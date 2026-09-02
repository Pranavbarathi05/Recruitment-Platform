"""
Authentication Router

All auth operations (signup, login, logout, session management) are proxied
through FastAPI to the Supabase Auth API. The browser NEVER communicates
directly with Supabase.

Flow:
  Browser → POST /auth/login → FastAPI → Supabase Auth API → FastAPI returns session → Browser

The backend uses SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (already configured)
to make authenticated calls to the Supabase Auth REST API.
"""

import os
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from core.auth import decode_supabase_token, get_current_user, AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ---------------------------------------------------------------------------
# Supabase Auth API configuration
# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL must be set for auth proxy")

# The Supabase Auth REST API accepts the service-role key via the apikey header.
SUPABASE_AUTH_URL = f"{SUPABASE_URL}/auth/v1"

# Common headers for Supabase Auth API calls
_auth_headers = {
    "apikey": SUPABASE_SERVICE_ROLE_KEY,
    "Content-Type": "application/json",
}

# HTTP Bearer token scheme (for extracting token from requests)
security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=6)
    fullName: str = Field(..., min_length=1)
    usn: str = Field(..., min_length=1)
    semester: int = Field(..., description="Semester: 1, 3, 5, or 7")
    branch: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supabase_auth_request(method: str, path: str, **kwargs) -> dict:
    """Make a request to the Supabase Auth REST API.

    Returns the JSON response body as a dict.
    Raises HTTPException on failure.
    """
    url = f"{SUPABASE_AUTH_URL}{path}"
    headers = {**_auth_headers}

    # If an Authorization header is passed in kwargs, add it (for user-scoped calls)
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.request(method, url, headers=headers, **kwargs)
    except httpx.RequestError as e:
        logger.error(f"Supabase Auth API request failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service is unavailable",
        )

    if resp.status_code >= 400:
        try:
            error_body = resp.json()
            error_msg = error_body.get("msg") or error_body.get("message") or str(error_body)
        except Exception:
            error_msg = resp.text or f"Auth API returned status {resp.status_code}"

        logger.warning(f"Supabase Auth API error ({resp.status_code}): {error_msg}")

        # Map common Supabase auth errors to appropriate HTTP status codes
        if resp.status_code == 400:
            if "already" in error_msg.lower() or "registered" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email already exists",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )
        elif resp.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        elif resp.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_msg,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Authentication service error: {error_msg}",
            )

    return resp.json()


def _extract_user_info(supabase_user: dict) -> dict:
    """Extract relevant user info from a Supabase Auth user object."""
    user_metadata = supabase_user.get("user_metadata", {})
    return {
        "id": supabase_user.get("id"),
        "email": supabase_user.get("email"),
        "email_confirmed_at": supabase_user.get("email_confirmed_at"),
        "full_name": user_metadata.get("full_name", ""),
        "usn": user_metadata.get("usn", ""),
        "semester": user_metadata.get("semester"),
        "branch": user_metadata.get("branch", ""),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/signup")
def signup(payload: SignupRequest):
    """Register a new user via Supabase Auth.

    Passes candidate metadata (full_name, usn, semester, branch) as Supabase
    Auth user metadata. The database trigger (handle_new_user) creates both
    profile and candidate rows atomically.

    Returns session tokens and user info, or indicates email confirmation is needed.
    """
    result = _supabase_auth_request("POST", "/signup", json={
        "email": payload.email,
        "password": payload.password,
        "data": {
            "full_name": payload.fullName,
            "usn": payload.usn,
            "semester": payload.semester,
            "branch": payload.branch,
        },
    })

    user = result.get("user")
    session = result.get("session")

    # If email confirmation is required, session will be null
    needs_confirmation = user is not None and session is None

    return {
        "user": _extract_user_info(user) if user else None,
        "session": {
            "access_token": session.get("access_token"),
            "refresh_token": session.get("refresh_token"),
            "expires_in": session.get("expires_in"),
            "expires_at": session.get("expires_at"),
        } if session else None,
        "needs_confirmation": needs_confirmation,
    }


@router.post("/login")
def login(payload: LoginRequest):
    """Sign in with email and password.

    Calls the Supabase Auth token endpoint and returns the session
    (access_token, refresh_token) along with user info.
    """
    result = _supabase_auth_request("POST", "/token?grant_type=password", json={
        "email": payload.email,
        "password": payload.password,
    })

    user = result.get("user")
    session = result.get("session")

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    return {
        "user": _extract_user_info(user) if user else None,
        "session": {
            "access_token": session.get("access_token"),
            "refresh_token": session.get("refresh_token"),
            "expires_in": session.get("expires_in"),
            "expires_at": session.get("expires_at"),
        },
    }


@router.post("/refresh")
def refresh_token(payload: RefreshRequest):
    """Refresh an expired access token using a refresh token."""
    result = _supabase_auth_request("POST", "/token?grant_type=refresh_token", json={
        "refresh_token": payload.refresh_token,
    })

    user = result.get("user")
    session = result.get("session")

    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or expired",
        )

    return {
        "user": _extract_user_info(user) if user else None,
        "session": {
            "access_token": session.get("access_token"),
            "refresh_token": session.get("refresh_token"),
            "expires_in": session.get("expires_in"),
            "expires_at": session.get("expires_at"),
        },
    }


@router.post("/logout")
def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """Sign out. Invalidates the current session on the Supabase side."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        _supabase_auth_request(
            "POST",
            "/logout",
            headers={"Authorization": f"Bearer {credentials.credentials}"},
        )
    except HTTPException:
        # Even if Supabase logout fails (e.g., token already expired),
        # we treat it as successful from the client's perspective.
        logger.warning("Supabase logout request failed, treating as successful")

    return {"status": "logged_out"}


@router.get("/me")
def get_me(current_user: AuthUser = Depends(get_current_user)):
    """Get current user info from the JWT.

    The JWT is verified by the existing core/auth.py dependency.
    Returns user identity extracted from the token.
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
    }
