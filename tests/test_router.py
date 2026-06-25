"""Unit tests for the Query Router -- facet tagging, dedup and the digest.

All Gemini and MongoDB interactions are mocked; tests focus on the
deterministic tagging, similarity and grouping logic.
"""

from __future__ import annotations

import pytest

from nhs_policy_navigator import router
from tests.conftest import FakeCollection

# -- Facet response parsing ----------------------------------------------------


def test_parse_facet_response_extracts_valid_tags() -> None:
    raw = "CARE: Acute, Mental Health and Learning Disability\nGROUP: Medical"
    parsed = router._parse_facet_response(raw)
    assert parsed["care_settings"] == ["Acute", "Mental Health and Learning Disability"]
    assert parsed["professional_groups"] == ["Medical"]


def test_parse_facet_response_drops_unknown_and_dedupes() -> None:
    raw = "CARE: Acute, Acute, Wizardry\nGROUP: NONE"
    parsed = router._parse_facet_response(raw)
    assert parsed["care_settings"] == ["Acute"]
    assert parsed["professional_groups"] == []


def test_parse_facet_response_is_case_insensitive() -> None:
    raw = "care: primary care\ngroup: dentistry"
    parsed = router._parse_facet_response(raw)
    assert parsed["care_settings"] == ["Primary Care"]
    assert parsed["professional_groups"] == ["Dentistry"]


def test_tag_facets_degrades_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_prompt: str) -> str:
        raise RuntimeError("gemini down")

    monkeypatch.setattr(router, "generate", boom)
    assert router.tag_facets("q") == {"care_settings": [], "professional_groups": []}


# -- Cosine similarity ---------------------------------------------------------


def test_cosine_similarity_identical_vectors() -> None:
    assert router.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors() -> None:
    assert router.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_handles_degenerate_input() -> None:
    assert router.cosine_similarity([], [1.0]) == 0.0
    assert router.cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


# -- Duplicate detection -------------------------------------------------------


def test_find_duplicate_returns_match_above_threshold() -> None:
    clusters = [
        {"_id": 1, "embedding": [0.0, 1.0]},
        {"_id": 2, "embedding": [1.0, 0.0]},
    ]
    match = router.find_duplicate([0.99, 0.01], clusters)
    assert match is not None and match["_id"] == 2


def test_find_duplicate_returns_none_when_all_below_threshold() -> None:
    clusters = [{"_id": 1, "embedding": [0.0, 1.0]}]
    assert router.find_duplicate([1.0, 0.0], clusters) is None


# -- Digest routing (bump vs add) ----------------------------------------------


def test_route_to_digest_adds_new_cluster() -> None:
    digest = FakeCollection()
    facets = {"care_settings": ["Acute"], "professional_groups": ["Medical"]}
    router.route_to_digest("waiting times?", [1.0, 0.0], facets, 4.0, "text_search", digest)
    assert len(digest.inserted) == 1
    assert digest.inserted[0]["asked_count"] == 1
    assert digest.inserted[0]["canonical_query"] == "waiting times?"


def test_route_to_digest_bumps_existing_cluster() -> None:
    digest = FakeCollection(
        documents=[
            {
                "_id": 1,
                "canonical_query": "GP access targets?",
                "embedding": [1.0, 0.0],
                "care_settings": ["Primary Care"],
                "professional_groups": [],
                "asked_count": 2,
                "best_score": 3.0,
            }
        ]
    )
    facets = {"care_settings": ["Primary Care"], "professional_groups": ["Medical"]}
    router.route_to_digest("GP access target by 2028", [0.99, 0.0], facets, 5.0, "vector_search", digest)

    assert digest.inserted == []  # no new cluster
    cluster = digest.documents[0]
    assert cluster["asked_count"] == 3
    assert cluster["best_score"] == 5.0
    assert cluster["professional_groups"] == ["Medical"]  # merged in


def test_route_to_digest_skips_empty_embedding() -> None:
    digest = FakeCollection()
    facets = {"care_settings": [], "professional_groups": []}
    router.route_to_digest("q", [], facets, 4.0, "text_search", digest)
    assert digest.inserted == []


# -- Digest read model ---------------------------------------------------------


def test_build_digest_groups_by_setting_and_sorts() -> None:
    digest = FakeCollection(
        documents=[
            {
                "canonical_query": "A&E plans?",
                "care_settings": ["Acute"],
                "professional_groups": ["Medical"],
                "asked_count": 1,
                "best_score": 4.0,
                "last_strategy": "text_search",
            },
            {
                "canonical_query": "Elective waiting list?",
                "care_settings": ["Acute"],
                "professional_groups": [],
                "asked_count": 3,
                "best_score": 5.0,
                "last_strategy": "hybrid_search",
            },
        ]
    )
    result = router.build_digest("setting", digest)
    assert result["facet"] == "setting"
    acute = next(g for g in result["groups"] if g["key"] == "Acute")
    assert acute["count"] == 2
    # Most-asked question comes first.
    assert acute["queries"][0]["query"] == "Elective waiting list?"
    assert acute["queries"][0]["asked_count"] == 3


def test_build_digest_multi_label_appears_in_each_group() -> None:
    digest = FakeCollection(
        documents=[
            {
                "canonical_query": "mental health staffing in acute trusts",
                "care_settings": ["Acute", "Mental Health and Learning Disability"],
                "professional_groups": ["Medical"],
                "asked_count": 2,
                "best_score": 4.0,
                "last_strategy": "vector_search",
            }
        ]
    )
    keys = {g["key"] for g in router.build_digest("setting", digest)["groups"]}
    assert keys == {"Acute", "Mental Health and Learning Disability"}


def test_build_digest_omits_empty_groups() -> None:
    digest = FakeCollection(documents=[])
    assert router.build_digest("group", digest)["groups"] == []


def test_build_digest_falls_back_to_setting_for_unknown_facet() -> None:
    digest = FakeCollection(documents=[])
    assert router.build_digest("bogus", digest)["facet"] == "setting"


def test_build_digest_caps_each_group_at_top_n() -> None:
    # 12 distinct Acute questions; only the 10 most-asked should be returned.
    documents = [
        {
            "canonical_query": f"acute question {i}",
            "care_settings": ["Acute"],
            "professional_groups": [],
            "asked_count": i,
            "best_score": 4.0,
            "last_strategy": "vector_search",
        }
        for i in range(1, 13)
    ]
    digest = FakeCollection(documents=documents)

    acute = next(g for g in router.build_digest("setting", digest)["groups"] if g["key"] == "Acute")

    assert len(acute["queries"]) == router.DIGEST_TOP_N == 10
    assert acute["count"] == 10
    assert acute["total"] == 12
    # Ranked most-asked first; the two least-asked (1, 2) are dropped.
    assert acute["queries"][0]["asked_count"] == 12
    assert acute["queries"][-1]["asked_count"] == 3
