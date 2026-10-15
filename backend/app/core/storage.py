import asyncio
import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from urllib.parse import quote, urlparse

from minio import Minio
from minio.commonconfig import CopySource
from minio.error import S3Error

from app.core.config import Settings

HASH_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str | None


class ObjectStorage(Protocol):
    async def ensure_bucket(self) -> None: ...
    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get_bytes(self, key: str) -> bytes: ...
    async def stat(self, key: str) -> ObjectInfo | None: ...
    async def sha256(self, key: str) -> str: ...
    async def copy(self, src_key: str, dst_key: str) -> None: ...
    async def delete(self, key: str) -> None: ...
    def presign_put(self, key: str, expires_seconds: int) -> str: ...
    def presign_get(
        self,
        key: str,
        expires_seconds: int,
        *,
        filename: str,
        content_type: str,
        attachment: bool = False,
    ) -> str: ...


def _content_disposition(filename: str, attachment: bool = False) -> str:
    return f"{'attachment' if attachment else 'inline'}; filename*=UTF-8''{quote(filename)}"


def _client(endpoint: str, settings: Settings) -> Minio:
    url = urlparse(endpoint)
    return Minio(
        url.netloc,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=url.scheme == "https",
        # A fixed region avoids a network round-trip when signing URLs.
        region=settings.minio_region,
    )


class MinioStorage:
    """MinIO adapter. The SDK is synchronous, so calls run in worker threads."""

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.minio_bucket
        self._client = _client(settings.minio_endpoint, settings)
        self._public = _client(settings.minio_public_endpoint, settings)
        self._bucket_ready = False

    async def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return

        def _ensure() -> None:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)

        await asyncio.to_thread(_ensure)
        self._bucket_ready = True

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            self.bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        def _get() -> bytes:
            resp = self._client.get_object(self.bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await asyncio.to_thread(_get)

    async def stat(self, key: str) -> ObjectInfo | None:
        def _stat() -> ObjectInfo | None:
            try:
                obj = self._client.stat_object(self.bucket, key)
            except S3Error as exc:
                if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                    return None
                raise
            return ObjectInfo(size=int(obj.size or 0), content_type=obj.content_type)

        return await asyncio.to_thread(_stat)

    async def sha256(self, key: str) -> str:
        def _hash() -> str:
            digest = hashlib.sha256()
            resp = self._client.get_object(self.bucket, key)
            try:
                for part in resp.stream(HASH_CHUNK_SIZE):
                    digest.update(part)
            finally:
                resp.close()
                resp.release_conn()
            return digest.hexdigest()

        return await asyncio.to_thread(_hash)

    async def copy(self, src_key: str, dst_key: str) -> None:
        await asyncio.to_thread(
            self._client.copy_object, self.bucket, dst_key, CopySource(self.bucket, src_key)
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self.bucket, key)

    def presign_put(self, key: str, expires_seconds: int) -> str:
        return self._public.presigned_put_object(
            self.bucket, key, expires=timedelta(seconds=expires_seconds)
        )

    def presign_get(
        self,
        key: str,
        expires_seconds: int,
        *,
        filename: str,
        content_type: str,
        attachment: bool = False,
    ) -> str:
        return self._public.presigned_get_object(
            self.bucket,
            key,
            expires=timedelta(seconds=expires_seconds),
            response_headers={
                "response-content-type": content_type,
                "response-content-disposition": _content_disposition(filename, attachment),
            },
        )


class MemoryStorage:
    """In-process storage for tests."""

    def __init__(self, base_url: str = "http://storage.test") -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.base_url = base_url

    async def ensure_bucket(self) -> None:
        return None

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key][0]

    async def stat(self, key: str) -> ObjectInfo | None:
        if key not in self.objects:
            return None
        data, content_type = self.objects[key]
        return ObjectInfo(size=len(data), content_type=content_type)

    async def sha256(self, key: str) -> str:
        return hashlib.sha256(await self.get_bytes(key)).hexdigest()

    async def copy(self, src_key: str, dst_key: str) -> None:
        self.objects[dst_key] = self.objects[src_key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def presign_put(self, key: str, expires_seconds: int) -> str:
        return f"{self.base_url}/{key}?op=put&expires={expires_seconds}"

    def presign_get(
        self,
        key: str,
        expires_seconds: int,
        *,
        filename: str,
        content_type: str,
        attachment: bool = False,
    ) -> str:
        op = "download" if attachment else "get"
        return f"{self.base_url}/{key}?op={op}&expires={expires_seconds}"
