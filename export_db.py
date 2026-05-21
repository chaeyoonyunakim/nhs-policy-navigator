"""
Export nhs_chunks and query_log from MongoDB Atlas to JSON files.
Uses the same connection as the app -- no port 27017 firewall issues.
Run with: python export_db.py
"""
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

uri = os.environ["MONGODB_URI"]
db_name = os.environ.get("DB_NAME", "agentic-evolution-hackathon")

print(f"Connecting to MongoDB...")
client = MongoClient(uri)
db = client[db_name]

os.makedirs("dump", exist_ok=True)


def export_collection(col_name):
    col = db[col_name]
    docs = list(col.find({}))
    print(f"  Found {len(docs)} documents in {col_name}")

    for doc in docs:
        doc["_id"] = str(doc["_id"])
        for k, v in doc.items():
            if isinstance(v, datetime):
                doc[k] = v.isoformat()

    out_path = f"dump/{col_name}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)

    size_mb = os.path.getsize(out_path) / 1_000_000
    print(f"  Saved {out_path} ({size_mb:.1f} MB)")


print(f"Exporting database: {db_name}")
export_collection("nhs_chunks")
export_collection("query_log")
print("Done. Files are in ./dump/")
