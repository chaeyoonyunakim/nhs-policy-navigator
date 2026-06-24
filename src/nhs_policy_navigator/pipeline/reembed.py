"""Re-embed all stored chunks with the configured Gemini embedding model.

Useful after changing the embedding model or dimensions. Run with::

    python -m nhs_policy_navigator.pipeline.reembed
"""

from __future__ import annotations

import time

from pymongo import MongoClient

from ..config import get_settings
from ..gemini import embed
from ..logging_config import get_logger

logger = get_logger(__name__)


def main() -> None:
    """Re-embed every document in the chunks collection in place."""
    settings = get_settings()
    mongo = MongoClient(settings.mongodb_uri)
    col = mongo[settings.db_name][settings.chunks_collection]

    docs = list(col.find({}, {"_id": 1, "text": 1}))
    logger.info("Re-embedding %d documents with %s", len(docs), settings.embedding_model)

    errors = 0
    for i, doc in enumerate(docs):
        try:
            embedding = embed(doc["text"], task_type="RETRIEVAL_DOCUMENT")
            col.update_one({"_id": doc["_id"]}, {"$set": {"embedding": embedding}})
            if (i + 1) % 50 == 0:
                logger.info("%d/%d done", i + 1, len(docs))
            time.sleep(0.05)
        except Exception as err:  # noqa: BLE001 - continue past transient failures
            errors += 1
            logger.error("Error on document %d: %s", i, err)
            time.sleep(2)

    logger.info("Done. %d updated, %d errors", len(docs) - errors, errors)
    mongo.close()


if __name__ == "__main__":
    main()
