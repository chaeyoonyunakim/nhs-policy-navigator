"""Query Router -- categorise and de-duplicate past questions.

The router runs alongside the retrieval pipeline. For every query it:

1. **Tags** the question with NHS domains from a fixed taxonomy -- a *care
   setting* and a *professional group*, multi-label so one query can carry
   several tags (e.g. ``Acute`` + ``Medical``).
2. **De-duplicates** by embedding similarity: if the new query is close enough
   (cosine >= :data:`DEDUP_THRESHOLD`) to a question already seen, it bumps an
   "asked N times" counter on the existing digest cluster instead of creating a
   new one.

This powers two surfaces with distinct jobs: the main-page *digest* shows a
curated, deduped, categorised view (``query_digest``), while the *Previous
queries* tab keeps the complete, append-only log (``query_log``). Tagging and
routing degrade gracefully -- a failure here never blocks an answer.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from pymongo.collection import Collection

from .gemini import generate
from .logging_config import get_logger

logger = get_logger(__name__)

# -- Fixed NHS taxonomy --------------------------------------------------------
# Care setting and professional group are *independent* facets, so tagging is
# multi-label: a query may appear under several settings and/or groups.

CARE_SETTINGS: tuple[str, ...] = (
    "Acute",
    "Ambulance",
    "Community",
    "Mental Health and Learning Disability",
    "Primary Care",
    "Primary Care - Wider Primary Care",
)

PROFESSIONAL_GROUPS: tuple[str, ...] = (
    "Medical",
    "Clinical non-medical",
    "Dentistry",
)

# Cosine similarity at or above which two queries are treated as the same
# question and collapsed into a single digest cluster.
DEDUP_THRESHOLD = 0.92

# Definitions handed to the tagger so close categories do not bleed together.
# "Wider Primary Care" is community/high-street pharmacy and dentistry; plain
# "Primary Care" is GP / general practice.
_TAG_PROMPT = (
    "Tag this NHS policy query with the NHS domains it relates to. "
    "A query can match several tags, one, or none.\n\n"
    "CARE SETTING -- choose any that apply:\n"
    "- Acute: hospital-based acute, emergency and elective care\n"
    "- Ambulance: ambulance services and urgent patient transport\n"
    "- Community: community health services delivered outside hospital\n"
    "- Mental Health and Learning Disability: mental health, learning "
    "disability and autism services\n"
    "- Primary Care: GP and general practice\n"
    "- Primary Care - Wider Primary Care: community / high-street pharmacy and "
    "dentistry\n\n"
    "PROFESSIONAL GROUP -- choose any that apply:\n"
    "- Medical: doctors and the medical workforce\n"
    "- Clinical non-medical: nurses, allied health professionals and other "
    "clinical non-medical staff\n"
    "- Dentistry: dental workforce and services\n\n"
    "Return EXACTLY two lines, using the tag names verbatim:\n"
    "CARE: <comma-separated tags, or NONE>\n"
    "GROUP: <comma-separated tags, or NONE>\n\n"
    "Query: "
)


def _match_taxonomy(values: list[str], allowed: tuple[str, ...]) -> list[str]:
    """Return the canonical, deduplicated taxonomy values found in ``values``."""
    lookup = {item.lower(): item for item in allowed}
    matched: list[str] = []
    for raw in values:
        canonical = lookup.get(raw.strip().lower())
        if canonical and canonical not in matched:
            matched.append(canonical)
    return matched


def _parse_facet_response(raw: str) -> dict[str, list[str]]:
    """Parse the tagger's ``CARE:`` / ``GROUP:`` reply into validated tags.

    Unknown or malformed labels are dropped; the result only ever contains
    values from the fixed taxonomy.
    """
    care: list[str] = []
    group: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("care:"):
            body = stripped.split(":", 1)[1]
            if body.strip().upper() != "NONE":
                care = _match_taxonomy(body.split(","), CARE_SETTINGS)
        elif lower.startswith("group:"):
            body = stripped.split(":", 1)[1]
            if body.strip().upper() != "NONE":
                group = _match_taxonomy(body.split(","), PROFESSIONAL_GROUPS)
    return {"care_settings": care, "professional_groups": group}


def tag_facets(query: str) -> dict[str, list[str]]:
    """Multi-label tag ``query`` with care settings and professional groups.

    Reuses the existing Gemini wrapper. On any failure it returns empty tag
    lists so the surrounding pipeline keeps working.
    """
    try:
        raw = generate(_TAG_PROMPT + query)
    except Exception as err:  # noqa: BLE001 - tagging must never block a query
        logger.error("Facet tagging failed: %s", err)
        return {"care_settings": [], "professional_groups": []}
    return _parse_facet_response(raw)


# -- De-duplication ------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of two equal-length vectors (0.0 if degenerate)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_duplicate(
    embedding: list[float],
    clusters: list[dict],
    threshold: float = DEDUP_THRESHOLD,
) -> dict | None:
    """Return the existing cluster most similar to ``embedding``, if any.

    The closest cluster is returned only when its cosine similarity is at or
    above ``threshold`` -- otherwise the query is treated as a new question.
    """
    best: dict | None = None
    best_score = threshold
    for cluster in clusters:
        score = cosine_similarity(embedding, cluster.get("embedding", []))
        if score >= best_score:
            best_score = score
            best = cluster
    return best


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    """Append any ``incoming`` values not already present in ``existing``."""
    merged = list(existing)
    for value in incoming:
        if value not in merged:
            merged.append(value)
    return merged


def route_to_digest(
    query: str,
    embedding: list[float],
    facets: dict[str, list[str]],
    score: float,
    strategy: str,
    digest_col: Collection,
) -> None:
    """Add ``query`` to the deduped digest, or bump an existing cluster.

    Implements the router's bump-or-add rule: if a near-identical question
    already exists (cosine >= :data:`DEDUP_THRESHOLD`) its ``asked_count`` is
    incremented and its facets/score refreshed; otherwise a new cluster is
    created. Failures are swallowed so the digest never blocks a response.
    """
    if not embedding:
        return
    try:
        projection = {
            "embedding": 1,
            "asked_count": 1,
            "care_settings": 1,
            "professional_groups": 1,
        }
        clusters = list(digest_col.find({}, projection))
        match = find_duplicate(embedding, clusters)
        now = datetime.now(timezone.utc)
        if match is not None:
            digest_col.update_one(
                {"_id": match["_id"]},
                {
                    "$inc": {"asked_count": 1},
                    "$max": {"best_score": score},
                    "$set": {
                        "last_strategy": strategy,
                        "last_asked": now,
                        "care_settings": _merge_unique(
                            match.get("care_settings", []), facets["care_settings"]
                        ),
                        "professional_groups": _merge_unique(
                            match.get("professional_groups", []), facets["professional_groups"]
                        ),
                    },
                },
            )
        else:
            digest_col.insert_one(
                {
                    "canonical_query": query,
                    "embedding": embedding,
                    "care_settings": facets["care_settings"],
                    "professional_groups": facets["professional_groups"],
                    "asked_count": 1,
                    "best_score": score,
                    "last_strategy": strategy,
                    "first_asked": now,
                    "last_asked": now,
                }
            )
    except Exception as err:  # noqa: BLE001 - digest upkeep is best-effort
        logger.error("Digest routing failed: %s", err)


# -- Digest read model ---------------------------------------------------------

_FACET_FIELD = {"setting": "care_settings", "group": "professional_groups"}
_FACET_KEYS = {"setting": CARE_SETTINGS, "group": PROFESSIONAL_GROUPS}

# Most-asked deduplicated questions shown per category in the main-page digest.
DIGEST_TOP_N = 10


def build_digest(facet: str, digest_col: Collection) -> dict:
    """Group deduped clusters by the chosen ``facet`` for the main-page digest.

    ``facet`` is ``"setting"`` (care setting) or ``"group"`` (professional
    group). Because tagging is multi-label, a cluster appears under every tag it
    carries. Within each group the most-asked questions come first, capped at
    the top :data:`DIGEST_TOP_N`. Empty groups are omitted; the embedding is
    never returned to the client.
    """
    if facet not in _FACET_FIELD:
        facet = "setting"
    field = _FACET_FIELD[facet]

    clusters = list(
        digest_col.find(
            {},
            {
                "canonical_query": 1,
                "care_settings": 1,
                "professional_groups": 1,
                "asked_count": 1,
                "best_score": 1,
                "last_strategy": 1,
                "_id": 0,
            },
        )
    )

    buckets: dict[str, list[dict]] = {key: [] for key in _FACET_KEYS[facet]}
    for cluster in clusters:
        entry = {
            "query": cluster.get("canonical_query", ""),
            "asked_count": cluster.get("asked_count", 1),
            "best_score": round(float(cluster.get("best_score", 0.0)), 1),
            "last_strategy": cluster.get("last_strategy", ""),
        }
        for tag in cluster.get(field, []):
            if tag in buckets:
                buckets[tag].append(entry)

    groups = []
    for key, entries in buckets.items():
        if not entries:
            continue
        ranked = sorted(entries, key=lambda e: (e["asked_count"], e["best_score"]), reverse=True)
        top = ranked[:DIGEST_TOP_N]
        groups.append({"key": key, "count": len(top), "total": len(entries), "queries": top})
    return {"facet": facet, "groups": groups}
