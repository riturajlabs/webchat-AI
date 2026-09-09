"""Privacy utilities for safe logging of user-provided content.

All user-supplied text (queries, answers, prompts) must never appear in
logs in plaintext.  This module provides deterministic SHA-256 hashing
that lets operators correlate events without exposing PII.
"""

import hashlib


def content_hash(text: str) -> str:
    """Return the first 16 hex chars of the SHA-256 digest of *text*.

    Truncation keeps log lines short while providing enough entropy
    (~64 bits) for practical correlation.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def mask_email(email: str) -> str:
    """Redact a user email address for log output (BE-Q15).

    Keeps a short, non-identifying prefix plus the sending domain so
    operators can still eyeball which mailbox flow failed without exposing
    the full PII address.  Addresses without a valid ``@`` separator are
    masked in full.
    """
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    prefix = local[:2] if len(local) > 2 else local
    return f"{prefix}***@{domain}"


def safe_query_meta(text: str) -> dict[str, object]:
    """Return a dict safe for inclusion in structured log calls.

    Usage in an f-string log line::

        logger.info("chat_request query_hash=%s query_length=%d ...",
                     safe_query_meta(text)["query_hash"],
                     safe_query_meta(text)["query_length"], ...)

    Or passed as ``extra``::

        logger.info("chat_request", extra=safe_query_meta(text))
    """
    return {"query_hash": content_hash(text), "query_length": len(text)}


__all__ = ["content_hash", "mask_email", "safe_query_meta"]
