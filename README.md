# NHS Policy Navigator — Adaptive Retrieval Agent

> Built for the **MongoDB Agentic Evolution Hackathon** (London, May 2025)  
> Theme: **Adaptive Retrieval** — an agentic system that actively modifies its query approach based on input and learns from past performance.

---

## What it does

NHS Policy Navigator is an adaptive retrieval agent over the **NHS 10 Year Health Plan "Fit for the Future" (July 2025)**. It doesn't just do RAG — it reasons about *how* to retrieve before it retrieves.

For every query, the agent:

1. **Classifies** the question into one of four types: `factual`, `conceptual`, `comparative`, or `gap_analysis`
2. **Selects a retrieval strategy** based on type — keyword search, vector search, or hybrid — using MongoDB Atlas
3. **Checks historical performance** — after 5+ queries of the same type, the agent switches to whichever strategy has scored highest, adapting autonomously
4. **Generates a grounded answer** citing page numbers from the source document
5. **Self-evaluates** the result quality (1–5 score) and **logs everything back to MongoDB**, enabling future adaptation
6. **Narrates the answer** via ElevenLabs voice synthesis

The right sidebar shows live strategy performance and query history pulled directly from MongoDB — making the adaptation visible in real time.

---

## Tech stack

| Layer | Technology |
|---|---|
| Database | MongoDB Atlas M10 — Vector Search + Full-Text Search |
| Embeddings | OpenAI `text-embedding-3-small` |
| LLM | OpenAI `gpt-4o-mini` |
| Backend | Python / FastAPI |
| Voice | ElevenLabs `eleven_multilingual_v2` |
| Observability | LangSmith (tracing every classify → retrieve → evaluate → generate step) |
| Frontend | Vanilla HTML/JS (single file) |

---

## Source documents

The agent is built on the **NHS 10 Year Health Plan for England — Fit for the Future (July 2025)**.

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

### 1. Clone and install

```bash
git clone https://github.com/chaeyoonyunakim/nhs-policy-navigator.git
cd nhs-policy-navigator
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```env
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=sk_...
DB_NAME=nhs_hackathon
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=nhs-policy-navigator
LANGCHAIN_API_KEY=lsv2_...
```

### 3. Download PDFs

Download both PDFs from [https://www.england.nhs.uk/long-term-plan/](https://www.england.nhs.uk/long-term-plan/) and place them in the project root (see filenames above).

### 4. Ingest documents into MongoDB

```bash
python ingest.py
```

This chunks both PDFs, generates embeddings, loads 586 chunks into MongoDB Atlas, and creates the vector + text search indexes. Takes ~5–10 minutes.

Wait for both indexes to show **READY** in Atlas UI → Cluster → Search Indexes before proceeding.

### 5. Run the app

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
    "numDimensions": 1536,
    "similarity": "cosine"
  }]
}
```

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

---

## Project structure

```
├── agent.py          # Core adaptive retrieval logic
├── app.py            # FastAPI backend (query, stats, narrate endpoints)
├── ingest.py         # PDF ingestion + MongoDB index creation
├── requirements.txt
├── .env.example
├── static/
│   ├── index.html    # Frontend (single file)
│   └── img/          # NHS England logo assets
└── README.md
```

---

## Observability

All LLM calls are traced via LangSmith. Each query produces a trace showing:
- Query classification
- Strategy selection (default vs. learned from data)
- Retrieval results
- Self-evaluation score
- Generated answer

View traces at [smith.langchain.com](https://smith.langchain.com) → `nhs-policy-navigator` project.

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
