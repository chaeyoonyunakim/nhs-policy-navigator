"""Unit tests for the configuration module."""

from __future__ import annotations

import pytest

from nhs_policy_navigator.config import Settings, get_settings


def test_from_env_reads_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb://example/db")
    monkeypatch.setenv("GOOGLE_API_KEY", "abc123")
    monkeypatch.setenv("DB_NAME", "custom-db")

    settings = Settings.from_env()

    assert settings.mongodb_uri == "mongodb://example/db"
    assert settings.google_api_key == "abc123"
    assert settings.db_name == "custom-db"


def test_from_env_raises_when_credentials_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Missing required environment variables"):
        Settings.from_env()


def test_defaults_are_sensible() -> None:
    settings = Settings(mongodb_uri="x", google_api_key="y")

    assert settings.embedding_dimensions == 768
    assert settings.generate_models[0] == "gemini-2.0-flash"
    assert settings.plan_cutoff == "2025-07-03"


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
