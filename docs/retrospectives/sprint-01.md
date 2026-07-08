# Sprint 01 — Retrospective & Process Log

**Project:** NHS Policy Navigator — adaptive multi-source retrieval agent over the
NHS 10 Year Health Plan.
**Sprint window:** June 2026.
**Outcome:** shipped **v1.0.0** (Gold RAP repackaging) and **v1.1.0** (Query Router
feature) to `main`, deployed on Vercel.

This document is the factual record of the sprint — what was done, in what order,
why, and what we learned. It is the input for the reflection blog draft
(`sprint-01-blog-draft.md`) and the planning input for Sprint 02.

---

## 1. Where we started

The repository was a working hackathon proof of concept:

- A flat layout — `agent.py`, `app.py`, `gemini.py`, plus `ingest.py` /
  `reembed.py` / `export_db.py` at the root.
- A FastAPI backend, a single-file vanilla HTML/JS front end, MongoDB Atlas
  (vector + full-text search), and Google Gemini for embeddings and generation.
- No tests, no CI, no packaging, `print()` for logging, secrets read ad hoc.

The goal for the sprint: **make it a credible, maintainable, reproducible product**
and **add the "adaptive" capability the hackathon theme promised** — without
introducing any paid dependency (the project runs entirely on free tiers).

---

## 2. What shipped (chronological)

| # | PR | Change | Outcome |
|---|----|--------|---------|
| 1 | **#10** `dev/refactor-cleancode` | Reorganise to **Gold RAP**: `src/` package, `config.py`, logging, pytest suite, GitHub Actions CI, `pyproject.toml`, Makefile, pre-commit, docs | merged |
| 2 | **#11** `fix/hackathon-date` | Correct the hackathon date (2025 → **2026**) across README, changelog, footer | merged |
| 3 | **#12** `design/query-router-wireframes` | First cut of the Query Router (imported from Claude Design) | **closed**, split into #13/#14 |
| 4 | **#13** `design/query-router` | Query Router **feature**: facet tagging, dedup digest, `/api/digest`, tests | merged |
| 5 | **#14** `design/ui-ux` | Query Router **UI/UX**: sidebar restructure, "This query" legend, trimmed panels | merged |
| 6 | **#15** `release/1.1.0` | Version bump to **1.1.0**, changelog promoted | merged |
| 7 | **#18** `fix/simplify-care-settings-main` | Collapse care-setting taxonomy to **Secondary / Primary / Wider Primary care** | merged |
| 8 | **#19** `fix/retire-metrics-main` | Retire the Selection & Relevance metrics from the UI | merged |

**Version:** 1.0.0 → 1.1.0 (tag `v1.1.0`).
**Tests:** 29 → 46 → 47 → **49**, all mocked (no network/DB).
**CI:** ruff + black + pytest across Python 3.10 / 3.11 / 3.12 on every PR.

---

## 3. Key engineering decisions

**Gold RAP first, features second.** We repackaged before adding capability, so the
Query Router landed on a base with tests, CI and a changelog rather than on a
hackathon scaffold. This paid off immediately — every later PR was gated green.

**Configuration and logging centralised.** All settings moved into a `Settings`
dataclass read from the environment (no hard-coded secrets); `print()` became
structured logging. Small change, large payoff for reproducibility and handover.

**The Query Router as a bandit-flavoured layer.** Rather than a fixed RAG pipeline,
each query is classified, routed to sources, and assigned a retrieval strategy that
can switch from a preset default to the best-performing option once enough history
exists — with the decision trail logged to MongoDB. (See the adaptive-retrieval
analysis captured during the sprint for the honest "adaptive vs static" assessment.)

**Two surfaces, two jobs.** The main-page *digest* (`query_digest`) is the curated,
deduplicated, categorised view (top 10 most-asked per category); the *Previous
Queries* tab (`query_log`) is the complete, append-only log. Keeping these separate
avoided conflating "highlights" with "history".

**Graceful degradation everywhere.** Tagging, dedup routing, news/publication
fetches and re-ranking all fail soft — a failure never blocks an answer.

---

## 4. Process decisions worth remembering

**Splitting an entangled PR into a stack.** #12 bundled the feature and its UI. The
UI commits depended on the feature commit, so they could not merge into `main`
independently. We split into **#13 (feature → main)** and **#14 (UI → #13)**, a
stacked pair, and retargeted #14 to `main` after #13 merged. Lesson: *separate the
capability from its presentation at commit time*, not after.

**Design handoff friction.** The Claude Design project could not be pulled directly
in the web session (the design connector could not authorise, and "Send to Claude
Code Web" seeds a *new* session, not the running one). The unblock was a plain git
patch. Lesson: for Sprint 02, agree the design → code handoff mechanism up front.

**Screenshot-driven UI iteration.** Several UI changes (drop the example pills, drop
the stats panels, replace the counter with a "This query" legend, top-10 per
category) came from annotated screenshots. Fast and effective, but it meant the UI
churned across several PRs — worth front-loading a UI spec next time.

**Release hygiene, with one gap.** We cut 1.1.0 cleanly (version bumped in all four
places, changelog dated, tag created). The **git tag push was blocked (403)** by the
sandbox and the GitHub tooling had no create-release method, so the tag/release must
be published manually. Lesson: confirm tag/release permissions before relying on
automation.

---

## 5. What went well

- Clean, test-gated increments — every merge was green on three Python versions.
- No paid dependencies added; the zero-cost handover property held.
- Documentation kept current *with* the code (README, architecture, changelog,
  RAP-compliance mapping) rather than after the fact.
- The adaptive analysis produced an honest map of what is genuinely adaptive vs.
  static — a strong starting point for Sprint 02.

## 6. What was harder than expected

- **Interdependent commits** made the "two clean PRs" request non-trivial; the stack
  needed a rebase and a careful tree-equality check.
- **Tooling gaps** (design auth, tag push) interrupted otherwise-automatable flows.
- **UI scope crept** through iterative screenshots — good outcomes, but more churn
  than a spec-first approach would have produced.
- The **feedback signal is the model grading itself** — fine for a demo, not a basis
  for real adaptation.

---

## 7. Carry-over into Sprint 02

Ranked, from the adaptive-retrieval analysis and the sprint experience:

1. **Real feedback signal** — add a user thumbs-up/down that writes a genuine reward
   field, instead of relying solely on LLM self-evaluation.
2. **Exploration in strategy selection** — replace the greedy "pick the best average"
   with an ε-greedy / bandit approach so strategies keep being sampled.
3. **Recency-weighted scoring** — decay old scores so the system tracks drift instead
   of averaging over all time.
4. **Proper hybrid fusion** — reciprocal-rank fusion instead of concatenate-and-dedupe.
5. **An offline evaluation harness** — a labelled query set + a CI metric, so
   retrieval changes are validated rather than self-reported.
6. **UI spec first** — lock the layout before implementation to reduce churn.
7. **Publish the `v1.1.0` tag/release** — close the release-signposting gap.

---

## 8. Reference

- Architecture: [`docs/architecture.md`](../architecture.md)
- RAP compliance: [`docs/rap_compliance.md`](../rap_compliance.md)
- Changelog: [`CHANGELOG.md`](../../CHANGELOG.md)
- Live demo: <https://nhs-policy-navigator.vercel.app>
