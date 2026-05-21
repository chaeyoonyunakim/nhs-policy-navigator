"""
NHS Policy Navigator -- Adaptive Multi-Source Retrieval Agent
Pipeline: classify -> select_sources -> retrieve (plan + live news + publications) -> rerank -> generate -> evaluate -> log -> adapt
"""
from datetime import datetime
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import os

import httpx
import google.generativeai as genai
from pymongo.collection import Collection
from langsmith import traceable

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
_llm = genai.GenerativeModel("gemini-2.0-flash")
_embed_model = "models/text-embedding-004"


# -- Embedding -----------------------------------------------------------------

@traceable(name="get_embedding")
def get_embedding(text: str) -> list:
    result = genai.embed_content(
        model=_embed_model,
        content=text[:8000],
        task_type="retrieval_query"
    )
    return result["embedding"]


# -- Query Classification ------------------------------------------------------

@traceable(name="classify_query")
def classify_query(query: str) -> str:
    prompt = (
        "Classify this NHS policy query into exactly one type:\n"
        "- factual: specific fact, number, target, date, named policy, or statistic\n"
        "- conceptual: themes, strategies, approaches, or how something works\n"
        "- comparative: comparing two or more things, policies, or approaches\n"
        "- gap_analysis: what is missing, not addressed, or absent from the plan\n\n"
        "Return ONLY the type name.\n\nQuery: " + query
    )
    response = _llm.generate_content(prompt)
    result = response.text.strip().lower()
    return result if result in {"factual", "conceptual", "comparative", "gap_analysis"} else "conceptual"


# -- Source Selection ----------------------------------------------------------

def select_sources(query_type: str) -> list:
    if query_type == "factual":
        return ["plan"]
    if query_type == "gap_analysis":
        return ["plan", "news", "publications"]
    return ["plan", "news"]


# -- NHS Plan Retrieval (MongoDB Atlas) ----------------------------------------

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


def retrieve_vector(query: str, collection: Collection, n: int = 6) -> list:
    try:
        embedding = get_embedding(query)
        return list(collection.aggregate([
            {"$vectorSearch": {"index": "vector_index", "path": "embedding", "queryVector": embedding, "numCandidates": 100, "limit": n}},
            {"$project": {"text": 1, "source": 1, "page": 1, "chunk_id": 1, "score": {"$meta": "vectorSearchScore"}}}
        ]))
    except Exception as e:
        print(f"[vector search error] {e}")
        return []


def retrieve_hybrid(query: str, collection: Collection, n: int = 6) -> list:
    vector_results = retrieve_vector(query, collection, n)
    text_results = retrieve_text(query, collection, n)
    seen, merged = set(), []
    for r in vector_results + text_results:
        rid = str(r.get("_id", r.get("chunk_id", "")))
        if rid not in seen:
            seen.add(rid)
            merged.append(r)
    return merged[:n]


# -- Live NHS News via RSS -----------------------------------------------------

@traceable(name="fetch_nhs_news")
def fetch_nhs_news(query: str, max_candidates: int = 20) -> list:
    try:
        r = httpx.get("https://www.england.nhs.uk/feed/", timeout=10.0,
                      follow_redirects=True, headers={"User-Agent": "NHS-Policy-Navigator/1.0"})
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
            items.append({"title": title, "link": link, "description": desc[:400],
                          "pub_date": date, "source_type": "nhs_news"})
    if not items:
        return []

    numbered = "\n".join(f"{i+1}. {it['title']}: {it['description'][:120]}" for i, it in enumerate(items))
    try:
        resp = _llm.generate_content(
            "Rank these NHS news items for relevance to the query. "
            "Return ONLY top-3 item numbers comma-separated e.g. 3,7,12\n\n"
            "Query: " + query + "\n\nNews items:\n" + numbered
        )
        raw = resp.text.strip()
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        return [items[i] for i in indices if 0 <= i < len(items)][:3]
    except Exception as e:
        print(f"[news rank error] {e}")
        return items[:3]


# -- NHS Publications post July 2025 -------------------------------------------

PUBLICATION_SEEDS = [
    {
        "title": "Fit for the future: towards population health delivery models",
        "link": "https://www.england.nhs.uk/publication/fit-for-the-future-towards-population-health-delivery-models/",
        "description": "Sets out how population-based delivery models introduced in the 10 Year Health Plan can be used by integrated care boards and providers to improve outcomes and reduce inequalities.",
        "pub_date": "17 Mar 2026",
        "source_type": "nhs_publication"
    },
    {
        "title": "Fit for the Future: 10 Year Health Plan -- open letter to staff",
        "link": "https://www.england.nhs.uk/publication/fit-for-the-future-10-year-health-plan-for-england-open-letter-to-staff/",
        "description": "Open letter from NHS England chief executive to all NHS staff on what the 10 Year Health Plan means for the workforce and frontline delivery.",
        "pub_date": "3 Jul 2025",
        "source_type": "nhs_publication"
    },
    {
        "title": "Change NHS: help build a health service fit for the future",
        "link": "https://www.england.nhs.uk/publication/change-nhs-help-build-a-health-service-fit-for-the-future/",
        "description": "Summary of the public engagement process that shaped the 10 Year Health Plan, including responses on prevention, primary care, mental health and digital transformation.",
        "pub_date": "3 Jul 2025",
        "source_type": "nhs_publication"
    },
]

PLAN_CUTOFF = "2025-07-03"


@traceable(name="fetch_nhs_publications")
def fetch_nhs_publications(query: str) -> list:
    live_pubs = []
    try:
        r = httpx.get("https://www.england.nhs.uk/feed/", timeout=10.0,
                      follow_redirects=True, headers={"User-Agent": "NHS-Policy-Navigator/1.0"})
        r.raise_for_status()
        root = ET.fromstring(r.text)
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            if "/publication/" not in link:
                continue
            date_str = (item.findtext("pubDate") or "").strip()
            try:
                if parsedate_to_datetime(date_str).date().isoformat() < PLAN_CUTOFF:
                    continue
            except Exception:
                pass
            title = (item.findtext("title") or "").strip()
            desc  = (item.findtext("description") or "").strip()
            if title and link:
                live_pubs.append({"title": title, "link": link, "description": desc[:400],
                                  "pub_date": date_str, "source_type": "nhs_publication"})
    except Exception as e:
        print(f"[publications fetch error] {e}")

    seen_links = {p["link"] for p in live_pubs}
    all_pubs = live_pubs + [s for s in PUBLICATION_SEEDS if s["link"] not in seen_links]

    if not all_pubs:
        return []

    numbered = "\n".join(f"{i+1}. {p['title']}: {p['description'][:150]}" for i, p in enumerate(all_pubs))
    try:
        resp = _llm.generate_content(
            "Rank these NHS publications for relevance to the query. "
            "Return ONLY top-3 item numbers comma-separated e.g. 1,3,2\n\n"
            "Query: " + query + "\n\nPublications:\n" + numbered
        )
        raw = resp.text.strip()
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        return [all_pubs[i] for i in indices if 0 <= i < len(all_pubs)][:3]
    except Exception as e:
        print(f"[publications rank error] {e}")
        return all_pubs[:3]


# -- Re-ranking ----------------------------------------------------------------

@traceable(name="rerank_chunks")
def rerank_chunks(query: str, chunks: list) -> list:
    if len(chunks) <= 1:
        return chunks
    numbered = "\n".join(f"{i+1}. {c.get('text','')[:200]}" for i, c in enumerate(chunks[:8]))
    try:
        resp = _llm.generate_content(
            "Score each chunk 0-10 for how directly it answers the query. "
            "Return ONLY comma-separated numbers e.g. 8,3,9,5,2\n\n"
            "Query: " + query + "\n\nChunks:\n" + numbered
        )
        raw = resp.text.strip()
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


# -- Answer Generation ---------------------------------------------------------

@traceable(name="generate_answer")
def generate_answer(query: str, query_type: str, chunks: list,
                    news_items: list = None, pub_items: list = None) -> str:
    if news_items is None:
        news_items = []
    if pub_items is None:
        pub_items = []

    if not chunks and not news_items and not pub_items:
        return "No relevant content found in the NHS 10 Year Health Plan, recent news, or related publications for this query. This may represent a genuine gap."

    plan_context = "\n\n".join([
        "[NHS Plan -- " + c.get("source","").replace("_"," ").title() + ", p." + str(c.get("page","?")) + "]: " + c.get("text","")
        for c in chunks[:5]
    ])

    news_context = ""
    if news_items:
        news_context = "\n\nLIVE NHS NEWS:\n" + "\n".join([
            "[" + n["pub_date"][:16] + "] " + n["title"] + ": " + n["description"][:300]
            for n in news_items
        ])

    pub_context = ""
    if pub_items:
        pub_context = "\n\nRELATED NHS PUBLICATIONS (post July 2025):\n" + "\n".join([
            "[" + p["pub_date"][:16] + "] " + p["title"] + ": " + p["description"][:300]
            for p in pub_items
        ])

    type_instructions = {
        "factual":      "Give a direct, precise answer in 2-3 sentences. Lead with the specific fact, figure or target.",
        "conceptual":   "Write a crisp executive-summary paragraph (4-5 sentences). State the core idea, mechanism, and one key milestone.",
        "comparative":  "Compare in exactly 2 short paragraphs -- one per side. Be direct, no padding.",
        "gap_analysis": "One paragraph: state clearly whether the plan addresses this. If recent news or publications fill the gap, note it."
    }

    multi_source = ""
    if news_items or pub_items:
        parts = []
        if news_items:
            parts.append("recent NHS news (cite as: NHS News, date)")
        if pub_items:
            parts.append("post-July-2025 NHS publications (cite as: NHS Publication, title)")
        multi_source = " Cross-reference plan text with " + " and ".join(parts) + ". Distinguish sources clearly."

    prompt = (
        "You are a senior NHS policy analyst. Dense, precise, no filler. Every sentence must carry information.\n\n"
        + type_instructions.get(query_type, "") + multi_source + "\n\n"
        "Rules: cite plan page numbers inline e.g. (p.24), include year targets, max 180 words.\n\n"
        "Query: " + query + "\n\nContext from NHS 10 Year Health Plan:\n" + plan_context + news_context + pub_context
    )
    response = _llm.generate_content(prompt)
    return response.text


# -- Evaluation ----------------------------------------------------------------

@traceable(name="evaluate_relevance")
def evaluate_relevance(query: str, chunks: list) -> float:
    if not chunks:
        return 1.0
    context = "\n---\n".join([c.get("text", "")[:300] for c in chunks[:3]])
    try:
        response = _llm.generate_content(
            "Rate how well this NHS policy context answers the query. Return ONLY a number 1-5.\n\n"
            "Query: " + query + "\n\nContext:\n" + context
        )
        score = float(response.text.strip().split()[0])
        return min(max(score, 1.0), 5.0)
    except Exception:
        return 3.0


# -- Main Pipeline -------------------------------------------------------------

def adaptive_retrieve(query: str, chunks_col: Collection, log_col: Collection) -> dict:
    # 1. Classify
    query_type = classify_query(query)

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
        chunks = retrieve_hybrid(query, chunks_col)
    else:
        chunks = retrieve_vector(query, chunks_col)

    # 5. Re-rank plan chunks
    chunks = rerank_chunks(query, chunks)

    # 6. Fetch live sources
    news_items = []
    if "news" in sources:
        news_items = fetch_nhs_news(query)

    pub_items = []
    if "publications" in sources:
        pub_items = fetch_nhs_publications(query)

    # 7. Generate answer
    answer = generate_answer(query, query_type, chunks, news_items, pub_items)

    # 8. Evaluate
    score = evaluate_relevance(query, chunks)

    # 9. Log to MongoDB
    log_col.insert_one({
        "query": query, "query_type": query_type,
        "strategy": strategy, "strategy_source": strategy_source,
        "sources_queried": sources, "news_fetched": len(news_items),
        "pubs_fetched": len(pub_items), "relevance_score": score,
        "chunk_count": len(chunks), "timestamp": datetime.utcnow()
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
        "news_items": news_items, "pub_items": pub_items,
        "relevance_score": score, "strategy_history": history
    }
