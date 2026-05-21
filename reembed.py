"""
Re-embed all nhs_chunks using Gemini text-embedding-004 (768 dims).
Run AFTER updating the Atlas vector_index to numDimensions: 768.
Run with: python reembed.py
"""
import os
import time
from dotenv import load_dotenv
from pymongo import MongoClient
import google.generativeai as genai

load_dotenv()

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
client = MongoClient(os.environ["MONGODB_URI"])
db = client[os.environ.get("DB_NAME", "agentic-evolution-hackathon")]
col = db["nhs_chunks"]

docs = list(col.find({}, {"_id": 1, "text": 1}))
print(f"Re-embedding {len(docs)} documents with Gemini text-embedding-004...")

for i, doc in enumerate(docs):
    try:
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=doc["text"][:8000],
            task_type="retrieval_document"
        )
        col.update_one(
            {"_id": doc["_id"]},
            {"$set": {"embedding": result["embedding"]}}
        )
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(docs)} done")
        time.sleep(0.1)  # stay within free tier rate limits
    except Exception as e:
        print(f"  Error on doc {i}: {e}")
        time.sleep(2)

print("Done. All embeddings updated to 768 dims.")
