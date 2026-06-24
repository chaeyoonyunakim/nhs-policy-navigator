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

    Supports the subset of operations exercised by the agent and router:
    ``aggregate`` returns a preset result; ``insert_one`` records inserted
    documents; ``find`` returns stored documents; and ``update_one`` applies the
    ``$inc`` / ``$max`` / ``$set`` operators used by the digest router.
    """

    def __init__(self, aggregate_result: list | None = None, documents: list | None = None) -> None:
        self.aggregate_result = aggregate_result or []
        self.documents: list[dict] = documents or []
        self.inserted: list[dict] = []

    def aggregate(self, _pipeline: list) -> list:
        return list(self.aggregate_result)

    def insert_one(self, document: dict) -> None:
        document.setdefault("_id", len(self.documents) + 1)
        self.documents.append(document)
        self.inserted.append(document)

    def find(self, _filter: dict | None = None, _projection: dict | None = None) -> list:
        return list(self.documents)

    def update_one(self, query: dict, update: dict) -> None:
        for doc in self.documents:
            if all(doc.get(key) == value for key, value in query.items()):
                for field, amount in update.get("$inc", {}).items():
                    doc[field] = doc.get(field, 0) + amount
                for field, value in update.get("$max", {}).items():
                    doc[field] = max(doc.get(field, value), value)
                for field, value in update.get("$set", {}).items():
                    doc[field] = value
                break


@pytest.fixture
def fake_collection() -> FakeCollection:
    """Return a fresh fake MongoDB collection."""
    return FakeCollection()
