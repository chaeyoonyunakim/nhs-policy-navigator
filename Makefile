# NHS Policy Navigator -- common developer tasks.
# Usage: `make <target>`. Run `make help` to list targets.

.DEFAULT_GOAL := help
PYTHON ?= python

.PHONY: help install install-dev lint format test coverage run ingest clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies
	$(PYTHON) -m pip install -r requirements.txt

install-dev: ## Install development dependencies and pre-commit hooks
	$(PYTHON) -m pip install -r requirements-dev.txt
	pre-commit install

lint: ## Run ruff and black in check mode
	ruff check src tests
	black --check src tests

format: ## Auto-format with ruff and black
	ruff check --fix src tests
	black src tests

test: ## Run the unit test suite
	$(PYTHON) -m pytest

coverage: ## Run tests with a coverage report
	$(PYTHON) -m pytest --cov=nhs_policy_navigator --cov-report=term-missing

run: ## Run the FastAPI app locally with autoreload
	$(PYTHON) -m uvicorn nhs_policy_navigator.app:app --reload --app-dir src

ingest: ## Ingest the NHS PDFs into MongoDB Atlas
	$(PYTHON) -m nhs_policy_navigator.pipeline.ingest

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
