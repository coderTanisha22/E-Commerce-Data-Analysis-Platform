"""Storage layer: one interface, two interchangeable backends.

``get_storage()`` is the only function the rest of the pipeline calls, so
switching between the local filesystem and MinIO is a change to
``ECOM_STORAGE_BACKEND`` and nothing else.
"""

from __future__ import annotations

import logging

from ecom.config import Settings, get_settings
from ecom.storage.base import PROCESSED_PREFIX, RAW_PREFIX, StorageBackend
from ecom.storage.local import LocalStorage
from ecom.storage.minio_backend import MinioStorage

logger = logging.getLogger(__name__)

__all__ = [
    "PROCESSED_PREFIX",
    "RAW_PREFIX",
    "LocalStorage",
    "MinioStorage",
    "StorageBackend",
    "get_storage",
]


def get_storage(settings: Settings | None = None) -> StorageBackend:
    """Build the storage backend named by configuration.

    Args:
        settings: Override settings, mainly for tests.

    Returns:
        A ready ``StorageBackend``.

    Raises:
        ValueError: If the configured backend name is not recognised.
    """
    settings = settings or get_settings()
    backend = settings.storage_backend.strip().lower()

    if backend == "local":
        store: StorageBackend = LocalStorage(
            raw_root=settings.resolve(settings.raw_root),
            processed_root=settings.resolve(settings.processed_root),
        )
    elif backend == "minio":
        store = MinioStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    else:
        raise ValueError(
            f"unknown storage backend {settings.storage_backend!r}; use local or minio"
        )

    logger.info("storage backend: %s", store.describe())
    return store
