"""HTTP API and dashboard over the processed layer.

``create_app`` builds the FastAPI application; ``ecom serve`` runs it.
"""

from __future__ import annotations

from ecom.api.app import create_app
from ecom.api.loader import PlatformData, load_platform

__all__ = ["PlatformData", "create_app", "load_platform"]
