"""Centralised configuration for the NHS Policy Navigator.

All runtime configuration is read from environment variables so that no
credentials are ever hard-coded. A ``.env`` file is loaded automatically when
present (see ``.env.example``). Grouping configuration in one place keeps the
pipeline reusable across environments, in line with Silver RAP guidance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Repository root, derived from this file's location (src/nhs_policy_navigator/).
REPO_ROOT: Path = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings sourced from the environment.

    Attributes:
        mongodb_uri: MongoDB Atlas connection string.
        db_name: Target database name.
        google_api_key: Google AI Studio (Gemini) API key.
        chunks_collection: Collection holding embedded source chunks.
        log_collection: Collection holding the per-query decision log.
        digest_collection: Collection holding deduped, categorised query clusters.
        embedding_model: Gemini embedding model identifier.
        embedding_dimensions: Vector dimensions produced by the model.
        generate_models: Ordered fallback list of Gemini generation models.
        nhs_rss_feed: NHS England RSS feed URL for live sources.
        plan_cutoff: ISO date marking the plan's publication boundary.
        static_dir: Directory containing the front-end assets.
        is_serverless: True when running on Vercel's serverless runtime.
    """

    mongodb_uri: str
    google_api_key: str
    db_name: str = "agentic-evolution-hackathon"
    chunks_collection: str = "nhs_chunks"
    log_collection: str = "query_log"
    digest_collection: str = "query_digest"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    generate_models: tuple[str, ...] = (
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
    )
    nhs_rss_feed: str = "https://www.england.nhs.uk/feed/"
    plan_cutoff: str = "2025-07-03"
    static_dir: Path = field(default_factory=lambda: REPO_ROOT / "static")
    is_serverless: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables.

        Raises:
            RuntimeError: If a required credential is missing.
        """
        missing = [name for name in ("MONGODB_URI", "GOOGLE_API_KEY") if not os.environ.get(name)]
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing) + ". "
                "Copy .env.example to .env and fill in your credentials."
            )
        return cls(
            mongodb_uri=os.environ["MONGODB_URI"],
            google_api_key=os.environ["GOOGLE_API_KEY"],
            db_name=os.environ.get("DB_NAME", "agentic-evolution-hackathon"),
            is_serverless=bool(os.environ.get("VERCEL")),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings, building them on first use."""
    return Settings.from_env()
