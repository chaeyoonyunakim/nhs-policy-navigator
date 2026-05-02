"""
NHS Policy Navigator — FastAPI backend
Run with: uvicorn app:app --reload
Then open: http://localhost:8000
"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from openai import OpenAI
from langsmith.wrappers import wrap_openai
from agent import adaptive_retrieve

load_dotenv()

# ── Setup ─────────────────────────────────────────────────────────────────────
mongo = MongoClient(os.environ["MONGODB_URI"])
db = mongo[os.environ.get("DB_NAME", "nhs_hackathon")]
chunks_col = db["nhs_chunks"]
log_col = db["query_log"]

openai_client = wrap_openai(OpenAI(api_key=os.environ["OPENAI_API_KEY"]))

ELEVENLABS_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
print(f"[startup] ElevenLabs key loaded: {'YES (' + ELEVENLABS_KEY[:8] + '...)' if ELEVENLABS_KEY else 'NO — check .env'}")

app = FastAPI(title="NHS Policy Navigator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ── Request/Response Models ───────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str


# ── Routes ────────────────────────────────────────────────────────────────────
@app.post("/api/query")
async def query_endpoint(request: QueryRequest):
    """Main adaptive retrieval endpoint."""
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    result = adaptive_retrieve(
        query=request.query,
        chunks_col=chunks_col,
        log_col=log_col,
        openai_client=openai_client
    )
    return result


@app.get("/api/stats")
async def stats_endpoint():
    """Strategy performance stats — shows the system learning over time."""
    strategy_perf = list(log_col.aggregate([
        {"$group": {
            "_id": "$strategy",
            "avg_score": {"$avg": "$relevance_score"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"avg_score": -1}}
    ]))

    type_perf = list(log_col.aggregate([
        {"$group": {
            "_id": "$query_type",
            "avg_score": {"$avg": "$relevance_score"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"count": -1}}
    ]))

    recent = list(
        log_col.find({}, {"query": 1, "query_type": 1, "strategy": 1,
                          "relevance_score": 1, "strategy_source": 1, "_id": 0})
        .sort("timestamp", -1)
        .limit(8)
    )

    total = log_col.count_documents({})

    return {
        "total_queries": total,
        "strategy_performance": strategy_perf,
        "type_performance": type_perf,
        "recent_queries": recent
    }


@app.post("/api/narrate")
def narrate_endpoint(request: QueryRequest):
    """ElevenLabs voice narration — bonus prize feature."""
    if not ELEVENLABS_KEY:
        raise HTTPException(status_code=503, detail="ElevenLabs API key not configured.")

    import httpx
    text = request.query[:1500]  # keep it short for voice

    response = httpx.post(
        "https://api.elevenlabs.io/v1/text-to-speech/EXAVITQu4vr4xnSDxMaL",
        headers={
            "xi-api-key": ELEVENLABS_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        },
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8}
        },
        timeout=30.0
    )

    if response.status_code != 200:
        print(f"[ElevenLabs] {response.status_code}: {response.text[:400]}")
        raise HTTPException(
            status_code=502,
            detail=f"ElevenLabs {response.status_code}: {response.text[:300]}"
        )

    from fastapi.responses import Response
    return Response(content=response.content, media_type="audio/mpeg")


@app.get("/api/test-elevenlabs")
def test_elevenlabs():
    """Quick diagnostic — call this to check ElevenLabs connectivity."""
    import httpx
    if not ELEVENLABS_KEY:
        return {"status": "error", "detail": "No API key in .env"}
    r = httpx.get(
        "https://api.elevenlabs.io/v1/user",
        headers={"xi-api-key": ELEVENLABS_KEY},
        timeout=10.0
    )
    return {"status": r.status_code, "body": r.json()}


@app.get("/api/health")
async def health():
    chunk_count = chunks_col.count_documents({})
    return {"status": "ok", "chunks_in_db": chunk_count}


# ── Serve frontend ────────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")
