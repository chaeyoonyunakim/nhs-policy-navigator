"""Unit tests for the Gemini REST wrappers.

HTTP calls are mocked via ``monkeypatch`` so no requests leave the process.
"""

from __future__ import annotations

import httpx
import pytest

from nhs_policy_navigator import gemini


class FakeResponse:
    """Minimal stand-in for an ``httpx.Response``."""

    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]


def test_embed_returns_values(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"embedding": {"values": [0.1, 0.2, 0.3]}}
    monkeypatch.setattr(gemini.httpx, "post", lambda *_a, **_k: FakeResponse(payload))

    assert gemini.embed("hello") == [0.1, 0.2, 0.3]


def test_generate_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": "  generated  "}]}}]}
    monkeypatch.setattr(gemini.httpx, "post", lambda *_a, **_k: FakeResponse(payload))

    assert gemini.generate("prompt") == "generated"


def test_generate_raises_when_all_models_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_500(*_a, **_k) -> FakeResponse:
        return FakeResponse({}, status_code=500)

    monkeypatch.setattr(gemini.httpx, "post", always_500)

    with pytest.raises(RuntimeError, match="All Gemini generate models failed"):
        gemini.generate("prompt")
