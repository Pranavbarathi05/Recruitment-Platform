"""
Authentication Router

Mediates between the browser and Supabase Auth.

The browser communicates ONLY with FastAPI for authentication.
FastAPI communicates with Supabase Auth server-side.

Endpoints:
  POST /auth/signup  — create account
  POST /auth/login   — sign in
  POST /auth/logout  — sign out
  GET  /auth/me      — get current user
  GET  /auth/csrf    — get CSRF token for double-submit pattern

Security:
  - JWT is NEVER returned to the browser
  - Authentication is purely cookie-based (HttpOnly)
  - CSRF protection via double-submit token pattern
"""

import os
import logging
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, Response, Request
from pydantic import BaseModel, Field

from core.auth import decode_supabase_token, AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Supabase Auth API configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

# Cookie configuration
COOKIE_NAME = "dsc_session"
COOKIE_MAX_AGE = 3600 * 24  # 24 hours
COOKIE_PATH = "/"
CSRF_COOKIE_NAME = "dsc_csrf"

# Determine if we should use Secure cookies
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development") == "production"


# ============================================================
# Request/Response Schemas
# ============================================================

class SignupRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=6)
    fullName: str = Field(..., min_length=1, alias="full_name")
    usn: str = Field(..., min_length=1)
    semester: int = Field(..., ge=1, le=8)
    branch: str = Field(..., min_length=1)

    model_config = {"populate_by_name": True}


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    user: dict
    # NO access_token field — JWT is never exposed to the browser


class UserResponse(BaseModel):
    id: str
    email: Optional[str] = None


# ============================================================
# Supabase Auth API helpers
# ============================================================

async def _supabase_sign_up(email: str, password: str, metadata: dict) -> dict:
    """Call Supabase Auth signUp endpoint server-side."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    url = f"{SUPABASE_URL}/auth/v1/signup"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
        "data": metadata,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()

        if resp.status_code >= 400:
            error_msg = data.get("msg", data.get("message", "Signup failed"))
            raise HTTPException(status_code=resp.status_code, detail=error_msg)

        return data


async def _supabase_sign_in(email: str, password: str) -> dict:
    """Call Supabase Auth signInWithPassword endpoint server-side."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured")

    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "password": password,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        data = resp.json()

        if resp.status_code >= 400:
            error_msg = data.get("error_description", data.get("msg", data.get("message", "Login failed")))
            raise HTTPException(status_code=resp.status_code, detail=error_msg)

        return data


async def _supabase_sign_out(access_token: str) -> None:
    """Call Supabase Auth signOut endpoint server-side."""
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return

    url = f"{SUPABASE_URL}/auth/v1/logout"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {access_token}",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, headers=headers)
    except Exception as e:
        logger.warning(f"Supabase logout failed (non-critical): {e}")


def _set_session_cookie(response: Response, access_token: str, expires_in: int = COOKIE_MAX_AGE) -> None:
    """Set the session cookie on the response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        max_age=expires_in,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,
    )


def _set_csrf_cookie(response: Response) -> str:
    """Generate and set a CSRF token cookie for double-submit pattern."""
    token = secrets.token_hex(32)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        httponly=False,  # Must be readable by JavaScript for double-submit
        samesite="lax",
        secure=IS_PRODUCTION,
    )
    return token


def _clear_session_cookie(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=False,
        samesite="lax",
        secure=IS_PRODUCTION,
    )


def _extract_token_from_request(request: Request) -> Optional[str]:
    """Extract JWT from session cookie only. No Bearer header support."""
    cookie_token = request.cookies.get(COOKIE_NAME)
    if cookie_token:
        return cookie_token

    return None


def _verify_csrf(request: Request) -> bool:
    """Verify CSRF double-submit token.

    For state-changing requests (POST, PUT, PATCH, DELETE):
    1. Read the CSRF token from the non-HttpOnly cookie
    2. Read the CSRF token from the X-CSRF-Token header
    3. They must match
    """
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get("X-CSRF-Token")

    if not cookie_token or not header_token:
        return False

    return secrets.compare_digest(cookie_token, header_token)


# ============================================================
# Endpoints
# ============================================================

@router.get("/csrf")
async def get_csrf_token(response: Response):
    """Get a CSRF token for the double-submit pattern.

    The token is set as a non-HttpOnly cookie AND returned in the response body.
    The frontend must send it back as X-CSRF-Token header on state-changing requests.
    """
    token = _set_csrf_cookie(response)
    return {"csrf_token": token}


@router.post("/signup", response_model=AuthResponse)
async def signup(payload: SignupRequest, request: Request, response: Response):
    """Create a new candidate account."""
    try:
        metadata = {
            "full_name": payload.fullName,
            "usn": payload.usn,
            "semester": payload.semester,
            "branch": payload.branch,
        }

        data = await _supabase_sign_up(payload.email, payload.password, metadata)

        access_token = data.get("access_token")
        user = data.get("user", {})
        expires_in = data.get("expires_in", 3600)

        if not access_token:
            # Email confirmation required — no session yet
            return AuthResponse(
                user={"id": user.get("id"), "email": user.get("email"), "needs_confirmation": True},
            )

        # Set session cookie (JWT never returned to browser)
        _set_session_cookie(response, access_token, expires_in)
        _set_csrf_cookie(response)

        return AuthResponse(
            user={"id": user.get("id"), "email": user.get("email")},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise HTTPException(status_code=500, detail="Signup failed")


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, request: Request, response: Response):
    """Sign in with email and password."""
    try:
        data = await _supabase_sign_in(payload.email, payload.password)

        access_token = data.get("access_token")
        user = data.get("user", {})
        expires_in = data.get("expires_in", 3600)

        if not access_token:
            raise HTTPException(status_code=401, detail="Authentication failed")

        # Set session cookie (JWT never returned to browser)
        _set_session_cookie(response, access_token, expires_in)
        _set_csrf_cookie(response)

        return AuthResponse(
            user={"id": user.get("id"), "email": user.get("email")},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Sign out and clear session."""
    token = _extract_token_from_request(request)
    if token:
        await _supabase_sign_out(token)

    _clear_session_cookie(response)
    return {"status": "logged out"}


@router.get("/me")
async def get_me(request: Request):
    """Get the current authenticated user from the session cookie."""
    token = _extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_supabase_token(token)
        user_id = payload.get("sub")
        email = payload.get("email")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {"id": user_id, "email": email}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(status_code=401, detail="Invalid session")
