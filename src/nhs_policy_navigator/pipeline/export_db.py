"""Export collections from MongoDB Atlas to JSON files.

Uses the same connection as the app -- no port 27017 firewall issues. Run::

    python -m nhs_policy_navigator.pipeline.export_db
"""

from __future__ import annotations

import json
from datetime import datetime

from pymongo import MongoClient

from ..config import REPO_ROOT, get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)

DUMP_DIR = REPO_ROOT / "dump"


def export_collection(db, col_name: str) -> None:
    """Serialise a single collection to ``dump/<col_name>.json``."""
    docs = list(db[col_name].find({}))
    logger.info("Found %d documents in %s", len(docs), col_name)

    for doc in docs:
        doc["_id"] = str(doc["_id"])
        for key, value in doc.items():
            if isinstance(value, datetime):
                doc[key] = value.isoformat()

    out_path = DUMP_DIR / f"{col_name}.json"
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(docs, handle, ensure_ascii=False)

    size_mb = out_path.stat().st_size / 1_000_000
    logger.info("Saved %s (%.1f MB)", out_path, size_mb)


def main() -> None:
    """Export the chunks and query-log collections to JSON."""
    settings = get_settings()
    mongo = MongoClient(settings.mongodb_uri)
    db = mongo[settings.db_name]

    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Exporting database: %s", settings.db_name)
    export_collection(db, settings.chunks_collection)
    export_collection(db, settings.log_collection)
    logger.info("Done. Files are in %s", DUMP_DIR)
    mongo.close()


if __name__ == "__main__":
    main()
