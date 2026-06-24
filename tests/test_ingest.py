"""Unit tests for the ingestion pipeline's pure helpers."""

from __future__ import annotations

from nhs_policy_navigator.pipeline import ingest


def test_chunk_text_splits_with_overlap() -> None:
    text = " ".join(f"word{i}" for i in range(400))
    chunks = ingest.chunk_text(text, max_words=180, overlap=30)

    assert len(chunks) >= 2
    # Consecutive chunks overlap by ``overlap`` words.
    first_tail = chunks[0].split()[-30:]
    second_head = chunks[1].split()[:30]
    assert first_tail == second_head


def test_chunk_text_drops_tiny_fragments() -> None:
    assert ingest.chunk_text("too short") == []


def test_chunk_text_empty_input() -> None:
    assert ingest.chunk_text("") == []
