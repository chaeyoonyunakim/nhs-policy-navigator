"""Vercel serverless entry point.

Adds the ``src`` directory to the import path so the packaged application can
be imported without an editable install, then re-exports the FastAPI ``app``.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from nhs_policy_navigator.app import app  # noqa: E402  (path set up above)

__all__ = ["app"]
