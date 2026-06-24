"""Logging configuration for the NHS Policy Navigator.

Gold RAP expects pipelines to record structured logs rather than relying on
ad-hoc ``print`` statements. ``configure_logging`` sets up a single console
handler with a consistent format; modules obtain a logger via
``logging.getLogger(__name__)``.
"""

from __future__ import annotations

import logging
import os

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_configured = False


def configure_logging(level: int | str | None = None) -> None:
    """Configure root logging once for the whole application.

    Args:
        level: Logging level. Defaults to the ``LOG_LEVEL`` environment
            variable, or ``INFO`` when unset.
    """
    global _configured
    if _configured:
        return
    resolved = level or os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(level=resolved, format=_DEFAULT_FORMAT)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given module name."""
    configure_logging()
    return logging.getLogger(name)
