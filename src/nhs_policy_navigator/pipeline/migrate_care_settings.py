"""One-off migration: remap stored care-setting tags to the three new buckets.

The care-setting taxonomy was simplified from six granular NHS settings to three
top-level buckets. Documents tagged before that change still carry the old
values, so they would no longer match any digest bucket. This script rewrites
the ``care_settings`` arrays in ``query_digest`` and ``query_log`` in place,
mapping each old value to its new bucket and de-duplicating the result.

Deterministic mapping (no LLM calls):

    Acute / Ambulance / Community /
    Mental Health and Learning Disability      -> Secondary care
    Primary Care                               -> Primary care
    Primary Care - Wider Primary Care          -> Wider Primary care

The migration is idempotent: values already in the new taxonomy are left as-is,
and unknown values are dropped. Run::

    python -m nhs_policy_navigator.pipeline.migrate_care_settings --dry-run
    python -m nhs_policy_navigator.pipeline.migrate_care_settings
"""

from __future__ import annotations

import argparse

from pymongo import MongoClient

from ..config import get_settings
from ..logging_config import get_logger
from ..router import CARE_SETTINGS

logger = get_logger(__name__)

# Old granular setting -> new bucket. New values map to themselves so the
# migration stays idempotent.
OLD_TO_NEW: dict[str, str] = {
    "Acute": "Secondary care",
    "Ambulance": "Secondary care",
    "Community": "Secondary care",
    "Mental Health and Learning Disability": "Secondary care",
    "Primary Care": "Primary care",
    "Primary Care - Wider Primary Care": "Wider Primary care",
    **{value: value for value in CARE_SETTINGS},
}

COLLECTIONS = ("query_digest", "query_log")


def remap(care_settings: list[str]) -> list[str]:
    """Map old care-setting values to the new buckets, de-duplicating in order.

    Unknown values (not in the old or new taxonomy) are dropped.
    """
    mapped: list[str] = []
    for value in care_settings:
        new_value = OLD_TO_NEW.get(value)
        if new_value and new_value not in mapped:
            mapped.append(new_value)
    return mapped


def migrate_collection(db, name: str, *, dry_run: bool) -> tuple[int, int]:
    """Rewrite care-setting tags in one collection.

    Returns ``(scanned, changed)`` document counts.
    """
    collection = db[name]
    scanned = 0
    changed = 0
    for doc in collection.find({"care_settings": {"$exists": True}}, {"care_settings": 1}):
        scanned += 1
        current = doc.get("care_settings") or []
        updated = remap(current)
        if updated == current:
            continue
        changed += 1
        logger.info("%s %s: %s -> %s", name, doc["_id"], current, updated)
        if not dry_run:
            collection.update_one({"_id": doc["_id"]}, {"$set": {"care_settings": updated}})
    logger.info("%s: scanned=%d changed=%d%s", name, scanned, changed, " (dry run)" if dry_run else "")
    return scanned, changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing to the database.",
    )
    args = parser.parse_args()

    settings = get_settings()
    client = MongoClient(settings.mongodb_uri)
    db = client[settings.db_name]
    try:
        total_changed = 0
        for name in COLLECTIONS:
            _, changed = migrate_collection(db, name, dry_run=args.dry_run)
            total_changed += changed
        verb = "Would update" if args.dry_run else "Updated"
        logger.info("%s %d document(s) across %s.", verb, total_changed, ", ".join(COLLECTIONS))
    finally:
        client.close()


if __name__ == "__main__":
    main()
