# Turning a hackathon RAG demo into a reproducible product (Sprint 01 reflection)

> Draft reflection blog. Voice is first-person; edit freely before publishing.
> Facts are drawn from `sprint-01.md`.

## The starting point

I came out of the MongoDB Agentic Evolution Hackathon (London, May 2026) with a
working proof of concept: **NHS Policy Navigator**, an adaptive retrieval agent over
the NHS 10 Year Health Plan. It did the job in a demo — but it was hackathon code.
One flat folder, no tests, no CI, `print()` statements for logging, and an
"adaptive" story that was more aspiration than implementation.

Sprint 01 had two goals: make it a product I'd be comfortable handing to someone
else, and actually build the adaptive layer the theme promised — all while keeping
the project at **zero running cost** (free-tier MongoDB Atlas and Gemini only).

## Lesson 1: structure before features

The first thing I did was resist the urge to build the shiny feature. Instead I
repackaged the project to **Gold RAP** — the NHS Reproducible Analytical Pipeline
standard: a proper `src/` package, environment-driven configuration with no
hard-coded secrets, structured logging, a pytest suite, GitHub Actions CI, a
changelog, and documentation that lives next to the code.

It felt slow. It wasn't. Every feature I built afterwards landed on a base that
tested itself across three Python versions and refused to merge if anything broke.
The test count went from 0 to 29 in that first PR and climbed to 49 by the end of
the sprint — and not once did I ship a regression I had to chase in production.
**The boring work bought me speed later.**

## Lesson 2: name what's actually adaptive

The headline feature was the **Query Router**. Every question is classified,
routed to the right sources, and given a retrieval strategy — keyword, vector, or
hybrid — that can *switch* from a sensible default to whichever strategy has scored
best historically for that kind of question. Near-identical questions are
deduplicated into a categorised digest so the front page shows the top-10 most-asked
topics per NHS care setting, while a separate tab keeps the full history.

Partway through I asked a blunt question of my own codebase: *what here is genuinely
adaptive, and what just looks it?* The honest answer was humbling. The strategy
selection is real — it reads logged outcomes and changes behaviour — but it's
**greedy** (once a strategy wins, the others stop being tried), it learns from the
**model grading itself** rather than from users, and it averages over all time with
no sense of recency. It's a bandit with the exploration switched off.

Writing that down, without flattering the work, turned out to be the most valuable
artefact of the sprint. It's the backlog for Sprint 02.

## Lesson 3: separate capability from presentation

I tried to ship the Query Router as one pull request. It bundled the backend feature
and the UI on top of it, and when I wanted to split them into two reviewable PRs I
hit the obvious-in-hindsight wall: the UI commits *depended* on the feature, so they
couldn't merge independently.

The fix was a **stacked pair** — the feature PR into `main`, the UI PR based on the
feature branch and retargeted once it merged. It worked, but the cleaner move would
have been to keep the capability and its presentation on separate commits from the
start. **Decide your review boundaries before you write the code, not after.**

## Lesson 4: the tooling will surprise you

Two things I assumed were automatic weren't. Importing the UI design from Claude
Design didn't work in the running web session, so the handoff became a plain git
patch. And cutting the release, publishing the `v1.1.0` git tag was blocked by the
environment. Neither was a disaster — but both cost time I hadn't budgeted.
**Confirm the mechanics of your handoffs and your release process early**, while
they're cheap to fix.

## What I'm proud of

- A hackathon demo is now a documented, tested, CI-gated, versioned product —
  shipped as **v1.1.0** — that still costs nothing to run.
- The documentation tells the truth about what the system does, including where the
  "adaptive" label is aspirational.
- Small, green, reversible increments the whole way.

## What Sprint 02 is for

Make the adaptation real: a genuine user feedback signal instead of the model marking
its own homework; exploration so the router keeps learning; recency-weighted scores;
proper hybrid fusion; and an offline evaluation harness so I can prove a change is an
improvement rather than assert it.

The demo answered questions. The product should get better at answering them.

---

*NHS Policy Navigator is built on free-tier MongoDB Atlas and Google Gemini. Live
demo: https://nhs-policy-navigator.vercel.app*
