"""
JWT Authentication dependency for FastAPI.

Verifies Supabase access tokens using JWKS from the Supabase project's
well-known endpoint. Falls back to the static SUPABASE_JWT_SECRET only
when the JWKS endpoint is genuinely unavailable (no SUPABASE_URL configured
or client creation failed).

Critical security rule:
  A token that fails signature/claims verification via JWKS MUST be
  rejected. We do NOT retry with the static secret — that would allow
  a token signed with a different/forged key to potentially pass on
  the second attempt.

Verification flow:
  1. Extract Bearer token from Authorization header
  2. If JWKS is available (SUPABASE_URL configured):
       a. Fetch keys from Supabase JWKS endpoint (cached)
       b. Find the key matching the token's kid
       c. Verify signature + issuer + audience + expiration
       d. If ANY verification fails → reject immediately
  3. If JWKS is NOT available (no SUPABASE_URL):
       a. Use static SUPABASE_JWT_SECRET (HS256 HMAC)
       b. Verify signature + issuer + audience + expiration
       c. If verification fails → reject
  4. Extract authenticated user ID (sub claim)
"""

import os
import logging
from typing import Optional
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# The audience claim in Supabase Auth JWTs is "authenticated".
SUPABASE_AUDIENCE = "authenticated"

# Supabase JWTs use "<SUPABASE_URL>/auth/v1" as the issuer claim.
# We derive this once so jwt.decode() matches the token's iss exactly.
SUPABASE_ISSUER = f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else None

if not SUPABASE_URL and not SUPABASE_JWT_SECRET:
    raise ValueError(
        "Either SUPABASE_URL (for JWKS) or SUPABASE_JWT_SECRET must be set"
    )

# JWKS URL for the Supabase project
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else None

# HTTP Bearer token scheme
security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# AuthUser — returned by the dependency
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
    """Get cached PyJWKClient for JWKS-based verification.

    Returns None only if SUPABASE_URL is not set or client creation fails.
    """
    if not JWKS_URL:
        return None
    try:
        return PyJWKClient(JWKS_URL, cache_keys=True)
    except Exception as e:
        logger.warning(
            f"Failed to create JWKS client: {e}. "
            "JWKS verification will be unavailable."
        )
        return None


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------

def _decode_with_jwks(token: str) -> dict:
    """Verify a token using the Supabase JWKS endpoint.

    Returns the decoded payload on success.
    Raises HTTPException on any verification failure — no fallback.
    """
    jwk_client = _get_jwk_client()
    if jwk_client is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWKS endpoint not available",
            headers={"WWW-Authenticate": "Bearer"},
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
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"JWKS token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _decode_with_static_secret(token: str) -> dict:
    """Verify a token using the static SUPABASE_JWT_SECRET (HS256).

    Used only when the JWKS endpoint is genuinely unavailable.
    """
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No JWT verification method configured",
            headers={"WWW-Authenticate": "Bearer"},
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
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Static secret token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_supabase_token(token: str) -> dict:
    """Decode and verify a Supabase JWT token.

    Routing logic:
      - If JWKS is available (SUPABASE_URL set AND client created) →
        use JWKS ONLY. Any verification failure is fatal — no fallback.
      - If JWKS is NOT available (no SUPABASE_URL or client creation failed) →
        use the static SUPABASE_JWT_SECRET.

    This prevents an attacker from obtaining a valid session by having a
    token that fails JWKS verification but passes the static secret check
    (which would imply two different signing keys are accepted).
    """
    jwk_client = _get_jwk_client()

    if jwk_client is not None:
        # JWKS is available → use it exclusively.
        # Any failure here is final — we do NOT fall back.
        return _decode_with_jwks(token)

    # JWKS is genuinely unavailable → use static secret if configured.
    return _decode_with_static_secret(token)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthUser:
    """FastAPI dependency that extracts the authenticated user from a Supabase JWT.

    Usage in route handlers:
        @router.get("/protected")
        async def protected_route(user: AuthUser = Depends(get_current_user)):
            return {"user_id": user.id}
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_supabase_token(credentials.credentials)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("email")

    return AuthUser(id=user_id, email=email)


# ---------------------------------------------------------------------------
# Admin dependency
# ---------------------------------------------------------------------------

async def require_admin(
    current_user: AuthUser = Depends(get_current_user),
) -> AuthUser:
    """FastAPI dependency that requires the authenticated user to be an admin.

    Checks the profiles.is_admin column via the service-role Supabase client.

    Usage in route handlers:
        @router.post("/admin/domains")
        async def create_domain(
            admin: AuthUser = Depends(require_admin),
            ...
        ):
            ...
    """
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
