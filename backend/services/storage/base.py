"""Storage service protocol definition for knowledge file attachments."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageService(Protocol):
    """Abstract storage backend for uploaded files (e.g. GridFS, S3)."""

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
        """Upload file content to storage.

        Returns the unique storage_key string.
        """
        ...

    async def download(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> bytes:
        """Download file content from storage by storage_key.

        Must validate tenant isolation (tenant_id matches file metadata).
        Raises StorageFileNotFoundError if not found or tenant mismatch.
        """
        ...

    async def delete(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> bool:
        """Delete file from storage by storage_key.

        Must validate tenant isolation (only deletes if tenant matches).
        Returns True if deleted, False if not found or tenant mismatch.
        Idempotent: never raises if file does not exist.
        """
        ...
