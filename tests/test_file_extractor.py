"""Unit tests for the file extractor engine (Phase 3)."""

import io

import docx
import pypdf
import pytest
from backend.core.errors import (
    AppError,
    DocumentCorruptedError,
    DocumentNoTextError,
    DocumentPasswordProtectedError,
    DocumentTooLargeError,
)
from backend.services.ingestion.file_extractor import (
    MAX_FILE_SIZE_BYTES,
    MAX_PDF_PAGES,
    extract_text_from_file,
)

SAMPLE_PDF_BYTES = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R
  /Resources << /Font << /F1 4 0 R >> >>
  /MediaBox [0 0 612 792] /Contents 5 0 R >> endobj
4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
5 0 obj << /Length 73 >> stream
BT
/F1 24 Tf
100 700 Td
(This is a test document with sufficient text content exceeding 50 chars.) Tj
ET
endstream endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000325 00000 n 
trailer << /Root 1 0 R /Size 6 >>
startxref
449
%%EOF"""


def _create_docx(text: str, table_data: list[list[str]] | None = None) -> bytes:
    doc = docx.Document()
    doc.add_paragraph(text)
    if table_data:
        table = doc.add_table(rows=len(table_data), cols=len(table_data[0]))
        for r_idx, row in enumerate(table_data):
            for c_idx, val in enumerate(row):
                table.cell(r_idx, c_idx).text = val
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


def _create_encrypted_pdf() -> bytes:
    reader = pypdf.PdfReader(io.BytesIO(SAMPLE_PDF_BYTES))
    writer = pypdf.PdfWriter()
    writer.append(reader)
    writer.encrypt("test_password")
    bio = io.BytesIO()
    writer.write(bio)
    return bio.getvalue()


def _create_multi_page_pdf(page_count: int) -> bytes:
    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    bio = io.BytesIO()
    writer.write(bio)
    return bio.getvalue()


def test_extract_txt_success() -> None:
    text = "This is a plain text knowledge document containing more than 50 characters."
    doc = extract_text_from_file("guide.txt", text.encode("utf-8"))
    assert doc.filename == "guide.txt"
    assert doc.text == text
    assert doc.char_count == len(text)
    assert doc.mime_type == "text/plain"


def test_extract_txt_insufficient_text_raises() -> None:
    text = "Short text."
    with pytest.raises(DocumentNoTextError) as exc_info:
        extract_text_from_file("short.txt", text.encode("utf-8"))
    assert "insufficient readable text" in str(exc_info.value)


def test_extract_txt_too_large_characters_raises() -> None:
    text = "A" * 500_001
    with pytest.raises(DocumentTooLargeError) as exc_info:
        extract_text_from_file("huge.txt", text.encode("utf-8"))
    assert "exceeds maximum allowed limit of 500000 characters" in str(exc_info.value)


def test_extract_file_exceeds_max_bytes_raises() -> None:
    oversized = b"X" * (MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(DocumentTooLargeError) as exc_info:
        extract_text_from_file("huge.bin", oversized)
    assert "exceeds maximum allowed limit of 10485760 bytes" in str(exc_info.value)


def test_extract_unsupported_extension_raises() -> None:
    with pytest.raises(AppError) as exc_info:
        extract_text_from_file("program.exe", b"A" * 100)
    assert "Unsupported file type" in str(exc_info.value)


def test_extract_md_success() -> None:
    md_content = "# Title\n\nThis is markdown content that provides knowledge documentation."
    doc = extract_text_from_file("readme.md", md_content.encode("utf-8"))
    assert doc.filename == "readme.md"
    assert "# Title" in doc.text
    assert doc.mime_type == "text/markdown"


def test_extract_docx_success() -> None:
    docx_bytes = _create_docx(
        "Welcome to the knowledge base manual for production operations.",
        table_data=[["Header 1", "Header 2"], ["Row 1 Val", "Row 2 Val"]],
    )
    doc = extract_text_from_file("manual.docx", docx_bytes)
    assert "Welcome to the knowledge base manual" in doc.text
    assert "Header 1 | Header 2" in doc.text
    assert "Row 1 Val | Row 2 Val" in doc.text
    assert (
        doc.mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_extract_docx_missing_magic_bytes_raises() -> None:
    with pytest.raises(DocumentCorruptedError) as exc_info:
        extract_text_from_file("manual.docx", b"NOT_A_ZIP_HEADER" + b" " * 100)
    assert "missing PK zip header magic bytes" in str(exc_info.value)


def test_extract_docx_corrupted_zip_raises() -> None:
    corrupt_docx = b"PK\x03\x04" + b"\x00" * 100
    with pytest.raises(DocumentCorruptedError) as exc_info:
        extract_text_from_file("corrupt.docx", corrupt_docx)
    assert "Corrupted or invalid DOCX file" in str(exc_info.value)


def test_extract_pdf_success() -> None:
    doc = extract_text_from_file("sample.pdf", SAMPLE_PDF_BYTES)
    assert doc.filename == "sample.pdf"
    assert "This is a test document with sufficient text content" in doc.text
    assert doc.pages == 1
    assert doc.mime_type == "application/pdf"


def test_extract_pdf_missing_magic_bytes_raises() -> None:
    with pytest.raises(DocumentCorruptedError) as exc_info:
        extract_text_from_file("bad.pdf", b"NOT_PDF_HEADER" + b" " * 100)
    assert "missing %PDF- header magic bytes" in str(exc_info.value)


def test_extract_pdf_corrupt_content_raises() -> None:
    corrupt_pdf = b"%PDF-1.4\n" + b"\xff" * 200
    with pytest.raises(DocumentCorruptedError) as exc_info:
        extract_text_from_file("corrupt.pdf", corrupt_pdf)
    assert "Corrupted or invalid PDF file" in str(exc_info.value)


def test_extract_pdf_encrypted_raises() -> None:
    enc_pdf = _create_encrypted_pdf()
    with pytest.raises(DocumentPasswordProtectedError) as exc_info:
        extract_text_from_file("secret.pdf", enc_pdf)
    assert "password-protected" in str(exc_info.value)


def test_extract_pdf_exceeds_page_limit_raises() -> None:
    multi_page_pdf = _create_multi_page_pdf(MAX_PDF_PAGES + 1)
    with pytest.raises(DocumentTooLargeError) as exc_info:
        extract_text_from_file("many_pages.pdf", multi_page_pdf)
    assert "exceeds maximum page limit" in str(exc_info.value)
