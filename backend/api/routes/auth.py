"""Authentication endpoints (Phase 2, ADR-003).

Cookie strategy:
  refresh_token  HttpOnly; Secure; SameSite=Lax; Path=/api/auth
  csrf_token     NOT HttpOnly; Secure; SameSite=Lax; Path=/
Only the refresh/logout endpoints are cookie-authenticated and therefore carry
the double-submit CSRF check; bearer-token endpoints (/api/auth/me and beyond)
are immune to CSRF by design.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from backend.api.deps import (
    client_ip,
    current_user,
    forgot_password_limiter,
    get_account_service,
    get_auth_service,
    login_limiter,
    refresh_limiter,
    register_limiter,
    resend_verification_limiter,
    reset_password_limiter,
    verify_csrf,
    verify_email_limiter,
)
from backend.core.config import get_settings
from backend.core.errors import InvalidCredentialsError
from backend.core.security import generate_csrf_token
from backend.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshResponse,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    UpdateProfileRequest,
    UserOut,
    VerifyEmailRequest,
)
from backend.services.account import AccountService
from backend.services.auth import AuthResult, AuthService, Principal

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, refresh_token: str, csrf_token: str) -> None:
    settings = get_settings()
    max_age = settings.jwt_refresh_token_expire_days * 24 * 3600
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
        max_age=max_age,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=max_age,
    )


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.refresh_cookie_name, path="/api/auth")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def _to_auth_response(result: AuthResult, *, csrf_token: str) -> AuthResponse:
    return AuthResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        csrf_token=csrf_token,
        user=UserOut.from_user(result.user, role=result.role),
    )


def _to_refresh_response(result: AuthResult) -> RefreshResponse:
    return RefreshResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserOut.from_user(result.user, role=result.role),
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(register_limiter)],
) -> AuthResponse:
    result = await auth.register(
        name=body.name,
        email=str(body.email),
        password=body.password,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    csrf_token = generate_csrf_token()
    _set_session_cookies(response, result.refresh_token, csrf_token)
    return _to_auth_response(result, csrf_token=csrf_token)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(login_limiter)],
) -> AuthResponse:
    result = await auth.login(
        email=str(body.email),
        password=body.password,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    csrf_token = generate_csrf_token()
    _set_session_cookies(response, result.refresh_token, csrf_token)
    return _to_auth_response(result, csrf_token=csrf_token)


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(verify_email_limiter)],
) -> MessageResponse:
    await auth.verify_email(
        token=body.token,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Email verified.")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(resend_verification_limiter)],
) -> MessageResponse:
    await auth.resend_verification(
        email=str(body.email),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(
        message="If that email is registered, a new verification link has been sent."
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(refresh_limiter)],
    __: Annotated[None, Depends(verify_csrf)],
) -> RefreshResponse:
    settings = get_settings()
    raw_refresh = request.cookies.get(settings.refresh_cookie_name, "")
    if not raw_refresh:
        raise InvalidCredentialsError("No session cookie present.")
    result = await auth.refresh(
        raw_refresh_token=raw_refresh,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    csrf_token = request.cookies.get(settings.csrf_cookie_name, "") or generate_csrf_token()
    _set_session_cookies(response, result.refresh_token, csrf_token)
    return _to_refresh_response(result)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(verify_csrf)],
    all_sessions: bool = Query(default=False),
) -> MessageResponse:
    settings = get_settings()
    raw_refresh = request.cookies.get(settings.refresh_cookie_name, "")
    if raw_refresh:
        if all_sessions:
            await auth.logout_all(
                raw_refresh_token=raw_refresh,
                ip_address=client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
        else:
            await auth.logout(
                raw_refresh_token=raw_refresh,
                ip_address=client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
    _clear_session_cookies(response)
    return MessageResponse(message="Logged out.")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(forgot_password_limiter)],
) -> MessageResponse:
    await auth.forgot_password(
        email=str(body.email),
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="If that email is registered, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
    _: Annotated[None, Depends(reset_password_limiter)],
) -> MessageResponse:
    await auth.reset_password(
        token=body.token,
        new_password=body.new_password,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Password has been reset.")


@router.get("/me", response_model=UserOut)
async def me(principal: Annotated[Principal, Depends(current_user)]) -> UserOut:
    return UserOut.from_principal(principal)


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateProfileRequest,
    principal: Annotated[Principal, Depends(current_user)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> UserOut:
    """Update editable profile fields (name, avatar_url) for the signed-in user."""
    fields: dict[str, str | None] = {}
    if "name" in body.model_fields_set and body.name is not None:
        fields["name"] = body.name
    if "avatar_url" in body.model_fields_set:
        # Explicit null/"" clears the avatar.
        fields["avatar_url"] = body.avatar_url
    updated = await auth.update_profile(user_id=principal.user_id, **fields)
    return UserOut.from_user(updated, role=principal.role)


@router.delete("/me", response_model=MessageResponse)
async def delete_me(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(current_user)],
    account: Annotated[AccountService, Depends(get_account_service)],
) -> MessageResponse:
    """Irreversibly delete the signed-in user's account and its data.

    The deletion is always scoped to the authenticated user's own private
    tenant (resolved from the verified principal, never from request input).
    The session cookies are cleared once the purge completes.
    """
    await account.delete_account(
        principal=principal,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _clear_session_cookies(response)
    return MessageResponse(message="Your account has been deleted.")
