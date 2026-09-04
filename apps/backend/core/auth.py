"""
JWT Authentication dependency for FastAPI.

Authentication is cookie-only. The browser sends the session cookie
automatically. No Bearer tokens are accepted from the frontend.

Verification flow:
  1. Read JWT from dsc_session cookie
  2. If JWKS is available (SUPABASE_URL configured):
       a. Verify signature + issuer + audience + expiration via JWKS
  3. If JWKS is NOT available:
       a. Verify via static SUPABASE_JWT_SECRET (HS256)
  4. Extract authenticated user ID (sub claim)
"""

import os
import logging
from typing import Optional
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

SUPABASE_AUDIENCE = "authenticated"
SUPABASE_ISSUER = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else None

if not SUPABASE_URL and not SUPABASE_JWT_SECRET:
    raise ValueError(
        "Either SUPABASE_URL (for JWKS) or SUPABASE_JWT_SECRET must be set"
    )

JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else None

SESSION_COOKIE_NAME = "dsc_session"


# ---------------------------------------------------------------------------

class AuthUser:
    """Represents an authenticated Supabase user."""

    def __init__(self, id: str, email: Optional[str] = None):
        self.id = id
        self.email = email


# ---------------------------------------------------------------------------
# JWKS client (cached)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_jwk_client() -> Optional[PyJWKClient]:
    if not JWKS_URL:
        return None
    try:
        return PyJWKClient(JWKS_URL, cache_keys=True)
    except Exception as e:
        logger.warning(f"Failed to create JWKS client: {e}")
        return None


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------

def _decode_with_jwks(token: str) -> dict:
    jwk_client = _get_jwk_client()
    if jwk_client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWKS endpoint not available",
            headers={"WWW-Authenticate": "Cookie"},
        )

    try:
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["HS256", "RS256", "ES256"],
            audience=SUPABASE_AUDIENCE,
            issuer=SUPABASE_ISSUER,
            options={"verify_aud": True, "verify_iss": True},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Cookie"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Cookie"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Cookie"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWKS token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Cookie"},
        )


def _decode_with_static_secret(token: str) -> dict:
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No JWT verification method configured",
            headers={"WWW-Authenticate": "Cookie"},
        )

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience=SUPABASE_AUDIENCE,
            issuer=SUPABASE_ISSUER,
            options={"verify_aud": True, "verify_iss": True},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Cookie"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Cookie"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Cookie"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Static secret token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Cookie"},
        )


def decode_supabase_token(token: str) -> dict:
    """Decode and verify a Supabase JWT token."""
    jwk_client = _get_jwk_client()
    if jwk_client is not None:
        return _decode_with_jwks(token)
    return _decode_with_static_secret(token)


# ---------------------------------------------------------------------------
# FastAPI dependency — COOKIE ONLY, no Bearer
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> AuthUser:
    """Extract the authenticated user from the dsc_session cookie.

    Authentication is cookie-only. No Authorization Bearer header is accepted.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Cookie"},
        )

    payload = decode_supabase_token(token)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
            headers={"WWW-Authenticate": "Cookie"},
        )

    email = payload.get("email")
    return AuthUser(id=user_id, email=email)


# ---------------------------------------------------------------------------
# Admin dependency
# ---------------------------------------------------------------------------

async def require_admin(
    current_user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """Require the authenticated user to be an admin."""
    from core.supabase import supabase_client

    result = (
        supabase_client.table("profiles")
        .select("is_admin")
        .eq("id", current_user.id)
        .execute()
    )

    if not result.data or not result.data[0].get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    return current_user
