"""NHS Policy Navigator -- adaptive multi-source retrieval agent.

Pipeline stages:
``classify -> select_sources -> retrieve -> rerank -> generate -> evaluate ->
log -> adapt``. The agent reasons about *how* to retrieve and *which* sources
to use before retrieving, then logs every decision to MongoDB so it can adapt
its strategy over time.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from pymongo.collection import Collection

from .config import get_settings
from .gemini import embed, generate
from .logging_config import get_logger
from .router import route_to_digest, tag_facets

logger = get_logger(__name__)

_VALID_TYPES = {"factual", "conceptual", "comparative", "gap_analysis"}
_USER_AGENT = {"User-Agent": "NHS-Policy-Navigator/1.0"}

DEFAULT_STRATEGY = {
    "factual": "text_search",
    "conceptual": "vector_search",
    "comparative": "hybrid_search",
    "gap_analysis": "vector_search",
}

# Curated seed publications used when the live RSS feed yields too few results.
PUBLICATION_SEEDS = [
    {
        "title": "Fit for the future: towards population health delivery models",
        "link": "https://www.england.nhs.uk/publication/fit-for-the-future-towards-population-health-delivery-models/",
        "description": (
            "Sets out how population-based delivery models introduced in the 10 Year Health Plan can be used "
            "by integrated care boards and providers to improve outcomes and reduce inequalities."
        ),
        "pub_date": "17 Mar 2026",
        "source_type": "nhs_publication",
    },
    {
        "title": "Fit for the Future: 10 Year Health Plan -- open letter to staff",
        "link": "https://www.england.nhs.uk/publication/fit-for-the-future-10-year-health-plan-for-england-open-letter-to-staff/",
        "description": (
            "Open letter from NHS England chief executive to all NHS staff on what the 10 Year Health Plan "
            "means for the workforce and frontline delivery."
        ),
        "pub_date": "3 Jul 2025",
        "source_type": "nhs_publication",
    },
    {
        "title": "Change NHS: help build a health service fit for the future",
        "link": "https://www.england.nhs.uk/publication/change-nhs-help-build-a-health-service-fit-for-the-future/",
        "description": (
            "Summary of the public engagement process that shaped the 10 Year Health Plan, "
            "including responses on prevention, primary care, mental health and digital transformation."
        ),
        "pub_date": "3 Jul 2025",
        "source_type": "nhs_publication",
    },
]


# -- Embedding & LLM helpers ---------------------------------------------------


def get_embedding(text: str) -> list[float]:
    """Return the query embedding for ``text``."""
    return embed(text)


def llm(prompt: str) -> str:
    """Generate a response for ``prompt`` using the Gemini wrapper."""
    return generate(prompt)


# -- Query classification ------------------------------------------------------


def classify_query(query: str) -> str:
    """Classify ``query`` into one of the four supported policy query types."""
    result = llm(
        "Classify this NHS policy query into exactly one type:\n"
        "- factual: specific fact, number, target, date, named policy, or statistic\n"
        "- conceptual: themes, strategies, approaches, or how something works\n"
        "- comparative: comparing two or more things, policies, or approaches\n"
        "- gap_analysis: what is missing, not addressed, or absent from the plan\n\n"
        "Return ONLY the type name.\n\nQuery: " + query
    ).lower()
    return result if result in _VALID_TYPES else "conceptual"


# -- Source selection ----------------------------------------------------------


def select_sources(query_type: str) -> list[str]:
    """Choose which sources to query for a given ``query_type``."""
    if query_type == "factual":
        return ["plan"]
    if query_type == "gap_analysis":
        return ["plan", "news", "publications"]
    return ["plan", "news"]


# -- NHS plan retrieval (MongoDB Atlas) ----------------------------------------


def retrieve_text(query: str, collection: Collection, n: int = 6) -> list[dict]:
    """Full-text search over plan chunks via the Atlas ``text_index``."""
    try:
        return list(
            collection.aggregate(
                [
                    {
                        "$search": {
                            "index": "text_index",
                            "text": {"query": query, "path": "text", "fuzzy": {"maxEdits": 1}},
                        }
                    },
                    {"$limit": n},
                    {
                        "$project": {
                            "text": 1,
                            "source": 1,
                            "page": 1,
                            "chunk_id": 1,
                            "score": {"$meta": "searchScore"},
                        }
                    },
                ]
            )
        )
    except Exception as err:  # noqa: BLE001 - degrade gracefully on search errors
        logger.error("Text search failed: %s", err)
        return []


def retrieve_vector(query: str, collection: Collection, n: int = 6) -> list[dict]:
    """Vector search over plan chunks via the Atlas ``vector_index``."""
    try:
        embedding = get_embedding(query)
        return list(
            collection.aggregate(
                [
                    {
                        "$vectorSearch": {
                            "index": "vector_index",
                            "path": "embedding",
                            "queryVector": embedding,
                            "numCandidates": 100,
                            "limit": n,
                        }
                    },
                    {
                        "$project": {
                            "text": 1,
                            "source": 1,
                            "page": 1,
                            "chunk_id": 1,
                            "score": {"$meta": "vectorSearchScore"},
                        }
                    },
                ]
            )
        )
    except Exception as err:  # noqa: BLE001 - degrade gracefully on search errors
        logger.error("Vector search failed: %s", err)
        return []


def retrieve_hybrid(query: str, collection: Collection, n: int = 6) -> list[dict]:
    """Merge vector and text results, de-duplicating by document id."""
    vector_results = retrieve_vector(query, collection, n)
    text_results = retrieve_text(query, collection, n)
    seen: set[str] = set()
    merged: list[dict] = []
    for result in vector_results + text_results:
        rid = str(result.get("_id", result.get("chunk_id", "")))
        if rid not in seen:
            seen.add(rid)
            merged.append(result)
    return merged[:n]


# -- Live NHS news via RSS -----------------------------------------------------


def _fetch_rss_items(query: str, max_candidates: int = 20) -> list[dict]:
    """Fetch and parse news items from the NHS England RSS feed."""
    settings = get_settings()
    try:
        response = httpx.get(settings.nhs_rss_feed, timeout=10.0, follow_redirects=True, headers=_USER_AGENT)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except Exception as err:  # noqa: BLE001 - network/parse failures are non-fatal
        logger.error("News fetch failed: %s", err)
        return []

    items: list[dict] = []
    for item in root.findall(".//item")[:max_candidates]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        date = (item.findtext("pubDate") or "").strip()
        if title and link:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "description": desc[:400],
                    "pub_date": date,
                    "source_type": "nhs_news",
                }
            )
    return items


def fetch_nhs_news(query: str, max_candidates: int = 20) -> list[dict]:
    """Return the top-3 NHS news items ranked for relevance to ``query``."""
    items = _fetch_rss_items(query, max_candidates)
    if not items:
        return []
    numbered = "\n".join(f"{i + 1}. {it['title']}: {it['description'][:120]}" for i, it in enumerate(items))
    try:
        raw = llm(
            "Rank these NHS news items for relevance to the query. "
            "Return ONLY top-3 item numbers comma-separated e.g. 3,7,12\n\n"
            "Query: " + query + "\n\nNews items:\n" + numbered
        )
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        return [items[i] for i in indices if 0 <= i < len(items)][:3]
    except Exception as err:  # noqa: BLE001 - fall back to first items on ranking error
        logger.error("News ranking failed: %s", err)
        return items[:3]


# -- NHS publications post July 2025 -------------------------------------------


def fetch_nhs_publications(query: str) -> list[dict]:
    """Return the top-3 post-cutoff NHS publications relevant to ``query``."""
    settings = get_settings()
    live_pubs: list[dict] = []
    try:
        response = httpx.get(settings.nhs_rss_feed, timeout=10.0, follow_redirects=True, headers=_USER_AGENT)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        for item in root.findall(".//item"):
            link = (item.findtext("link") or "").strip()
            if "/publication/" not in link:
                continue
            date_str = (item.findtext("pubDate") or "").strip()
            try:
                if parsedate_to_datetime(date_str).date().isoformat() < settings.plan_cutoff:
                    continue
            except Exception:  # noqa: BLE001 - keep items with unparseable dates
                pass
            title = (item.findtext("title") or "").strip()
            desc = (item.findtext("description") or "").strip()
            if title and link:
                live_pubs.append(
                    {
                        "title": title,
                        "link": link,
                        "description": desc[:400],
                        "pub_date": date_str,
                        "source_type": "nhs_publication",
                    }
                )
    except Exception as err:  # noqa: BLE001 - seeds cover the failure case
        logger.error("Publications fetch failed: %s", err)

    seen_links = {pub["link"] for pub in live_pubs}
    all_pubs = live_pubs + [seed for seed in PUBLICATION_SEEDS if seed["link"] not in seen_links]
    if not all_pubs:
        return []

    numbered = "\n".join(f"{i + 1}. {p['title']}: {p['description'][:150]}" for i, p in enumerate(all_pubs))
    try:
        raw = llm(
            "Rank these NHS publications for relevance to the query. "
            "Return ONLY top-3 item numbers comma-separated e.g. 1,3,2\n\n"
            "Query: " + query + "\n\nPublications:\n" + numbered
        )
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip().isdigit()]
        return [all_pubs[i] for i in indices if 0 <= i < len(all_pubs)][:3]
    except Exception as err:  # noqa: BLE001 - fall back to first publications
        logger.error("Publications ranking failed: %s", err)
        return all_pubs[:3]


# -- Re-ranking ----------------------------------------------------------------


def rerank_chunks(query: str, chunks: list[dict]) -> list[dict]:
    """Re-rank plan ``chunks`` by an LLM relevance score (0-10)."""
    if len(chunks) <= 1:
        return chunks
    numbered = "\n".join(f"{i + 1}. {c.get('text', '')[:200]}" for i, c in enumerate(chunks[:8]))
    try:
        raw = llm(
            "Score each chunk 0-10 for how directly it answers the query. "
            "Return ONLY comma-separated numbers e.g. 8,3,9,5,2\n\n"
            "Query: " + query + "\n\nChunks:\n" + numbered
        )
        scores: list[float] = []
        for value in raw.split(","):
            try:
                scores.append(float(value.strip()))
            except ValueError:
                scores.append(5.0)
        for i, chunk in enumerate(chunks[: len(scores)]):
            chunk["rerank_score"] = scores[i]
        return sorted(chunks, key=lambda c: c.get("rerank_score", 5.0), reverse=True)
    except Exception as err:  # noqa: BLE001 - keep original order on ranking error
        logger.error("Re-ranking failed: %s", err)
        return chunks


# -- Answer generation ---------------------------------------------------------

_TYPE_INSTRUCTIONS = {
    "factual": (
        "Open with one declarative sentence that states the fact, figure or target directly — "
        "use the plan's own language where possible. Follow with one sentence of context or mechanism. "
        "Close with the specific commitment or milestone (year, scale, metric)."
    ),
    "conceptual": (
        "Open with a strong framing sentence that names the challenge or crossroads (mirroring the executive "
        "summary's style: 'The NHS faces...', 'This represents a decisive shift...'). "
        "Write 2-3 sentences on the approach and mechanism. "
        "Then list 2-3 specific, dated commitments as tight bullets, "
        "each with a figure or year where available."
    ),
    "comparative": (
        "Open with a sentence that frames what is being displaced and what replaces it. "
        "Write one short paragraph per side — each starting with a bold claim about that model's role, "
        "followed by the specific plan commitments that define it (cite pages and years). "
        "Close with one sentence on the financial or structural lever that drives the shift."
    ),
    "gap_analysis": (
        "Open with a direct verdict: does the plan address this or not? "
        "If addressed: name the policy, page, and target. "
        "If a gap: state it plainly — 'The plan does not set out...' — then note whether recent news or "
        "publications fill it. No hedging."
    ),
}

_STYLE_RULES = (
    "Writing style: mirror the NHS 10 Year Health Plan executive summary — "
    "authoritative, declarative, no filler. Use the plan's own terms and framing "
    "(e.g. 'three shifts', 'Neighbourhood Health Service', 'analogue to digital', "
    "'sickness to prevention', 'decisive shift'). "
    "Lead every answer with a strong claim, not a definition. "
    "Include specific figures, dates and targets wherever the context provides them. "
    "Cite plan pages inline (p.24). Max 200 words total."
)


def _build_context(chunks: list[dict], news_items: list[dict], pub_items: list[dict]) -> str:
    """Assemble the prompt context from plan chunks, news and publications."""
    plan_context = "\n\n".join(
        "[NHS Plan -- "
        + c.get("source", "").replace("_", " ").title()
        + ", p."
        + str(c.get("page", "?"))
        + "]: "
        + c.get("text", "")
        for c in chunks[:5]
    )
    news_context = ""
    if news_items:
        news_context = "\n\nLIVE NHS NEWS:\n" + "\n".join(
            "[" + n["pub_date"][:16] + "] " + n["title"] + ": " + n["description"][:300] for n in news_items
        )
    pub_context = ""
    if pub_items:
        pub_context = "\n\nRELATED NHS PUBLICATIONS (post July 2025):\n" + "\n".join(
            "[" + p["pub_date"][:16] + "] " + p["title"] + ": " + p["description"][:300] for p in pub_items
        )
    return plan_context + news_context + pub_context


def _multi_source_instruction(news_items: list[dict], pub_items: list[dict]) -> str:
    """Build the cross-referencing instruction when live sources are present."""
    if not (news_items or pub_items):
        return ""
    parts = []
    if news_items:
        parts.append("recent NHS news (cite as: NHS News, date)")
    if pub_items:
        parts.append("post-July-2025 NHS publications (cite as: NHS Publication, title)")
    return (
        " Cross-reference plan text with "
        + " and ".join(parts)
        + ". Where news or publications update or extend the plan, flag this explicitly. "
        "Distinguish sources clearly — plan text vs live context."
    )


def generate_answer(
    query: str,
    query_type: str,
    chunks: list[dict],
    news_items: list[dict] | None = None,
    pub_items: list[dict] | None = None,
) -> str:
    """Generate a grounded, source-aware answer in the plan's house style."""
    news_items = news_items or []
    pub_items = pub_items or []

    if not chunks and not news_items and not pub_items:
        return (
            "No relevant content found in the NHS 10 Year Health Plan for this query. "
            "This may represent a genuine gap."
        )

    instructions = _TYPE_INSTRUCTIONS.get(query_type, _TYPE_INSTRUCTIONS["conceptual"])
    context = _build_context(chunks, news_items, pub_items)
    return llm(
        "You are the author of the NHS 10 Year Health Plan executive summary. "
        "You write with authority, precision and urgency — "
        "every sentence carries a fact, target or commitment.\n\n"
        + _STYLE_RULES
        + "\n\n"
        + instructions
        + _multi_source_instruction(news_items, pub_items)
        + "\n\nQuery: "
        + query
        + "\n\nContext:\n"
        + context
    )


# -- Evaluation ----------------------------------------------------------------


def evaluate_relevance(query: str, chunks: list[dict]) -> float:
    """Self-evaluate retrieval quality on a 1-5 scale."""
    if not chunks:
        return 1.0
    context = "\n---\n".join(c.get("text", "")[:300] for c in chunks[:3])
    try:
        score = float(
            llm(
                "Rate how well this NHS policy context answers the query. Return ONLY a number 1-5.\n\n"
                "Query: " + query + "\n\nContext:\n" + context
            ).split()[0]
        )
        return min(max(score, 1.0), 5.0)
    except Exception:  # noqa: BLE001 - default to a neutral score
        return 3.0


# -- Strategy selection & main pipeline ----------------------------------------


def select_strategy(query_type: str, history: list[dict]) -> tuple[str, str]:
    """Pick a retrieval strategy, learning from history after enough runs.

    Returns:
        A ``(strategy, source)`` tuple where ``source`` is ``"learned"`` once a
        query type has five or more historical runs, else ``"default"``.
    """
    if history and history[0]["count"] >= 5:
        return history[0]["_id"], "learned"
    return DEFAULT_STRATEGY.get(query_type, "vector_search"), "default"


def _retrieve(strategy: str, query: str, collection: Collection) -> list[dict]:
    """Dispatch retrieval to the chosen strategy."""
    if strategy == "text_search":
        return retrieve_text(query, collection)
    if strategy == "hybrid_search":
        return retrieve_hybrid(query, collection)
    return retrieve_vector(query, collection)


def adaptive_retrieve(
    query: str,
    chunks_col: Collection,
    log_col: Collection,
    digest_col: Collection | None = None,
) -> dict:
    """Run the full adaptive retrieval pipeline for ``query``.

    Classifies the query, tags it with NHS domain facets, routes to sources,
    selects (or learns) a retrieval strategy, re-ranks results, generates an
    answer, self-evaluates and logs the full decision trail to MongoDB. When a
    ``digest_col`` is supplied, the query is also routed into the deduped,
    categorised digest that powers the main-page panel.
    """
    query_type = classify_query(query)
    facets = tag_facets(query)
    sources = select_sources(query_type)

    history = list(
        log_col.aggregate(
            [
                {"$match": {"query_type": query_type}},
                {
                    "$group": {
                        "_id": "$strategy",
                        "avg_score": {"$avg": "$relevance_score"},
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"avg_score": -1}},
            ]
        )
    )

    strategy, strategy_source = select_strategy(query_type, history)
    logger.info("Query classified as %s; using %s strategy (%s)", query_type, strategy, strategy_source)

    chunks = rerank_chunks(query, _retrieve(strategy, query, chunks_col))
    news_items = fetch_nhs_news(query) if "news" in sources else []
    pub_items = fetch_nhs_publications(query) if "publications" in sources else []
    answer = generate_answer(query, query_type, chunks, news_items, pub_items)
    score = evaluate_relevance(query, chunks)

    log_col.insert_one(
        {
            "query": query,
            "query_type": query_type,
            "strategy": strategy,
            "strategy_source": strategy_source,
            "sources_queried": sources,
            "care_settings": facets["care_settings"],
            "professional_groups": facets["professional_groups"],
            "news_fetched": len(news_items),
            "pubs_fetched": len(pub_items),
            "relevance_score": score,
            "chunk_count": len(chunks),
            "timestamp": datetime.now(timezone.utc),
        }
    )

    # Route into the deduped, categorised digest (best-effort; never blocks).
    if digest_col is not None:
        try:
            embedding = get_embedding(query)
        except Exception as err:  # noqa: BLE001 - dedup is best-effort
            logger.error("Digest embedding failed: %s", err)
            embedding = []
        route_to_digest(query, embedding, facets, score, strategy, digest_col)

    return {
        "query": query,
        "query_type": query_type,
        "strategy": strategy,
        "strategy_source": strategy_source,
        "sources_queried": sources,
        "care_settings": facets["care_settings"],
        "professional_groups": facets["professional_groups"],
        "answer": answer,
        "sources": [
            {
                "text": c.get("text", "")[:220] + "...",
                "source": c.get("source", "NHS Plan").replace("_", " ").title(),
                "page": c.get("page", "?"),
                "score": round(c.get("rerank_score", 5.0), 1),
            }
            for c in chunks[:4]
        ],
        "news_items": news_items,
        "pub_items": pub_items,
        "relevance_score": score,
        "strategy_history": history,
    }
