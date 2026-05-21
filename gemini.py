"""
Thin wrappers for Gemini REST API — avoids SDK versioning issues.
"""
import os
import httpx

_API_KEY = None

def _key():
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ["GOOGLE_API_KEY"]
    return _API_KEY


def embed(text: str) -> list:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={_key()}"
    r = httpx.post(url, json={
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text[:8000]}]},
        "taskType": "RETRIEVAL_QUERY"
    }, timeout=30.0)
    r.raise_for_status()
    return r.json()["embedding"]["values"]


_GENERATE_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
]


def generate(prompt: str) -> str:
    import time
    last_err = None
    for model in _GENERATE_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={_key()}"
        for attempt in range(3):
            try:
                r = httpx.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}]
                }, timeout=60.0)
                if r.status_code in (429, 503):
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code in (429, 503):
                    time.sleep(2 ** attempt)
                else:
                    break
            except Exception as e:
                last_err = e
                break
    raise RuntimeError(f"All Gemini generate models failed. Last error: {last_err}")
