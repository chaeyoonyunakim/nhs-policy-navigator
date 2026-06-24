"""Unit tests for the adaptive retrieval agent.

All Gemini and MongoDB interactions are mocked; no network or database access
occurs. Tests focus on the deterministic decision logic of the pipeline.
"""

from __future__ import annotations

import pytest

from nhs_policy_navigator import agent
from tests.conftest import FakeCollection

# -- Source selection ----------------------------------------------------------


@pytest.mark.parametrize(
    ("query_type", "expected"),
    [
        ("factual", ["plan"]),
        ("conceptual", ["plan", "news"]),
        ("comparative", ["plan", "news"]),
        ("gap_analysis", ["plan", "news", "publications"]),
    ],
)
def test_select_sources(query_type: str, expected: list[str]) -> None:
    assert agent.select_sources(query_type) == expected


# -- Classification ------------------------------------------------------------


def test_classify_query_accepts_valid_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "llm", lambda _prompt: "Factual")
    assert agent.classify_query("How many GPs by 2028?") == "factual"


def test_classify_query_falls_back_to_conceptual(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "llm", lambda _prompt: "nonsense")
    assert agent.classify_query("anything") == "conceptual"


# -- Strategy selection --------------------------------------------------------


def test_select_strategy_uses_default_without_history() -> None:
    strategy, source = agent.select_strategy("comparative", [])
    assert strategy == "hybrid_search"
    assert source == "default"


def test_select_strategy_learns_after_five_runs() -> None:
    history = [{"_id": "text_search", "avg_score": 4.8, "count": 7}]
    strategy, source = agent.select_strategy("conceptual", history)
    assert strategy == "text_search"
    assert source == "learned"


def test_select_strategy_ignores_thin_history() -> None:
    history = [{"_id": "text_search", "avg_score": 5.0, "count": 3}]
    strategy, source = agent.select_strategy("conceptual", history)
    assert strategy == "vector_search"
    assert source == "default"


# -- Hybrid retrieval de-duplication ------------------------------------------


def test_retrieve_hybrid_dedupes_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    vector = [{"_id": "a", "text": "v"}, {"_id": "b", "text": "v"}]
    text = [{"_id": "b", "text": "t"}, {"_id": "c", "text": "t"}]
    monkeypatch.setattr(agent, "retrieve_vector", lambda *_a, **_k: vector)
    monkeypatch.setattr(agent, "retrieve_text", lambda *_a, **_k: text)

    merged = agent.retrieve_hybrid("q", FakeCollection(), n=6)

    assert [r["_id"] for r in merged] == ["a", "b", "c"]


# -- Re-ranking ----------------------------------------------------------------


def test_rerank_chunks_orders_by_score(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "llm", lambda _prompt: "2,9,5")
    chunks = [{"text": "low"}, {"text": "high"}, {"text": "mid"}]

    ranked = agent.rerank_chunks("q", chunks)

    assert [c["text"] for c in ranked] == ["high", "mid", "low"]


def test_rerank_chunks_noop_for_single_chunk() -> None:
    chunks = [{"text": "only"}]
    assert agent.rerank_chunks("q", chunks) == chunks


def test_rerank_chunks_handles_garbage_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "llm", lambda _prompt: "x,y")
    chunks = [{"text": "a"}, {"text": "b"}]
    # Both default to 5.0; order is preserved, no exception raised.
    assert agent.rerank_chunks("q", chunks) == chunks


# -- Answer generation ---------------------------------------------------------


def test_generate_answer_returns_gap_message_when_empty() -> None:
    answer = agent.generate_answer("q", "factual", [], [], [])
    assert "No relevant content" in answer


def test_generate_answer_passes_context_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "An authoritative answer."

    monkeypatch.setattr(agent, "llm", fake_llm)
    chunks = [{"text": "GP access target", "source": "full_plan", "page": 24}]

    answer = agent.generate_answer("q", "factual", chunks)

    assert answer == "An authoritative answer."
    assert "GP access target" in captured["prompt"]


# -- Evaluation ----------------------------------------------------------------


def test_evaluate_relevance_empty_returns_one() -> None:
    assert agent.evaluate_relevance("q", []) == 1.0


def test_evaluate_relevance_clamps_to_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "llm", lambda _prompt: "9")
    assert agent.evaluate_relevance("q", [{"text": "ctx"}]) == 5.0


def test_evaluate_relevance_defaults_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "llm", lambda _prompt: "not a number")
    assert agent.evaluate_relevance("q", [{"text": "ctx"}]) == 3.0


# -- End-to-end pipeline (fully mocked) ---------------------------------------


def test_adaptive_retrieve_logs_and_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent, "classify_query", lambda _q: "factual")
    monkeypatch.setattr(agent, "_retrieve", lambda *_a: [{"text": "chunk", "source": "full_plan", "page": 1}])
    monkeypatch.setattr(agent, "rerank_chunks", lambda _q, chunks: chunks)
    monkeypatch.setattr(agent, "generate_answer", lambda *_a: "answer")
    monkeypatch.setattr(agent, "evaluate_relevance", lambda *_a: 4.0)

    log_col = FakeCollection()
    result = agent.adaptive_retrieve("q", FakeCollection(), log_col)

    assert result["query_type"] == "factual"
    assert result["strategy_source"] == "default"
    assert result["answer"] == "answer"
    assert len(log_col.inserted) == 1
    assert log_col.inserted[0]["relevance_score"] == 4.0
