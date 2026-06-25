"""NHS Policy Navigator -- FastAPI backend.

Exposes query, stats, history and health endpoints over the adaptive
retrieval agent. Run locally with::

    uvicorn nhs_policy_navigator.app:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pymongo import MongoClient

from .agent import adaptive_retrieve
from .config import get_settings
from .logging_config import get_logger
from .router import build_digest

logger = get_logger(__name__)
settings = get_settings()

mongo = MongoClient(settings.mongodb_uri)
db = mongo[settings.db_name]
chunks_col = db[settings.chunks_collection]
log_col = db[settings.log_collection]
digest_col = db[settings.digest_collection]

logger.info("Startup complete; connected to database %s", settings.db_name)

app = FastAPI(title="NHS Policy Navigator", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class QueryRequest(BaseModel):
    """Request body for the query endpoint."""

    query: str


@app.post("/api/query")
async def query_endpoint(request: QueryRequest) -> dict:
    """Run the adaptive retrieval pipeline for a single query."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    return adaptive_retrieve(
        query=request.query, chunks_col=chunks_col, log_col=log_col, digest_col=digest_col
    )


@app.get("/api/stats")
async def stats_endpoint() -> dict:
    """Return strategy performance, query-type distribution and recent queries."""
    strategy_perf = list(
        log_col.aggregate(
            [
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
    type_perf = list(
        log_col.aggregate(
            [
                {
                    "$group": {
                        "_id": "$query_type",
                        "avg_score": {"$avg": "$relevance_score"},
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"count": -1}},
            ]
        )
    )
    recent = list(
        log_col.find(
            {},
            {
                "query": 1,
                "query_type": 1,
                "strategy": 1,
                "relevance_score": 1,
                "strategy_source": 1,
                "care_settings": 1,
                "professional_groups": 1,
                "_id": 0,
            },
        )
        .sort("timestamp", -1)
        .limit(8)
    )
    return {
        "total_queries": log_col.count_documents({}),
        "strategy_performance": strategy_perf,
        "type_performance": type_perf,
        "recent_queries": recent,
    }


@app.get("/api/queries")
async def queries_endpoint(
    page: int = 1,
    per_page: int = 10,
    setting: str | None = None,
    group: str | None = None,
) -> dict:
    """Return a paginated history of every query asked, newest first.

    The append-only log is never collapsed here -- ``setting`` and ``group``
    only *filter* the full history by NHS care setting or professional group.
    """
    per_page = max(1, min(per_page, 50))
    query_filter: dict = {}
    if setting:
        query_filter["care_settings"] = setting
    if group:
        query_filter["professional_groups"] = group
    total = log_col.count_documents(query_filter)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    docs = list(
        log_col.find(
            query_filter,
            {
                "query": 1,
                "query_type": 1,
                "strategy": 1,
                "relevance_score": 1,
                "strategy_source": 1,
                "care_settings": 1,
                "professional_groups": 1,
                "timestamp": 1,
                "_id": 0,
            },
        )
        .sort("timestamp", -1)
        .skip((page - 1) * per_page)
        .limit(per_page)
    )
    for doc in docs:
        timestamp = doc.get("timestamp")
        if timestamp is not None:
            doc["timestamp"] = timestamp.isoformat() + "Z"
    return {
        "queries": docs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


@app.get("/api/digest")
async def digest_endpoint(facet: str = "setting") -> dict:
    """Return deduped past questions grouped by NHS domain for the main page.

    ``facet`` selects the grouping: ``setting`` (care setting) or ``group``
    (professional group). Duplicates are collapsed into one cluster carrying an
    ``asked_count``; the full, ungrouped history stays on ``/api/queries``.
    """
    return build_digest(facet, digest_col)


@app.get("/api/health")
async def health() -> dict:
    """Liveness check reporting the number of indexed chunks."""
    return {"status": "ok", "chunks_in_db": chunks_col.count_documents({})}


if not settings.is_serverless:
    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")
