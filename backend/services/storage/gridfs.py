"""MongoDB GridFS implementation of the StorageService protocol."""

import io
import logging
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket

from backend.core.errors import StorageError, StorageFileNotFoundError

logger = logging.getLogger("webchat_ai")


class GridFSStorageService:
    """Stores and retrieves file attachments via MongoDB GridFS."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase[Any],
        bucket_name: str = "knowledge_files",
        bucket: AsyncIOMotorGridFSBucket | None = None,
    ) -> None:
        self._db = db
        self._bucket_name = bucket_name
        self._bucket = (
            bucket
            if bucket is not None
            else AsyncIOMotorGridFSBucket(db, bucket_name=bucket_name)
        )

    async def upload(
        self,
        *,
        tenant_id: str,
        website_id: str,
        document_id: str,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> str:
        """Upload raw binary to GridFS bucket with tenant metadata."""
        metadata = {
            "tenant_id": tenant_id,
            "website_id": website_id,
            "document_id": document_id,
            "filename": filename,
            "mime_type": mime_type,
            "file_size_bytes": len(content),
        }
        try:
            stream = io.BytesIO(content)
            file_id = await self._bucket.upload_from_stream(
                filename,
                stream,
                metadata=metadata,
            )
            return str(file_id)
        except Exception as exc:
            logger.exception("gridfs_upload_failed document_id=%s", document_id)
            raise StorageError(f"Failed to upload file to GridFS: {exc}") from exc

    async def download(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> bytes:
        """Download raw binary from GridFS, strictly verifying tenant ownership."""
        try:
            oid = ObjectId(storage_key)
        except (InvalidId, TypeError) as exc:
            raise StorageFileNotFoundError("File not found.") from exc

        files_col = self._db[f"{self._bucket_name}.files"]
        file_doc = await files_col.find_one({"_id": oid, "metadata.tenant_id": tenant_id})
        if file_doc is None:
            raise StorageFileNotFoundError("File not found.")

        try:
            grid_out = await self._bucket.open_download_stream(oid)
            return await grid_out.read()
        except Exception as exc:
            logger.exception("gridfs_download_failed storage_key=%s", storage_key)
            raise StorageError(f"Failed to read file from GridFS: {exc}") from exc

    async def delete(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> bool:
        """Delete file from GridFS bucket if owned by tenant. Idempotent."""
        try:
            oid = ObjectId(storage_key)
        except (InvalidId, TypeError):
            return False

        files_col = self._db[f"{self._bucket_name}.files"]
        file_doc = await files_col.find_one({"_id": oid, "metadata.tenant_id": tenant_id})
        if file_doc is None:
            return False

        try:
            await self._bucket.delete(oid)
            return True
        except Exception:
            logger.warning("gridfs_delete_failed storage_key=%s", storage_key)
            return False
