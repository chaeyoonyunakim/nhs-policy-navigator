"""
NHS Policy Navigator -- FastAPI backend
Run with: uvicorn app:app --reload
"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from agent import adaptive_retrieve

load_dotenv()

mongo = MongoClient(os.environ["MONGODB_URI"])
db = mongo[os.environ.get("DB_NAME", "agentic-evolution-hackathon")]
chunks_col = db["nhs_chunks"]
log_col = db["query_log"]

print(f"[startup] Google API key loaded: {'YES' if os.environ.get('GOOGLE_API_KEY') else 'NO'}")

app = FastAPI(title="NHS Policy Navigator")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class QueryRequest(BaseModel):
    query: str


@app.post("/api/query")
async def query_endpoint(request: QueryRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    return adaptive_retrieve(query=request.query, chunks_col=chunks_col, log_col=log_col)


@app.get("/api/stats")
async def stats_endpoint():
    strategy_perf = list(log_col.aggregate([
        {"$group": {"_id": "$strategy", "avg_score": {"$avg": "$relevance_score"}, "count": {"$sum": 1}}},
        {"$sort": {"avg_score": -1}}
    ]))
    type_perf = list(log_col.aggregate([
        {"$group": {"_id": "$query_type", "avg_score": {"$avg": "$relevance_score"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]))
    recent = list(
        log_col.find({}, {"query": 1, "query_type": 1, "strategy": 1,
                          "relevance_score": 1, "strategy_source": 1, "_id": 0})
        .sort("timestamp", -1).limit(8)
    )
    return {"total_queries": log_col.count_documents({}), "strategy_performance": strategy_perf,
            "type_performance": type_perf, "recent_queries": recent}


@app.get("/api/queries")
async def queries_endpoint(page: int = 1, per_page: int = 10):
    """Paginated history of every query asked, newest first."""
    per_page = max(1, min(per_page, 50))
    total = log_col.count_documents({})
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    docs = list(
        log_col.find({}, {"query": 1, "query_type": 1, "strategy": 1, "relevance_score": 1,
                          "strategy_source": 1, "timestamp": 1, "_id": 0})
        .sort("timestamp", -1).skip((page - 1) * per_page).limit(per_page)
    )
    for d in docs:
        ts = d.get("timestamp")
        if ts is not None:
            d["timestamp"] = ts.isoformat() + "Z"
    return {"queries": docs, "total": total, "page": page,
            "per_page": per_page, "total_pages": total_pages}


@app.get("/api/health")
async def health():
    return {"status": "ok", "chunks_in_db": chunks_col.count_documents({})}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
