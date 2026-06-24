# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-24

### Added

- **Gold RAP packaging**: the application is now an installable Python package
  under `src/nhs_policy_navigator/` with a `pyproject.toml`, console entry
  points (`nhs-ingest`, `nhs-reembed`, `nhs-export-db`) and a `VERSION` file.
- **Centralised configuration** (`config.py`) reading all settings from
  environment variables, with validation of required credentials.
- **Structured logging** (`logging_config.py`) replacing ad-hoc `print`
  statements throughout the agent and pipeline.
- **Unit test suite** (`tests/`) covering configuration, the Gemini wrappers,
  ingestion helpers and the adaptive retrieval decision logic — all external
  services mocked.
- **Continuous integration** via GitHub Actions (`.github/workflows/ci.yml`)
  running ruff, black and pytest across Python 3.10–3.12.
- **Developer tooling**: `Makefile`, `.pre-commit-config.yaml`,
  `.editorconfig`, `requirements-dev.txt`.
- **Documentation**: `CONTRIBUTING.md`, pull request template, a `docs/`
  directory (architecture, user guide, RAP compliance) and this changelog.

### Changed

- Moved `agent.py`, `app.py`, `gemini.py` and the data pipeline scripts into
  the package; the FastAPI app now runs as `nhs_policy_navigator.app:app`.
- Updated the Vercel serverless entry point (`api/index.py`) and the README to
  reflect the new package layout.
- Timestamps now use timezone-aware UTC (`datetime.now(timezone.utc)`).

### Notes

- No change to runtime behaviour or external interfaces; the API endpoints,
  retrieval logic and front end are functionally unchanged.

## [0.1.0] - 2026-05

### Added

- Initial proof of concept built for the MongoDB Agentic Evolution Hackathon:
  adaptive multi-source retrieval agent over the NHS 10 Year Health Plan with a
  FastAPI backend, MongoDB Atlas vector/text search and a single-file front end.
