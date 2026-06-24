# User guide

## Prerequisites

- Python 3.10+
- A free [Google AI Studio API key](https://aistudio.google.com/apikey)
- A free [MongoDB Atlas M0](https://www.mongodb.com/atlas) cluster

## Installation

```bash
git clone https://github.com/chaeyoonyunakim/nhs-policy-navigator.git
cd nhs-policy-navigator
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install-dev        # or: pip install -r requirements-dev.txt
```

## Configuration

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `MONGODB_URI` | yes | — | MongoDB Atlas connection string. |
| `GOOGLE_API_KEY` | yes | — | Google AI Studio (Gemini) key. |
| `DB_NAME` | no | `agentic-evolution-hackathon` | Target database. |
| `LOG_LEVEL` | no | `INFO` | Logging verbosity. |

Required variables are validated at startup; a clear error is raised if either
is missing.

## Populating the database

Restore the bundled dump (fastest):

```bash
mongoimport --uri "$MONGODB_URI" --db agentic-evolution-hackathon \
  --collection nhs_chunks --file dump/nhs_chunks.json --jsonArray
```

…or ingest from the source PDFs (place both PDFs in the repository root first):

```bash
make ingest            # or: python -m nhs_policy_navigator.pipeline.ingest
```

Wait for both Atlas search indexes to show **READY** before querying.

## Running the app

```bash
make run               # uvicorn nhs_policy_navigator.app:app --reload --app-dir src
```

Open <http://localhost:8000>.

## Pipeline utilities

| Command | Purpose |
|---|---|
| `python -m nhs_policy_navigator.pipeline.ingest` | Ingest PDFs and create indexes. |
| `python -m nhs_policy_navigator.pipeline.reembed` | Re-embed stored chunks. |
| `python -m nhs_policy_navigator.pipeline.export_db` | Export collections to `dump/`. |

After installing the package these are also available as the console scripts
`nhs-ingest`, `nhs-reembed` and `nhs-export-db`.

## Development checks

```bash
make format   # ruff --fix + black
make lint     # ruff + black --check
make test     # pytest
make coverage # pytest with coverage report
```
