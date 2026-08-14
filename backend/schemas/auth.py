"""Pydantic v2 request/response schemas for the authentication API."""

import re
from datetime import datetime
from typing import Any

import email_validator
from pydantic import BaseModel, ConfigDict, Field, field_validator

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72
_PASSWORD_CLASSES = (
    re.compile(r"[a-z]"),
    re.compile(r"[A-Z]"),
    re.compile(r"\d"),
    re.compile(r"[^A-Za-z0-9]"),
)


def validate_email(value: str) -> str:
    """Normalize and strictly validate an email address.

    The backend is the source of truth for email format: the same
    `email-validator` library Pydantic's `EmailStr` uses, but surfaced with a
    single, user-facing message instead of library-specific wording.
    """
    normalized = value.strip().lower()
    try:
        email_validator.validate_email(normalized, check_deliverability=False)
    except email_validator.EmailNotValidError as exc:
        raise ValueError("Please enter a valid email address.") from exc
    return normalized


def validate_password_policy(password: str) -> str:
    """Enforce the ADR-003 password policy: >=8 chars, <=72 bytes, 3/4 classes.

    Raises ValueError (=> HTTP 422 via Pydantic) when the policy is violated.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    matched = sum(1 for pattern in _PASSWORD_CLASSES if pattern.search(password))
    if matched < 3:
        raise ValueError(
            "Password must contain at least three of: lowercase, uppercase, digit, symbol."
        )
    return password


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)

    @field_validator("email", mode="before")
    @classmethod
    def _validate_email(cls, value: object) -> str:
        return _validated_email(value)

    @field_validator("password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return validate_password_policy(value)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def _validate_email(cls, value: object) -> str:
        return _validated_email(value)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10)


class ResendVerificationRequest(BaseModel):
    email: str

    @field_validator("email", mode="before")
    @classmethod
    def _validate_email(cls, value: object) -> str:
        return _validated_email(value)


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email", mode="before")
    @classmethod
    def _validate_email(cls, value: object) -> str:
        return _validated_email(value)


def _validated_email(value: object) -> str:
    """Shared email field validation for the auth request schemas."""
    if not isinstance(value, str):
        raise ValueError("Please enter a valid email address.")
    return validate_email(value)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)

    @field_validator("new_password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return validate_password_policy(value)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: str
    role: str
    email_verified: bool
    status: str
    tenant_id: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: Any, *, role: str) -> "UserOut":
        return cls(
            id=user.id,
            name=user.name,
            email=user.email,
            role=role,
            email_verified=user.email_verified,
            status=user.status,
            tenant_id=user.tenant_id,
            created_at=user.created_at,
        )

    @classmethod
    def from_principal(cls, principal: Any) -> "UserOut":
        return cls(
            id=principal.user_id,
            name=principal.name,
            email=principal.email,
            role=principal.role,
            email_verified=principal.email_verified,
            status=principal.status,
            tenant_id=principal.tenant_id,
            created_at=principal.created_at,
        )


class AuthResponse(BaseModel):
    """Access token + cookies data returned by register/login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str
    user: UserOut


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class MessageResponse(BaseModel):
    message: str
