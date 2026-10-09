"""MinIO (S3-compatible) storage backend.

Keys map directly onto object names inside one bucket, so ``raw/olist/orders.csv``
is literally that object. The ``minio`` client is imported lazily, which keeps it
an optional dependency: the pipeline runs on the local backend without it
installed. Install with ``pip install -e '.[minio]'``.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

from ecom.storage.base import StorageBackend

if TYPE_CHECKING:  # pragma: no cover - typing only
    from minio import Minio

logger = logging.getLogger(__name__)


class MinioStorage(StorageBackend):
    """Key-addressed store backed by a MinIO bucket."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        *,
        secure: bool = False,
    ) -> None:
        """Connect to MinIO and ensure the bucket exists.

        Args:
            endpoint: Host and port, e.g. ``localhost:9000``.
            access_key: MinIO access key.
            secret_key: MinIO secret key.
            bucket: Bucket holding every layer of the pipeline.
            secure: Whether to use TLS. False for local development.

        Raises:
            ImportError: If the optional ``minio`` dependency is absent, with
                the install command in the message.
        """
        try:
            from minio import Minio
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise ImportError(
                "the minio backend needs the optional dependency: "
                "pip install -e '.[minio]' (or set ECOM_STORAGE_BACKEND=local)"
            ) from exc

        self._bucket = bucket
        self._endpoint = endpoint
        self._client: Minio = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)
            logger.info("created bucket %s", bucket)

    def put_bytes(self, key: str, data: bytes) -> None:
        """Put an object into the bucket."""
        self._client.put_object(self._bucket, key, io.BytesIO(data), length=len(data))
        logger.debug("put s3://%s/%s (%d bytes)", self._bucket, key, len(data))

    def get_bytes(self, key: str) -> bytes:
        """Get an object from the bucket.

        Raises:
            FileNotFoundError: If the key is absent, normalising MinIO's
                ``NoSuchKey`` error so callers handle one exception type.
        """
        from minio.error import S3Error

        response = None
        try:
            response = self._client.get_object(self._bucket, key)
            return response.read()
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                raise FileNotFoundError(f"no object at key {key!r}") from exc
            raise
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def exists(self, key: str) -> bool:
        """Return whether the object exists."""
        from minio.error import S3Error

        try:
            self._client.stat_object(self._bucket, key)
        except S3Error:
            return False
        return True

    def list_keys(self, prefix: str = "") -> list[str]:
        """List object names under ``prefix``."""
        objects = self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
        return sorted(obj.object_name for obj in objects)

    def describe(self) -> str:
        """Return the bucket URI."""
        return f"minio(s3://{self._bucket} @ {self._endpoint})"
