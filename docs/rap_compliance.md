# RAP compliance

This repository is organised to meet **Gold RAP** under the
[NHS RAP Community of Practice maturity framework](https://nhsdigital.github.io/rap-community-of-practice/introduction_to_RAP/levels_of_RAP/).
The levels are cumulative — Gold includes everything in Baseline and Silver.
The structure also draws on the
[NHS England repository template](https://github.com/nhs-england-tools/repository-template)
and the [NHS England "package your code" workshop](https://github.com/nhsengland/package-your-code-workshop).

## Baseline RAP

| Criterion | Status | Evidence |
|---|---|---|
| Data produced by code in an open-source language | ✅ | Python pipeline (`src/nhs_policy_navigator/`). |
| Code is version controlled | ✅ | Git, hosted on GitHub. |
| README details steps to reproduce | ✅ | [`README.md`](../README.md), [`docs/user_guide.md`](user_guide.md). |
| Code has been peer reviewed | ✅ | Pull request workflow with template + required human review. |
| Code is published in the open | ✅ | Public GitHub repository, MIT licensed. |

## Silver RAP

| Criterion | Status | Evidence |
|---|---|---|
| Outputs produced with minimal manual intervention | ✅ | `make ingest` / `make run`; console entry points. |
| Code is well-documented (guidance, structure, docstrings) | ✅ | Module + function docstrings; `docs/`. |
| Well-organised, standard directory format | ✅ | `src/` package layout, `tests/`, `docs/`. |
| Reusable functions and/or classes | ✅ | Modular agent, `Settings` dataclass, helper functions. |
| Adheres to agreed coding standards | ✅ | PEP 8, type hints, **black** + **ruff** (see `pyproject.toml`). |
| Pipeline includes a testing framework | ✅ | `pytest` suite in `tests/` (external services mocked). |
| Dependency information included | ✅ | `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`. |
| Logs automatically recorded by the pipeline | ✅ | `logging_config.py`; every query logged to `query_log`. |
| Configuration aids reusability | ✅ | `config.py` reads all settings from the environment. |

## Gold RAP

| Criterion | Status | Evidence |
|---|---|---|
| Code is fully packaged | ✅ | `pyproject.toml` (`setuptools`, `src/` layout, entry points). |
| Tests run automatically via CI/CD | ✅ | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — ruff + black + pytest on 3.10–3.12. |
| Process runs on event-based triggers or a schedule | ✅ | CI runs on push / pull request; the agent itself runs on live query events and fetches live sources at request time. |
| Changes clearly signposted (changelog, releases) | ✅ | [`CHANGELOG.md`](../CHANGELOG.md), `VERSION`, semantic versioning. |

## Additional good practice

- **Pre-commit hooks** (`.pre-commit-config.yaml`) for local quality gates.
- **Editor configuration** (`.editorconfig`) for consistent formatting.
- **Pull request template** and `CONTRIBUTING.md` documenting the review process.
- **Secret hygiene**: no credentials in code; `.env` git-ignored; a
  `detect-private-key` pre-commit hook.
