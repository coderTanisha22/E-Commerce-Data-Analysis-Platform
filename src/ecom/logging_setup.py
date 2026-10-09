"""Single logging configuration for the whole project.

Imported for its side effect by ``cli`` and by any script entrypoint. Library
modules only call ``logging.getLogger(__name__)`` and never configure handlers,
so importing a module never mutates global logging state.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(message)s"
_DATEFMT = "%H:%M:%S"


def configure(level: str = "INFO") -> None:
    """Install one stderr handler with a consistent format.

    Idempotent: calling it twice does not duplicate handlers, which would
    otherwise double every pipeline log line.

    Args:
        level: Any name accepted by ``logging.getLevelName``.
    """
    root = logging.getLogger()
    if any(getattr(h, "_ecom_handler", False) for h in root.handlers):
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    handler._ecom_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
