"""
LLM text-generation provider.

Routes every generation call (classification, chunk re-ranking, answer
generation, self-evaluation) to a backend chosen at runtime:

  LLM_PROVIDER=ollama   (default)  -- a local model served by Ollama. Nothing
                                       leaves the machine, so it is safe for
                                       confidential / non-public material.
  LLM_PROVIDER=gemini              -- the hosted Google Gemini API (gemini.py).

Local (Ollama) configuration:
  OLLAMA_MODEL=qwen2.5             -- any model you have `ollama pull`-ed;
                                       run `ollama list` to see what you have.
  OLLAMA_HOST=http://localhost:11434

NOTE: embeddings still use Gemini (see gemini.py) so the existing 768-dim
Atlas vector index stays valid. Only text generation is swapped here.
"""
import os
import re

import httpx

# Reasoning models (e.g. qwen3) wrap their chain-of-thought in <think>...</think>;
# strip it so it never reaches the answer card or the response parsers.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "ollama").strip().lower()


def _strip_reasoning(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def _ollama_generate(prompt: str) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5")
    try:
        r = httpx.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=300.0,
        )
        r.raise_for_status()
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"Could not reach Ollama at {host}. Is it running? Start it with `ollama serve`."
        ) from e
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            raise RuntimeError(
                f"Ollama model '{model}' not found. Pull it with `ollama pull {model}`, "
                f"or set OLLAMA_MODEL to one shown by `ollama list`."
            ) from e
        raise
    return _strip_reasoning(r.json().get("response", ""))


def generate(prompt: str) -> str:
    if _provider() == "gemini":
        from gemini import generate as gemini_generate
        return gemini_generate(prompt)
    return _ollama_generate(prompt)
