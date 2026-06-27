"""
auth.py — Microsoft 365 SSO authentication for Dream Big PM Dashboard.

Uses MSAL for OAuth flow. Session stored in a signed httponly cookie.
Set SKIP_AUTH=true in .env for local development without Azure setup.
"""

import os
import json
import logging
from typing import Optional

import msal
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException

from backend import database

logger = logging.getLogger(__name__)

COOKIE_NAME = "dbpm_session"
COOKIE_MAX_AGE = 28800  # 8 hours
ALLOWED_DOMAIN = "dreambigpm.com"
SCOPES = ["openid", "profile", "email", "User.Read"]

_signer: Optional[URLSafeTimedSerializer] = None


def _get_signer() -> URLSafeTimedSerializer:
    global _signer
    if _signer is None:
        secret = os.getenv("SECRET_KEY", "dev-secret-change-me")
        _signer = URLSafeTimedSerializer(secret)
    return _signer


def _get_msal_app() -> msal.ConfidentialClientApplication:
    client_id = os.getenv("MICROSOFT_CLIENT_ID", "")
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    tenant_id = os.getenv("MICROSOFT_TENANT_ID", "")

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )


def _redirect_uri() -> str:
    port = os.getenv("APP_PORT", "8000")
    return f"http://localhost:{port}/auth/callback"


def get_microsoft_auth_url() -> str:
    """Build the Microsoft OAuth redirect URL."""
    app = _get_msal_app()
    result = app.get_authorization_request_url(
        scopes=SCOPES,
        redirect_uri=_redirect_uri(),
    )
    return result


def exchange_code_for_token(code: str) -> dict:
    """
    Exchange the OAuth authorization code for an access token.
    Returns dict with 'email' and 'name' keys.
    Raises ValueError if the email domain is not dreambigpm.com.
    """
    app = _get_msal_app()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=_redirect_uri(),
    )

    if "error" in result:
        raise ValueError(f"Microsoft token exchange failed: {result.get('error_description', result['error'])}")

    id_token_claims = result.get("id_token_claims", {})
    email = (
        id_token_claims.get("preferred_username")
        or id_token_claims.get("email")
        or id_token_claims.get("upn")
        or ""
    ).lower()

    if not email.endswith(f"@{ALLOWED_DOMAIN}"):
        raise ValueError(f"Access denied: {email} is not a @{ALLOWED_DOMAIN} account")

    name = id_token_claims.get("name") or id_token_claims.get("displayName") or email.split("@")[0]

    return {"email": email, "name": name}


def create_session_cookie(user_data: dict) -> str:
    """Sign session data into a cookie-safe string."""
    return _get_signer().dumps(user_data)


def decode_session_cookie(cookie: str) -> Optional[dict]:
    """Decode and verify a session cookie. Returns None if invalid or expired."""
    try:
        return _get_signer().loads(cookie, max_age=COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    except Exception as e:
        logger.warning(f"Cookie decode error: {e}")
        return None


async def get_current_user(request: Request) -> dict:
    """
    FastAPI dependency — returns the current authenticated user dict.
    Raises HTTPException(401) if not authenticated.

    If SKIP_AUTH=true, returns a hardcoded admin user for local testing.
    """
    if os.getenv("SKIP_AUTH", "").lower() == "true":
        return {
            "user_id": 1,
            "email": "brian@dreambigpm.com",
            "role": "admin",
            "display_name": "Brian Bean",
        }

    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        raise HTTPException(status_code=401, detail="Not authenticated")

    data = decode_session_cookie(cookie)
    if not data:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")

    return data


def require_role(*allowed_roles: str):
    """FastAPI dependency factory that enforces role access."""
    async def _check(user: dict = None):
        # This is used inside route handlers with the user dict already resolved
        if user and user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This section requires one of: {', '.join(allowed_roles)}"
            )
        return user
    return _check
