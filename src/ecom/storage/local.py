"""Local filesystem storage backend.

Maps logical keys onto two configured directory roots. This is the default
backend so the pipeline runs with no services started.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ecom.storage.base import PROCESSED_PREFIX, RAW_PREFIX, StorageBackend

logger = logging.getLogger(__name__)


class LocalStorage(StorageBackend):
    """Key-addressed store backed by directories on disk."""

    def __init__(self, raw_root: Path, processed_root: Path) -> None:
        """Create the backend, making both roots if they do not exist.

        Args:
            raw_root: Directory backing the ``raw/`` key prefix.
            processed_root: Directory backing the ``processed/`` key prefix.
        """
        self._roots = {RAW_PREFIX: Path(raw_root), PROCESSED_PREFIX: Path(processed_root)}
        for root in self._roots.values():
            root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        prefix, _, remainder = key.partition("/")
        if prefix not in self._roots:
            raise ValueError(
                f"key {key!r} must start with one of {sorted(self._roots)}, got {prefix!r}"
            )
        if not remainder:
            raise ValueError(f"key {key!r} names a prefix, not an object")
        # Guard against a key escaping its configured root via traversal.
        root = self._roots[prefix].resolve()
        target = (root / remainder).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"key {key!r} resolves outside its root")
        return target

    def put_bytes(self, key: str, data: bytes) -> None:
        """Write bytes to the mapped path, creating parent directories."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.debug("wrote %s (%d bytes)", key, len(data))

    def get_bytes(self, key: str) -> bytes:
        """Read bytes from the mapped path."""
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(f"no object at key {key!r} (looked in {path})")
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        """Return whether the mapped path exists."""
        try:
            return self._path(key).exists()
        except ValueError:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        """Walk both roots and return matching keys."""
        keys: list[str] = []
        for name, root in self._roots.items():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    keys.append(f"{name}/{path.relative_to(root).as_posix()}")
        return sorted(k for k in keys if k.startswith(prefix))

    def describe(self) -> str:
        """Return the two backing directories."""
        return f"local(raw={self._roots[RAW_PREFIX]}, processed={self._roots[PROCESSED_PREFIX]})"
