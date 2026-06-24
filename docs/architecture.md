# Architecture

## Overview

The NHS Policy Navigator is a small, packaged Python application with three
layers:

1. **Front end** — a single-file vanilla HTML/JS page (`static/index.html`)
   styled to the NHS England identity.
2. **API** — a FastAPI application (`nhs_policy_navigator.app`) exposing query,
   stats, history and health endpoints.
3. **Agent + data** — the adaptive retrieval agent
   (`nhs_policy_navigator.agent`) over MongoDB Atlas, using Google Gemini for
   embeddings and generation.

## Package layout

```
src/nhs_policy_navigator/
├── __init__.py          # package version
├── config.py            # environment-driven settings (Settings dataclass)
├── logging_config.py    # structured logging setup
├── gemini.py            # Gemini REST wrappers (embed + generate)
├── agent.py             # adaptive multi-source retrieval pipeline
├── app.py               # FastAPI application
└── pipeline/
    ├── ingest.py        # PDF ingestion + Atlas index creation
    ├── reembed.py       # re-embed stored chunks
    └── export_db.py     # export collections to JSON
```

## Retrieval pipeline

For every query the agent runs:

```
classify -> select_sources -> retrieve -> rerank -> generate -> evaluate -> log -> adapt
```

| Stage | Function | Description |
|---|---|---|
| Classify | `classify_query` | `factual`, `conceptual`, `comparative` or `gap_analysis`. |
| Route sources | `select_sources` | Plan only, plan + news, or plan + news + publications. |
| Select strategy | `select_strategy` | Default per type, or the best-scoring strategy once a type has ≥5 runs. |
| Retrieve | `retrieve_text` / `retrieve_vector` / `retrieve_hybrid` | MongoDB Atlas full-text, vector or hybrid search. |
| Re-rank | `rerank_chunks` | LLM relevance score (0–10) re-orders plan chunks. |
| Generate | `generate_answer` | Grounded, source-aware answer in the plan's house style. |
| Evaluate | `evaluate_relevance` | Self-evaluated quality score (1–5). |
| Log / adapt | `adaptive_retrieve` | Writes the full decision trail to `query_log`. |

## Data stores (MongoDB Atlas M0)

- `nhs_chunks` — embedded plan chunks with `vector_index` (vector search) and
  `text_index` (full-text search).
- `query_log` — one document per query capturing classification, strategy,
  sources, counts and the relevance score. This collection powers both the
  observability views and the agent's learning.

## External services

| Concern | Service | Notes |
|---|---|---|
| Database | MongoDB Atlas M0 | Free tier, vector + full-text search. |
| Embeddings | Gemini `gemini-embedding-001` (768 dims) | Free tier. |
| Generation | Gemini `gemini-2.0-flash` (+ fallbacks) | Free tier, REST API. |
| Live sources | NHS England RSS feed | Fetched at query time. |

All credentials are read from environment variables via `config.Settings`;
nothing is hard-coded.
