"""
Re-embed all nhs_chunks using Gemini gemini-embedding-001 (768 dims).
Calls the REST API directly via httpx — no SDK versioning issues.
Run with: python reembed.py
"""
import os
import time
import httpx
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

API_KEY = os.environ["GOOGLE_API_KEY"]
EMBED_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={API_KEY}"

mongo = MongoClient(os.environ["MONGODB_URI"])
db = mongo[os.environ.get("DB_NAME", "agentic-evolution-hackathon")]
col = db["nhs_chunks"]


def embed_text(text: str) -> list:
    r = httpx.post(EMBED_URL, json={
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text[:8000]}]},
        "taskType": "RETRIEVAL_DOCUMENT"
    }, timeout=30.0)
    r.raise_for_status()
    return r.json()["embedding"]["values"]


docs = list(col.find({}, {"_id": 1, "text": 1}))
print(f"Re-embedding {len(docs)} documents with Gemini gemini-embedding-001...")

errors = 0
for i, doc in enumerate(docs):
    try:
        embedding = embed_text(doc["text"])
        col.update_one({"_id": doc["_id"]}, {"$set": {"embedding": embedding}})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(docs)} done")
        time.sleep(0.05)
    except Exception as e:
        errors += 1
        print(f"  Error on doc {i}: {e}")
        time.sleep(2)

print(f"Done. {len(docs)-errors} updated, {errors} errors.")
