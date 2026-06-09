[![status: experimental](https://github.com/GIScience/badges/raw/master/status/experimental.svg)](https://github.com/GIScience/badges#experimental)


# NHS Policy Navigator — Adaptive Multi-Source Retrieval Agent

> PoC built for the **MongoDB Agentic Evolution Hackathon** (London, May 2025)  
> Theme: **Adaptive Retrieval** — an agentic system that actively modifies its query approach based on input and learns from past performance.

---

## What it does

NHS Policy Navigator is an adaptive retrieval agent over the **NHS 10 Year Health Plan "Fit for the Future" (July 2025)** plus live NHS England updates. It doesn't just do RAG — it reasons about *how* to retrieve and *which sources* to use before it retrieves.

![Refined draft wireframe](https://github.com/chaeyoonyunakim/nhs-policy-navigator/blob/main/img/refine-draft-2.png)

For every query, the agent:

1. **Classifies** the question into one of four types: `factual`, `conceptual`, `comparative`, or `gap_analysis`
2. **Routes to sources by type**:
   - `factual` -> NHS plan
   - `conceptual` / `comparative` -> NHS plan + live NHS news
   - `gap_analysis` -> NHS plan + live NHS news + post-July-2025 NHS publications
3. **Selects a retrieval strategy** based on type — keyword search, vector search, or hybrid — using MongoDB Atlas
4. **Re-ranks retrieved chunks** by query relevance before generation
5. **Checks historical performance** — after 5+ queries of the same type, the agent switches to whichever strategy has scored highest, adapting autonomously
6. **Generates a grounded answer** with source-aware citations (plan pages + live sources where relevant)
7. **Self-evaluates** result quality (1–5 score) and **logs everything back to MongoDB**, enabling future adaptation

The UI also surfaces live news/publication cards and shows strategy performance + query history from MongoDB, making adaptation visible in real time. A dedicated **Previous Queries** tab browses the full query history (paginated, 10 per page), and any past question — in the sidebar or that tab — can be copied for reuse.

---

## Tech stack

| Layer | Technology |
|---|---|
| Database | MongoDB Atlas M0 — Vector Search + Full-Text Search |
| Embeddings | Google `gemini-embedding-001` (768 dims) |
| LLM | Google `gemini-2.0-flash` (with fallback to `gemini-2.0-flash-lite`, `gemini-2.5-flash`) |
| Backend | Python / FastAPI |
| Frontend | Vanilla HTML/JS (single file) |

> **Runs at zero external cost.** The entire stack uses only free-tier services: MongoDB Atlas **M0** (free forever) and the Google Gemini **free tier** for both embeddings and generation. There are no paid dependencies — no observability platform and no text-to-speech provider — so the project can be handed over and run without procuring any additional tooling.

---

## Sources used

Primary corpus:
- **NHS 10 Year Health Plan for England — Fit for the Future (July 2025)**
- **Executive summary** of the same plan

Live/secondary sources (fetched at query time):
- **NHS England RSS feed** (`https://www.england.nhs.uk/feed/`) for recent news
- **NHS publications post 3 July 2025** (live RSS filter + curated seed publications)

Download both PDFs and place them in the project root before running ingestion:

- **Full plan** — available at [https://www.england.nhs.uk/long-term-plan/](https://www.england.nhs.uk/long-term-plan/)
- **Executive summary** — available at the same link above

The PDFs are not committed to this repository due to file size. The ingestion script (`ingest.py`) expects them named exactly:

```
fit-for-the-future-10-year-health-plan-for-england.pdf
fit-for-the-future-10-year-health-plan-for-england-executive-summary.pdf
```

---

## Setup

You need Python 3.10+ and a free [Google AI Studio API key](https://aistudio.google.com/apikey).

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/chaeyoonyunakim/nhs-policy-navigator.git
cd nhs-policy-navigator

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:

```env
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
GOOGLE_API_KEY=AIza...
DB_NAME=agentic-evolution-hackathon
```

`GOOGLE_API_KEY` is free — no billing required. Obtain one at [aistudio.google.com](https://aistudio.google.com/apikey). Together with your MongoDB Atlas connection string, it is the only credential the app needs — there are no paid third-party services to configure.

### 4. Download PDFs

Download both PDFs from [https://www.england.nhs.uk/long-term-plan/](https://www.england.nhs.uk/long-term-plan/) and place them in the project root (see filenames above).

### 5. Restore the MongoDB data from the dump (recommended)

The repository includes a pre-built dump of all 586 embedded chunks (using `gemini-embedding-001`, 768 dims). This is the fastest way to get started — no PDF ingestion or embedding calls needed:

```bash
mongoimport --uri "$MONGODB_URI" --db agentic-evolution-hackathon \
  --collection nhs_chunks --file dump/nhs_chunks.json --jsonArray
```

Then create both Atlas Search indexes manually in the Atlas UI (see [MongoDB Atlas index configuration](#mongodb-atlas-index-configuration) below).

**Alternatively — ingest from scratch:**

```bash
python ingest.py
```

This chunks both PDFs, generates `gemini-embedding-001` embeddings (768 dims), loads all chunks into MongoDB Atlas, and creates both search indexes automatically. Takes ~5–10 minutes.

Wait for both indexes to show **READY** in Atlas UI → Cluster → Search Indexes before running the app.

Note: live news and publication sources are fetched at query time and do not require ingestion.

### 6. Run the app

```bash
python -m uvicorn app:app --reload
```

Open [http://localhost:8000](http://localhost:8000)

---

## MongoDB Atlas index configuration

Two indexes are created automatically by `ingest.py`:

**Vector index** (`vector_index`, type: `vectorSearch`):
```json
{
  "fields": [{
    "type": "vector",
    "path": "embedding",
    "numDimensions": 768,
    "similarity": "cosine"
  }]
}
```

> ⚠️ `numDimensions` must be **768** to match `gemini-embedding-001`. Using 1536 (OpenAI) will cause vector search to return no results.

**Text search index** (`text_index`, type: `search`):
```json
{
  "mappings": {
    "dynamic": false,
    "fields": { "text": [{ "type": "string" }] }
  }
}
```

---

## Example queries

| Query | Classified as | Strategy |
|---|---|---|
| What are the NHS targets for GP access by 2028? | `factual` | Text search |
| What does the plan say about AI in the NHS? | `conceptual` | Vector search |
| How does hospital care compare to community care? | `comparative` | Hybrid search |
| Does the plan address mental health in prisons? | `gap_analysis` | Vector search |

For `conceptual`, `comparative`, and `gap_analysis`, results may include:
- Ranked **live NHS news** context from RSS
- Ranked **post-July-2025 NHS publications** context (for `gap_analysis`)

---

## Project structure

```
├── agent.py          # Core multi-source adaptive retrieval logic
├── app.py            # FastAPI backend (query, stats, queries, health endpoints)
├── gemini.py         # Gemini REST API wrapper (embed + generate, no SDK)
├── ingest.py         # PDF ingestion + MongoDB index creation
├── reembed.py        # One-shot utility: re-embed existing docs (e.g. after model change)
├── export_db.py      # Export MongoDB collections to JSON (backup utility)
├── requirements.txt
├── .env.example
├── dump/
│   ├── nhs_chunks.json   # 586 pre-embedded chunks (gemini-embedding-001, 768 dims)
│   └── query_log.json    # Query history snapshot
├── img/              # Wireframes and design references
├── static/
│   ├── index.html    # Frontend (single file)
│   └── img/          # NHS England logo assets
└── README.md
```

---

## Answer generation style

Answers are generated to mirror the writing style of the NHS 10 Year Health Plan executive summary — authoritative, declarative, and dense with specific commitments, dates and figures. The system prompt explicitly references the plan's signature framing ("three shifts", "Neighbourhood Health Service", "decisive shift") and instructs the model to lead every response with a strong claim rather than a definition.

---

## Adaptive retrieval behavior

- **Classification**: `factual`, `conceptual`, `comparative`, `gap_analysis`
- **Strategy options**: `text_search`, `vector_search`, `hybrid_search`
- **Learning rule**: if a query type has >=5 historical runs, use the best average-scoring strategy for that type
- **Re-ordering**: plan chunks are re-ranked by an LLM relevance score (0-10)
- **Source routing**: sources are chosen before retrieval based on query type

## Observability

Observability is built in and requires no external platform. Every query is logged to the MongoDB `query_log` collection with its full decision trail:
- Query classification and source routing decision (plan/news/publications)
- Strategy selection (default vs. learned from data) and relevance/self-evaluation score
- Sources queried and counts of live news / publications fetched

The UI makes this visible in real time — strategy performance, query-type distribution, and the browsable **Previous Queries** history all read directly from MongoDB, so you can watch the agent adapt without any third-party tracing service.

---

## Design reference

Frontend styling follows the NHS England identity and data visualisation guidelines:

- **NHS Identity Guidelines (colours, logo, typography):** [england.nhs.uk/nhsidentity](https://www.england.nhs.uk/nhsidentity/identity-guidelines/colours/)
- **NHS England Data Viz Community of Practice:** [github.com/nhsengland/data-viz-community-of-practice](https://github.com/nhsengland/data-viz-community-of-practice)
- **NHS digital service manual:** [service-manual.nhs.uk](https://service-manual.nhs.uk/design-system/styles/colour)

NHS colour palette used:

| Name | Hex |
|---|---|
| NHS Dark Blue | `#003087` |
| NHS Blue | `#005EB8` |
| NHS Mid Blue | `#0072CE` |
| NHS Light Blue | `#41B6E6` |
| NHS Aqua Blue | `#00A9CE` |
| NHS Green | `#007f3b` |

---

## Licence

MIT — see [LICENSE](./LICENSE).
