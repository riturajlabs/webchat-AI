"""Unit tests for the GridFSStorageService implementation."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from backend.core.errors import StorageError, StorageFileNotFoundError
from backend.services.storage.base import StorageService
from backend.services.storage.gridfs import GridFSStorageService
from bson import ObjectId


def test_gridfs_storage_service_implements_protocol() -> None:
    mock_db = MagicMock()
    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket=mock_bucket)
    assert isinstance(service, StorageService)


@pytest.mark.asyncio
async def test_gridfs_upload_success() -> None:
    mock_db = MagicMock()
    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket_name="knowledge_files", bucket=mock_bucket)

    expected_oid = ObjectId()
    mock_bucket.upload_from_stream = AsyncMock(return_value=expected_oid)

    content = b"sample pdf binary content"
    storage_key = await service.upload(
        tenant_id="tenant-123",
        website_id="site-456",
        document_id="doc-789",
        filename="report.pdf",
        content=content,
        mime_type="application/pdf",
    )

    assert storage_key == str(expected_oid)
    mock_bucket.upload_from_stream.assert_called_once()
    call_args, call_kwargs = mock_bucket.upload_from_stream.call_args
    assert call_args[0] == "report.pdf"
    assert call_kwargs["metadata"] == {
        "tenant_id": "tenant-123",
        "website_id": "site-456",
        "document_id": "doc-789",
        "filename": "report.pdf",
        "mime_type": "application/pdf",
        "file_size_bytes": len(content),
    }


@pytest.mark.asyncio
async def test_gridfs_upload_failure_raises_storage_error() -> None:
    mock_db = MagicMock()
    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket=mock_bucket)
    mock_bucket.upload_from_stream = AsyncMock(side_effect=RuntimeError("disk full"))

    with pytest.raises(StorageError) as exc_info:
        await service.upload(
            tenant_id="tenant-123",
            website_id="site-456",
            document_id="doc-789",
            filename="report.pdf",
            content=b"test",
            mime_type="application/pdf",
        )
    assert "Failed to upload file to GridFS" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gridfs_download_success() -> None:
    mock_db = MagicMock()
    mock_files_col = MagicMock()
    mock_db.__getitem__.return_value = mock_files_col

    file_oid = ObjectId()
    mock_files_col.find_one = AsyncMock(
        return_value={"_id": file_oid, "metadata": {"tenant_id": "tenant-1"}}
    )

    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket_name="knowledge_files", bucket=mock_bucket)
    mock_stream = AsyncMock()
    mock_stream.read = AsyncMock(return_value=b"retrieved content")
    mock_bucket.open_download_stream = AsyncMock(return_value=mock_stream)

    data = await service.download(tenant_id="tenant-1", storage_key=str(file_oid))
    assert data == b"retrieved content"
    mock_files_col.find_one.assert_called_once_with(
        {"_id": file_oid, "metadata.tenant_id": "tenant-1"}
    )
    mock_bucket.open_download_stream.assert_called_once_with(file_oid)


@pytest.mark.asyncio
async def test_gridfs_download_tenant_isolation_mismatch() -> None:
    mock_db = MagicMock()
    mock_files_col = MagicMock()
    mock_db.__getitem__.return_value = mock_files_col

    # File exists for another tenant, so find_one with tenant-2 returns None
    mock_files_col.find_one = AsyncMock(return_value=None)

    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket=mock_bucket)
    file_oid = ObjectId()

    with pytest.raises(StorageFileNotFoundError):
        await service.download(tenant_id="tenant-2", storage_key=str(file_oid))


@pytest.mark.asyncio
async def test_gridfs_download_invalid_object_id() -> None:
    mock_db = MagicMock()
    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket=mock_bucket)

    with pytest.raises(StorageFileNotFoundError):
        await service.download(tenant_id="tenant-1", storage_key="invalid-oid-string")


@pytest.mark.asyncio
async def test_gridfs_delete_success() -> None:
    mock_db = MagicMock()
    mock_files_col = MagicMock()
    mock_db.__getitem__.return_value = mock_files_col

    file_oid = ObjectId()
    mock_files_col.find_one = AsyncMock(
        return_value={"_id": file_oid, "metadata": {"tenant_id": "tenant-1"}}
    )

    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket=mock_bucket)
    mock_bucket.delete = AsyncMock()

    deleted = await service.delete(tenant_id="tenant-1", storage_key=str(file_oid))
    assert deleted is True
    mock_bucket.delete.assert_called_once_with(file_oid)


@pytest.mark.asyncio
async def test_gridfs_delete_tenant_isolation_mismatch() -> None:
    mock_db = MagicMock()
    mock_files_col = MagicMock()
    mock_db.__getitem__.return_value = mock_files_col

    # Return None because tenant doesn't match
    mock_files_col.find_one = AsyncMock(return_value=None)

    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket=mock_bucket)
    mock_bucket.delete = AsyncMock()

    deleted = await service.delete(tenant_id="tenant-attacker", storage_key=str(ObjectId()))
    assert deleted is False
    mock_bucket.delete.assert_not_called()


@pytest.mark.asyncio
async def test_gridfs_delete_invalid_object_id() -> None:
    mock_db = MagicMock()
    mock_bucket = MagicMock()
    service = GridFSStorageService(mock_db, bucket=mock_bucket)

    deleted = await service.delete(tenant_id="tenant-1", storage_key="not-an-oid")
    assert deleted is False
