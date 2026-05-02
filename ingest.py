"""
Ingest NHS PDFs into MongoDB Atlas.
Run this ONCE before starting the app.

Usage:
    python ingest.py

Expects both PDFs in the same folder as this script.
After running, go to MongoDB Atlas UI and create the two search indexes
(instructions printed at the end).
"""
import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel
from openai import OpenAI
import pypdf
import time

load_dotenv()

MONGO_URI = os.environ["MONGODB_URI"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DB_NAME = os.environ.get("DB_NAME", "nhs_hackathon")
COLLECTION = "nhs_chunks"

PDFS = [
    ("fit-for-the-future-10-year-health-plan-for-england-executive-summary.pdf", "executive_summary"),
    ("fit-for-the-future-10-year-health-plan-for-england.pdf", "full_plan"),
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, max_words: int = 180, overlap: int = 30) -> list[str]:
    """Split text into overlapping chunks of ~180 words."""
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i: i + max_words])
        if len(chunk.strip()) > 80:   # skip tiny fragments
            chunks.append(chunk.strip())
        i += max_words - overlap
    return chunks


def get_embedding(text: str, client: OpenAI) -> list:
    response = client.embeddings.create(
        input=text[:8000],
        model="text-embedding-3-small"
    )
    return response.data[0].embedding


def extract_pages(pdf_path: str) -> list[dict]:
    reader = pypdf.PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"page": i + 1, "text": text})
    return pages


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    mongo = MongoClient(MONGO_URI)
    db = mongo[DB_NAME]
    col = db[COLLECTION]

    print(f"Connected to MongoDB. Clearing existing chunks...")
    col.delete_many({})

    openai = OpenAI(api_key=OPENAI_API_KEY)

    total_chunks = 0
    for pdf_file, source_name in PDFS:
        if not os.path.exists(pdf_file):
            print(f"  [SKIP] {pdf_file} not found — skipping.")
            continue

        print(f"\nProcessing {pdf_file}...")
        pages = extract_pages(pdf_file)
        print(f"  Extracted {len(pages)} pages.")

        documents = []
        for page_data in pages:
            chunks = chunk_text(page_data["text"])
            for j, chunk in enumerate(chunks):
                embedding = get_embedding(chunk, openai)
                documents.append({
                    "text": chunk,
                    "embedding": embedding,
                    "source": source_name,
                    "page": page_data["page"],
                    "chunk_id": f"{source_name}_p{page_data['page']}_c{j}"
                })
                print(f"  Embedded: {source_name} p{page_data['page']} chunk {j+1}", end="\r")
                time.sleep(0.05)  # gentle rate limit

        if documents:
            col.insert_many(documents)
            print(f"\n  Inserted {len(documents)} chunks from {source_name}")
            total_chunks += len(documents)

    print(f"\n✅ Ingestion complete — {total_chunks} total chunks in MongoDB.\n")

    # ── Create Search Indexes ─────────────────────────────────────────────────
    print("Creating search indexes (this may take 1-2 minutes)...")

    try:
        # Drop existing indexes first (ignore errors if they don't exist)
        try:
            col.drop_search_index("vector_index")
            col.drop_search_index("text_index")
            time.sleep(5)
        except Exception:
            pass

        vector_index = SearchIndexModel(
            definition={
                "fields": [{
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": 1536,
                    "similarity": "cosine"
                }]
            },
            name="vector_index",
            type="vectorSearch"
        )

        text_index = SearchIndexModel(
            definition={
                "mappings": {
                    "dynamic": False,
                    "fields": {
                        "text": [{"type": "string"}]
                    }
                }
            },
            name="text_index",
            type="search"
        )

        col.create_search_indexes([vector_index, text_index])
        print("✅ Search indexes created! They take ~2 minutes to become READY in Atlas.")
        print("   Check: Atlas UI → your cluster → Search Indexes tab")
        print("   Wait until both show 'READY' before running app.py\n")

    except Exception as e:
        print(f"\n⚠️  Could not auto-create indexes: {e}")
        print("\nCreate them manually in MongoDB Atlas UI:")
        print("\n1) VECTOR INDEX — Atlas UI → Cluster → Search Indexes → Create:")
        print("""   {
     "fields": [{
       "type": "vector",
       "path": "embedding",
       "numDimensions": 1536,
       "similarity": "cosine"
     }]
   }
   Name: vector_index   Type: vectorSearch""")
        print("\n2) TEXT INDEX:")
        print("""   {
     "mappings": {
       "dynamic": false,
       "fields": { "text": [{"type": "string"}] }
     }
   }
   Name: text_index   Type: search""")

    mongo.close()


if __name__ == "__main__":
    # Quick check
    uri = os.environ.get("MONGODB_URI", "")
    if "YOUR_PASSWORD" in uri or "XXXXX" in uri:
        print("❌ Update MONGODB_URI in your .env file first!")
        print("   Get it from: MongoDB Atlas → Clusters → Connect → Connect your application")
        sys.exit(1)
    main()
