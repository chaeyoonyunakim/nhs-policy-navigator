# Contributing

Thank you for considering a contribution to the NHS Policy Navigator. This
project follows the [NHS RAP Community of Practice](https://nhsdigital.github.io/rap-community-of-practice/)
guidance and the [Government Digital Service (GDS) coding standards](https://gds-way.digital.cabinet-office.gov.uk/standards/programming-languages.html).

## Getting started

```bash
git clone https://github.com/chaeyoonyunakim/nhs-policy-navigator.git
cd nhs-policy-navigator
python -m venv .venv && source .venv/bin/activate
make install-dev          # installs dev deps and pre-commit hooks
```

## Development workflow

1. Create a feature branch from `main`.
2. Make your change, keeping functions small and well-documented.
3. Run the checks locally:
   ```bash
   make format   # auto-fix style
   make lint     # ruff + black
   make test     # pytest
   ```
4. Commit. Pre-commit hooks run ruff, black and basic hygiene checks.
5. Open a **pull request**. CI (GitHub Actions) runs lint and tests on every PR.

## Coding standards

- **Python**: PEP 8, 4-space indentation, type hints, formatted with **black**
  and linted with **ruff**.
- Write **tests for all new functions** (`tests/`, run with pytest).
- Keep functions under 20 lines where practical.
- Use **British English** in comments and documentation.
- Never commit secrets, credentials or API keys — use environment variables
  (see `.env.example`).

## Review

All changes must be **reviewed by a human** before merge. The pull request
template includes a checklist to confirm standards are met.
