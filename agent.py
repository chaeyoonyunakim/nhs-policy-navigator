"""
NHS Policy Navigator -- Adaptive Multi-Source Retrieval Agent
Pipeline: classify -> select_sources -> retrieve (plan + live news) -> rerank -> generate -> evaluate -> log -> adapt
"""
from datetime import datetime
import xml.etree.ElementTree as ET

import httpx
from openai import OpenAI
from pymongo.collection import Collection
from langsmith import traceable


@traceable(name="get_embedding")
def get_embedding(text: str, openai_client: OpenAI) -> list:
    response = openai_client.embeddings.create(
        input=text[:8000], model="text-embedding-3-small"
    )
    return response.data[0].embedding


@traceable(name="classify_query")
def classify_query(query: str, openai_client: OpenAI) -> str:
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


def select_sources(query_type: str) -> list:
    """Route queries to sources. factual -> plan only. Others -> plan + live news."""
    if query_type == "factual":
        return ["plan"]
    return ["plan", "news"]


def retrieve_text(query: str, collection: Collection, n: int = 6) -> list:
    try:
        return list(collection.aggregate([
            {"$search": {"index": "text_index", "text": {"query": query, "path": "text", "fuzzy": {"maxEdits": 1}}}},
            {"$limit": n},
            {"$project": {"text": 1, "source": 1, "page": 1, "chunk_id": 1, "score": {"$meta": "searchScore"}}}
        ]))
    except Exception as e:
        print(f"[text search error] {e}")
        return []


def retrieve_vector(query: str, collection: Collection, openai_client: OpenAI, n: int = 6) -> list:
    try:
        embedding = get_embedding(query, openai_client)
        return list(collection.aggregate([
            {"$vectorSearch": {"index": "vector_index", "path": "embedding", "queryVector": embedding, "numCandidates": 100, "limit": n}},
            {"$project": {"text": 1, "source": 1, "page": 1, "chunk_id": 1, "score": {"$meta": "vectorSearchScore"}}}
        ]))
    except Exception as e:
        print(f"[vector search error] {e}")
        return []


def retrieve_hybrid(query: str, collection: Collection, openai_client: OpenAI, n: int = 6) -> list:
    vector_results = retrieve_vector(query, collection, openai_client, n)
    text_results = retrieve_text(query, collection, n)
    seen, merged = set(), []
    for r in vector_results + text_results:
        rid = str(r.get("_id", r.get("chunk_id", "")))
        if rid not in seen:
            seen.add(rid)
            merged.append(r)
    return merged[:n]


@traceable(name="fetch_nhs_news")
def fetch_nhs_news(query: str, openai_client: OpenAI, max_candidates: int = 20) -> list:
    """Fetch live NHS England RSS news and rank top 3 items by query relevance."""
    try:
        r = httpx.get(
            "https://www.england.nhs.uk/feed/",
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "NHS-Policy-Navigator/1.0"}
        )
        r.raise_for_status()
    except Exception as e:
        print(f"[news HTTP error] {e}")
        return []

    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        print(f"[news XML error] {e}")
        return []

    items = []
    for item in root.findall(".//item")[:max_candidates]:
        title = (item.findtext("title") or "").strip()
        link  = (item.findtext("link")  or "").strip()
        desc  = (item.findtext("description") or "").strip()
        date  = (item.findtext("pubDate") or "").strip()
        if title and link:
            items.append({"title": title, "link": link, "description": desc[:400], "pub_date": date, "source_type": "nhs_news"})

    if not items:
        return []

    numbered = "\n".join(f"{i+1}. {it['title']}: {it['description'][:120]}" for i, it in enumerate(items))
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Rank NHS news items for relevance to the query. Return ONLY top-3 item numbers comma-separated e.g. 3,7,12"},
                {"role": "user", "content": f"Query: {query}\n\nNews items:\n{numbered}"}
            ],
            max_tokens=20
        )
        raw = resp.choices[0].message.content.strip()
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        return [items[i] for i in indices if 0 <= i < len(items)][:3]
    except Exception as e:
        print(f"[news rank error] {e}")
        return items[:3]


@traceable(name="rerank_chunks")
def rerank_chunks(query: str, chunks: list, openai_client: OpenAI) -> list:
    """Re-rank plan chunks by LLM relevance score 0-10. Addresses 'reordering results based on input'."""
    if len(chunks) <= 1:
        return chunks
    numbered = "\n".join(f"{i+1}. {c.get('text','')[:200]}" for i, c in enumerate(chunks[:8]))
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Score each chunk 0-10 for how directly it answers the query. Return ONLY comma-separated numbers e.g. 8,3,9,5,2"},
                {"role": "user", "content": f"Query: {query}\n\nChunks:\n{numbered}"}
            ],
            max_tokens=40
        )
        raw = resp.choices[0].message.content.strip()
        scores = []
        for x in raw.split(","):
            try:
                scores.append(float(x.strip()))
            except ValueError:
                scores.append(5.0)
        for i, chunk in enumerate(chunks[:len(scores)]):
            chunk["rerank_score"] = scores[i]
        return sorted(chunks, key=lambda c: c.get("rerank_score", 5.0), reverse=True)
    except Exception as e:
        print(f"[rerank error] {e}")
        return chunks


@traceable(name="generate_answer")
def generate_answer(query: str, query_type: str, chunks: list, openai_client: OpenAI, news_items: list = None) -> str:
    """Generate grounded answer from plan chunks + optional live news."""
    if news_items is None:
        news_items = []

    if not chunks and not news_items:
        return "No relevant content found in the NHS 10 Year Health Plan or recent NHS news for this query. This may represent a genuine gap."

    plan_context = "\n\n".join([
        f"[NHS Plan -- {c.get('source','').replace('_',' ').title()}, p.{c.get('page','?')}]: {c.get('text','')}"
        for c in chunks[:5]
    ])

    news_context = ""
    if news_items:
        news_context = "\n\nLIVE NHS NEWS:\n" + "\n".join([
            f"[{n['pub_date'][:16]}] {n['title']}: {n['description'][:300]}"
            for n in news_items
        ])

    type_instructions = {
        "factual":      "Give a direct, precise answer in 2-3 sentences. Lead with the specific fact, figure or target.",
        "conceptual":   "Write a crisp executive-summary paragraph (4-5 sentences). State the core idea, mechanism, and one key milestone.",
        "comparative":  "Compare in exactly 2 short paragraphs -- one per side. Be direct, no padding.",
        "gap_analysis": "One paragraph: state clearly whether the plan addresses this. If recent news fills the gap, note it."
    }

    multi_source = ""
    if news_items:
        multi_source = " Where relevant, note whether the plan's stated intention matches recent NHS announcements. Distinguish: cite plan pages as (p.X) and news as (NHS News, date)."

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a senior NHS policy analyst. Dense, precise, no filler. Every sentence must carry information.\n\n"
                    f"{type_instructions.get(query_type,'')}{multi_source}\n\n"
                    "Rules: cite plan page numbers inline e.g. (p.24), include year targets, max 180 words."
                )
            },
            {"role": "user", "content": f"Query: {query}\n\nContext from NHS 10 Year Health Plan:\n{plan_context}{news_context}"}
        ],
        max_tokens=300
    )
    return response.choices[0].message.content


@traceable(name="evaluate_relevance")
def evaluate_relevance(query: str, chunks: list, openai_client: OpenAI) -> float:
    if not chunks:
        return 1.0
    context = "\n---\n".join([c.get("text", "")[:300] for c in chunks[:3]])
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Rate how well this NHS policy context answers the query. Return ONLY a number 1-5."},
                {"role": "user", "content": f"Query: {query}\n\nContext:\n{context}"}
            ],
            max_tokens=5
        )
        score = float(response.choices[0].message.content.strip().split()[0])
        return min(max(score, 1.0), 5.0)
    except Exception:
        return 3.0


def adaptive_retrieve(query: str, chunks_col: Collection, log_col: Collection, openai_client: OpenAI) -> dict:
    """
    Full adaptive multi-source retrieval pipeline:
    1. Classify -> 2. Select sources -> 3. Check history -> 4. Retrieve plan ->
    5. Re-rank -> 6. Fetch live news -> 7. Generate -> 8. Evaluate -> 9. Log -> 10. Return
    """
    # 1. Classify
    query_type = classify_query(query, openai_client)

    # 2. Select sources
    sources = select_sources(query_type)

    # 3. Check historical strategy performance
    history = list(log_col.aggregate([
        {"$match": {"query_type": query_type}},
        {"$group": {"_id": "$strategy", "avg_score": {"$avg": "$relevance_score"}, "count": {"$sum": 1}}},
        {"$sort": {"avg_score": -1}}
    ]))

    default_strategy = {
        "factual": "text_search", "conceptual": "vector_search",
        "comparative": "hybrid_search", "gap_analysis": "vector_search"
    }

    if history and history[0]["count"] >= 5:
        strategy = history[0]["_id"]
        strategy_source = "learned"
    else:
        strategy = default_strategy.get(query_type, "vector_search")
        strategy_source = "default"

    # 4. Retrieve from MongoDB Atlas
    if strategy == "text_search":
        chunks = retrieve_text(query, chunks_col)
    elif strategy == "hybrid_search":
        chunks = retrieve_hybrid(query, chunks_col, openai_client)
    else:
        chunks = retrieve_vector(query, chunks_col, openai_client)

    # 5. Re-rank plan chunks
    chunks = rerank_chunks(query, chunks, openai_client)

    # 6. Fetch live NHS news
    news_items = []
    if "news" in sources:
        news_items = fetch_nhs_news(query, openai_client)

    # 7. Generate answer
    answer = generate_answer(query, query_type, chunks, openai_client, news_items)

    # 8. Evaluate
    score = evaluate_relevance(query, chunks, openai_client)

    # 9. Log to MongoDB
    log_col.insert_one({
        "query": query, "query_type": query_type,
        "strategy": strategy, "strategy_source": strategy_source,
        "sources_queried": sources, "news_fetched": len(news_items),
        "relevance_score": score, "chunk_count": len(chunks),
        "timestamp": datetime.utcnow()
    })

    # 10. Return
    return {
        "query": query, "query_type": query_type,
        "strategy": strategy, "strategy_source": strategy_source,
        "sources_queried": sources, "answer": answer,
        "sources": [
            {"text": c.get("text","")[:220] + "...", "source": c.get("source","NHS Plan").replace("_"," ").title(),
             "page": c.get("page","?"), "score": round(c.get("rerank_score", 5.0), 1)}
            for c in chunks[:4]
        ],
        "news_items": news_items, "relevance_score": score, "strategy_history": history
    }
