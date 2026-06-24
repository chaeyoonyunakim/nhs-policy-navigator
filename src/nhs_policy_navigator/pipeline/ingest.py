"""Ingest NHS PDFs into MongoDB Atlas using Gemini embeddings.

Run once before starting the app::

    python -m nhs_policy_navigator.pipeline.ingest

Both PDFs are expected in the repository root (see the README for filenames).
After running, the script creates the two Atlas Search indexes; wait for them
to become ``READY`` before querying.
"""

from __future__ import annotations

import time
from pathlib import Path

import pypdf
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from ..config import REPO_ROOT, get_settings
from ..gemini import embed
from ..logging_config import get_logger

logger = get_logger(__name__)

PDFS = [
    ("fit-for-the-future-10-year-health-plan-for-england-executive-summary.pdf", "executive_summary"),
    ("fit-for-the-future-10-year-health-plan-for-england.pdf", "full_plan"),
]


def chunk_text(text: str, max_words: int = 180, overlap: int = 30) -> list[str]:
    """Split ``text`` into overlapping chunks of roughly ``max_words`` words."""
    words = text.split()
    chunks: list[str] = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + max_words]).strip()
        if len(chunk) > 80:
            chunks.append(chunk)
        i += max_words - overlap
    return chunks


def extract_pages(pdf_path: str | Path) -> list[dict]:
    """Extract non-empty pages from a PDF as ``{page, text}`` records."""
    reader = pypdf.PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"page": i + 1, "text": text})
    return pages


def _build_documents(source_name: str, pages: list[dict]) -> list[dict]:
    """Embed every chunk on every page into MongoDB document records."""
    documents: list[dict] = []
    for page_data in pages:
        for j, chunk in enumerate(chunk_text(page_data["text"])):
            documents.append(
                {
                    "text": chunk,
                    "embedding": embed(chunk, task_type="RETRIEVAL_DOCUMENT"),
                    "source": source_name,
                    "page": page_data["page"],
                    "chunk_id": f"{source_name}_p{page_data['page']}_c{j}",
                }
            )
            time.sleep(0.05)  # gentle rate limit
    return documents


def _create_indexes(col) -> None:
    """Create the Atlas vector and text search indexes."""
    settings = get_settings()
    try:
        col.drop_search_index("vector_index")
        col.drop_search_index("text_index")
        time.sleep(5)
    except Exception:  # noqa: BLE001 - indexes may not exist yet
        pass

    vector_index = SearchIndexModel(
        definition={
            "fields": [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": settings.embedding_dimensions,
                    "similarity": "cosine",
                }
            ]
        },
        name="vector_index",
        type="vectorSearch",
    )
    text_index = SearchIndexModel(
        definition={"mappings": {"dynamic": False, "fields": {"text": [{"type": "string"}]}}},
        name="text_index",
        type="search",
    )
    col.create_search_indexes([vector_index, text_index])
    logger.info("Search indexes created; allow ~2 minutes to become READY in Atlas")


def main() -> None:
    """Ingest both PDFs and (re)create the Atlas search indexes."""
    settings = get_settings()
    mongo = MongoClient(settings.mongodb_uri)
    col = mongo[settings.db_name][settings.chunks_collection]

    logger.info("Connected to MongoDB (%s); clearing existing chunks", settings.db_name)
    col.delete_many({})

    total_chunks = 0
    for pdf_file, source_name in PDFS:
        pdf_path = REPO_ROOT / pdf_file
        if not pdf_path.exists():
            logger.warning("%s not found; skipping", pdf_file)
            continue
        logger.info("Processing %s", pdf_file)
        documents = _build_documents(source_name, extract_pages(pdf_path))
        if documents:
            col.insert_many(documents)
            total_chunks += len(documents)
            logger.info("Inserted %d chunks from %s", len(documents), source_name)

    logger.info("Ingestion complete -- %d total chunks in MongoDB", total_chunks)

    try:
        _create_indexes(col)
    except Exception as err:  # noqa: BLE001 - surface manual fallback instructions
        logger.error("Could not auto-create indexes: %s", err)
        logger.error("Create them manually in the Atlas UI (see README index configuration).")

    mongo.close()


if __name__ == "__main__":
    main()
