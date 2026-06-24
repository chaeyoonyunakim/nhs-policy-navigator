"""Shared pytest fixtures and environment setup.

Required credentials are stubbed with dummy values so that configuration and
imports succeed without contacting any external service. No network or
database calls are made by the unit tests.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/test")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("DB_NAME", "test-db")


class FakeCollection:
    """Minimal in-memory stand-in for a pymongo ``Collection``.

    Supports the subset of operations exercised by the agent: ``aggregate``
    returns a preset result, and ``insert_one`` records inserted documents.
    """

    def __init__(self, aggregate_result: list | None = None) -> None:
        self.aggregate_result = aggregate_result or []
        self.inserted: list[dict] = []

    def aggregate(self, _pipeline: list) -> list:
        return list(self.aggregate_result)

    def insert_one(self, document: dict) -> None:
        self.inserted.append(document)


@pytest.fixture
def fake_collection() -> FakeCollection:
    """Return a fresh fake MongoDB collection."""
    return FakeCollection()
