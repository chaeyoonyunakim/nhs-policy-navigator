"""Thin wrappers for the Gemini REST API.

Calling the REST endpoints directly with ``httpx`` avoids SDK versioning
issues and keeps the dependency surface small. Embedding and generation both
read configuration (API key, model names) from :mod:`config`.
"""

from __future__ import annotations

import time

import httpx

from .config import get_settings
from .logging_config import get_logger

logger = get_logger(__name__)

_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={key}"
_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

_RETRYABLE_STATUS = (429, 503)
_MAX_ATTEMPTS = 3


def embed(text: str, task_type: str = "RETRIEVAL_QUERY") -> list[float]:
    """Return the embedding vector for ``text``.

    Args:
        text: Text to embed (truncated to 8,000 characters).
        task_type: Gemini embedding task type, e.g. ``RETRIEVAL_QUERY`` for
            queries or ``RETRIEVAL_DOCUMENT`` for indexed documents.
    """
    settings = get_settings()
    url = _EMBED_URL.format(model=settings.embedding_model, key=settings.google_api_key)
    response = httpx.post(
        url,
        json={
            "model": f"models/{settings.embedding_model}",
            "content": {"parts": [{"text": text[:8000]}]},
            "taskType": task_type,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["embedding"]["values"]


def generate(prompt: str) -> str:
    """Generate text for ``prompt``, falling back across configured models.

    Each model is retried on transient (429/503) errors with exponential
    backoff before moving to the next fallback model.

    Raises:
        RuntimeError: If every configured model fails.
    """
    settings = get_settings()
    last_err: Exception | None = None
    for model in settings.generate_models:
        url = _GENERATE_URL.format(model=model, key=settings.google_api_key)
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = httpx.post(
                    url,
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=60.0,
                )
                if response.status_code in _RETRYABLE_STATUS:
                    time.sleep(2**attempt)
                    continue
                response.raise_for_status()
                return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            except httpx.HTTPStatusError as err:
                last_err = err
                if err.response.status_code in _RETRYABLE_STATUS:
                    time.sleep(2**attempt)
                else:
                    break
            except Exception as err:  # noqa: BLE001 - logged and re-raised below
                last_err = err
                break
        logger.warning("Gemini model %s exhausted; trying next fallback", model)
    raise RuntimeError(f"All Gemini generate models failed. Last error: {last_err}")
