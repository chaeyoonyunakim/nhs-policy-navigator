"""
NHS Policy Adaptive Retrieval Agent
Core logic: classify → strategy select → retrieve → evaluate → log → adapt
"""
from datetime import datetime
from openai import OpenAI
from pymongo.collection import Collection
from langsmith import traceable
from langsmith.wrappers import wrap_openai


@traceable(name="get_embedding")
def get_embedding(text: str, openai_client: OpenAI) -> list:
    response = openai_client.embeddings.create(
        input=text[:8000],
        model="text-embedding-3-small"
    )
    return response.data[0].embedding


@traceable(name="classify_query")
def classify_query(query: str, openai_client: OpenAI) -> str:
    """
    Classify query into one of four types to drive strategy selection.
    This is what makes the system 'agentic' — it decides HOW to retrieve.
    """
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Classify this NHS policy query into exactly one type:\n"
                    "- factual: specific fact, number, target, date, named policy, or statistic\n"
                    "- conceptual: themes, strategies, approaches, or how something works\n"
                    "- comparative: comparing two or more things, policies, or approaches\n"
                    "- gap_analysis: what is missing, not addressed, or absent from the plan\n\n"
                    "Return ONLY the type name."
                )
            },
            {"role": "user", "content": query}
        ],
        max_tokens=20
    )
    result = response.choices[0].message.content.strip().lower()
    return result if result in {"factual", "conceptual", "comparative", "gap_analysis"} else "conceptual"


def retrieve_text(query: str, collection: Collection, n: int = 6) -> list:
    """Atlas full-text search — best for specific terms, targets, named things."""
    try:
        return list(collection.aggregate([
            {
                "$search": {
                    "index": "text_index",
                    "text": {
                        "query": query,
                        "path": "text",
                        "fuzzy": {"maxEdits": 1}
                    }
                }
            },
            {"$limit": n},
            {"$project": {"text": 1, "source": 1, "page": 1, "chunk_id": 1,
                          "score": {"$meta": "searchScore"}}}
        ]))
    except Exception as e:
        print(f"[text search error] {e}")
        return []


def retrieve_vector(query: str, collection: Collection, openai_client: OpenAI, n: int = 6) -> list:
    """Atlas vector search — best for semantic/conceptual queries."""
    try:
        embedding = get_embedding(query, openai_client)
        return list(collection.aggregate([
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": embedding,
                    "numCandidates": 100,
                    "limit": n
                }
            },
            {"$project": {"text": 1, "source": 1, "page": 1, "chunk_id": 1,
                          "score": {"$meta": "vectorSearchScore"}}}
        ]))
    except Exception as e:
        print(f"[vector search error] {e}")
        return []


def retrieve_hybrid(query: str, collection: Collection, openai_client: OpenAI, n: int = 6) -> list:
    """Hybrid: run both searches, merge, deduplicate — best for comparisons."""
    vector_results = retrieve_vector(query, collection, openai_client, n)
    text_results = retrieve_text(query, collection, n)
    seen, merged = set(), []
    for r in vector_results + text_results:
        rid = str(r.get("_id", r.get("chunk_id", "")))
        if rid not in seen:
            seen.add(rid)
            merged.append(r)
    return merged[:n]


@traceable(name="evaluate_relevance")
def evaluate_relevance(query: str, chunks: list, openai_client: OpenAI) -> float:
    """LLM self-evaluation: scores how well chunks answer the query (1–5)."""
    if not chunks:
        return 1.0
    context = "\n---\n".join([c.get("text", "")[:300] for c in chunks[:3]])
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Rate how well this NHS policy context answers the query. Return ONLY a number 1-5."
                },
                {"role": "user", "content": f"Query: {query}\n\nContext:\n{context}"}
            ],
            max_tokens=5
        )
        score = float(response.choices[0].message.content.strip().split()[0])
        return min(max(score, 1.0), 5.0)
    except Exception:
        return 3.0


@traceable(name="generate_answer")
def generate_answer(query: str, query_type: str, chunks: list, openai_client: OpenAI) -> str:
    """Generate a grounded answer from retrieved chunks."""
    if not chunks:
        return (
            "No relevant content found in the NHS 10 Year Health Plan for this query. "
            "This may represent a genuine gap in the plan."
        )

    context = "\n\n".join([
        f"[{c.get('source','NHS Plan').replace('_',' ').title()}, p.{c.get('page','?')}]: {c.get('text','')}"
        for c in chunks[:5]
    ])

    instructions = {
        "factual":      "Give a direct, precise answer in 2-3 sentences. Lead with the specific fact, figure or target.",
        "conceptual":   "Write a crisp executive-summary paragraph (4-5 sentences). State the core idea, the mechanism, and one key milestone.",
        "comparative":  "Compare in exactly 2 short paragraphs — one per side. Be direct, no padding.",
        "gap_analysis": "One paragraph: state clearly whether the plan addresses this. If it does, quote the key passage. If not, name what IS covered nearby."
    }

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a senior NHS policy analyst. Write like the executive summary of the plan — "
                    "dense, precise, no filler. Every sentence must carry information.\n\n"
                    f"{instructions.get(query_type, '')}\n\n"
                    "Rules: cite page numbers inline e.g. (p.24), include relevant year targets, "
                    "maximum 150 words total."
                )
            },
            {
                "role": "user",
                "content": f"Query: {query}\n\nContext from NHS 10 Year Health Plan:\n\n{context}"
            }
        ],
        max_tokens=250
    )
    return response.choices[0].message.content


def adaptive_retrieve(
    query: str,
    chunks_col: Collection,
    log_col: Collection,
    openai_client: OpenAI
) -> dict:
    """
    Full adaptive retrieval pipeline:
    1. Classify query type
    2. Check MongoDB query history — if 5+ past queries of this type, let data decide strategy
    3. Retrieve using chosen strategy
    4. Generate answer
    5. Self-evaluate quality
    6. Write result back to MongoDB (enables future adaptation)
    7. Return everything for the UI
    """

    # --- Step 1: Classify ---
    query_type = classify_query(query, openai_client)

    # --- Step 2: Check historical performance ---
    history = list(log_col.aggregate([
        {"$match": {"query_type": query_type}},
        {"$group": {
            "_id": "$strategy",
            "avg_score": {"$avg": "$relevance_score"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"avg_score": -1}}
    ]))

    default_strategy = {
        "factual":      "text_search",
        "conceptual":   "vector_search",
        "comparative":  "hybrid_search",
        "gap_analysis": "vector_search"
    }

    if history and history[0]["count"] >= 5:
        strategy = history[0]["_id"]
        strategy_source = "learned"  # System adapted based on data!
    else:
        strategy = default_strategy.get(query_type, "vector_search")
        strategy_source = "default"

    # --- Step 3: Retrieve ---
    if strategy == "text_search":
        chunks = retrieve_text(query, chunks_col)
    elif strategy == "hybrid_search":
        chunks = retrieve_hybrid(query, chunks_col, openai_client)
    else:
        chunks = retrieve_vector(query, chunks_col, openai_client)

    # --- Step 4: Generate ---
    answer = generate_answer(query, query_type, chunks, openai_client)

    # --- Step 5: Evaluate ---
    score = evaluate_relevance(query, chunks, openai_client)

    # --- Step 6: Log to MongoDB ---
    log_col.insert_one({
        "query": query,
        "query_type": query_type,
        "strategy": strategy,
        "strategy_source": strategy_source,
        "relevance_score": score,
        "chunk_count": len(chunks),
        "timestamp": datetime.utcnow()
    })

    # --- Step 7: Return ---
    sources = [
        {
            "text": c.get("text", "")[:220] + "…",
            "source": c.get("source", "NHS Plan").replace("_", " ").title(),
            "page": c.get("page", "?")
        }
        for c in chunks[:4]
    ]

    return {
        "query": query,
        "query_type": query_type,
        "strategy": strategy,
        "strategy_source": strategy_source,
        "answer": answer,
        "sources": sources,
        "relevance_score": score,
        "strategy_history": history
    }
