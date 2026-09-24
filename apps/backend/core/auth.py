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
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Path, Request, Response, status

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

# Absolute ceiling on the age of ANY login session, enforced SERVER-SIDE.
#
# A session is valid for at most SESSION_MAX_AGE_SECONDS after the access
# token's `iat` (issued-at) claim — regardless of the token's own `exp`
# claim and regardless of what the Supabase project's JWT expiry setting is
# configured to issue. This is the hard guarantee that a session can never
# silently outlive two hours: even a longer-lived token (or one produced by
# some future refresh path) is rejected here.
#
# The two other layers aligned to this same value:
#   * the dsc_session cookie Max-Age is capped at min(expires_in, this)
#     (routers.auth._set_session_cookie), and
#   * the Supabase "Access Token (JWT) expiry" dashboard setting should be
#     7200 so a normal session actually REACHES two hours (the code can only
#     cap downward, never extend).
#
# There is deliberately NO refresh-token flow in this application: the
# refresh_token Supabase returns at login is discarded, so no request can
# ever extend a session beyond one access-token lifetime.
SESSION_MAX_AGE_SECONDS = 2 * 60 * 60  # 2 hours


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


def _enforce_absolute_session_lifetime(payload: dict) -> None:
    """Reject tokens issued more than SESSION_MAX_AGE_SECONDS ago.

    GoTrue stamps every access token with `iat`. The standard `exp`
    verification (performed by jwt.decode in either decode path) bounds the
    token by Supabase's configured TTL; this check additionally bounds it by
    an APPLICATION-OWNED ceiling, so raising the Supabase JWT expiry (or any
    future refresh mechanism) can never extend a session past 2 hours.

    A token without a usable `iat` falls back to `exp` verification alone —
    GoTrue always issues `iat`, so that branch only covers hand-crafted
    tokens, which are still bounded by `exp`.
    """
    iat = payload.get("iat")
    if isinstance(iat, bool) or not isinstance(iat, (int, float)):
        return
    age_seconds = time.time() - float(iat)
    if age_seconds > SESSION_MAX_AGE_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired",
            headers={"WWW-Authenticate": "Cookie"},
        )


def decode_supabase_token(token: str) -> dict:
    """Decode and verify a Supabase JWT token.

    Verifies signature, audience, issuer and `exp`, then enforces the
    application's absolute 2-hour session ceiling.
    """
    jwk_client = _get_jwk_client()
    if jwk_client is not None:
        payload = _decode_with_jwks(token)
    else:
        payload = _decode_with_static_secret(token)
    _enforce_absolute_session_lifetime(payload)
    return payload


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


# ---------------------------------------------------------------------------
# Assessment-scoped authorization capability
# ---------------------------------------------------------------------------
#
# WHY: login sessions are hard-limited to SESSION_MAX_AGE_SECONDS (2h), but an
# attempt's frozen duration can outlive the session (login 19:00, attempt
# 19:50–21:05). When the session dies mid-attempt, every answer-save/submit
# call would 401 and the candidate would be unfairly interrupted.
#
# WHAT THIS IS: a second HttpOnly cookie that is NOT a login session:
#   * issued ONLY to an already-authenticated candidate at attempt start (and
#     attempt-questions fetch), bound to (profile_id, attempt_id, exp);
#   * `exp` is copied verbatim from the attempt's FROZEN expires_at — never
#     longer than the assessment itself; re-issuing never extends it because
#     the row, not the cookie, is authoritative and is re-checked every call;
#   * accepted ONLY by the 10 endpoints a candidate needs mid-assessment, and
#     ONLY after re-validating ownership (profile_id), status (in_progress)
#     and expiry against the assessment_attempts row;
#   * rejected by everything else (/admin/*, /questions/*, /assessment/start,
#     /assessment/current, /auth/* keep get_current_user unchanged);
#   * cleared on logout and when a different user logs in.
#
# KEY: HS256 with a key derived from SUPABASE_SERVICE_ROLE_KEY (server-only;
# unrelated to the Supabase JWT secret), so a capability can never validate as
# a Supabase access token and a Supabase access token can never validate as a
# capability. This does NOT weaken normal JWT verification: the session path
# above runs first with all signature/aud/iss/exp + 2h-ceiling rules intact.
ASSESSMENT_COOKIE_NAME = "dsc_assessment"
ASSESSMENT_CAPABILITY_TYPE = "assessment_access"


@lru_cache(maxsize=1)
def _capability_key() -> bytes:
    """Server-side signing key for assessment capability cookies."""
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not service_role_key:
        raise ValueError(
            "SUPABASE_SERVICE_ROLE_KEY must be set to derive the assessment "
            "capability signing key"
        )
    return hashlib.sha256(
        b"dsc-assessment-capability|" + service_role_key.encode("utf-8")
    ).digest()


def _parse_aware(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def issue_assessment_capability(
    response: Response,
    *,
    profile_id: str,
    attempt_id: str,
    expires_at,
) -> None:
    """Attach the assessment-scoped capability cookie to the response.

    Only called from handlers that already authorized the caller with a valid
    normal session — the capability can therefore never create access that the
    candidate did not already have, and can never start a new attempt.
    """
    exp_epoch = int(_parse_aware(expires_at).timestamp())
    now = int(time.time())
    if exp_epoch <= now:
        return  # attempt already over — never issue a dead capability
    token = jwt.encode(
        {
            "sub": profile_id,
            "att": attempt_id,
            "typ": ASSESSMENT_CAPABILITY_TYPE,
            "iat": now,
            "exp": exp_epoch,
        },
        _capability_key(),
        algorithm="HS256",
    )
    response.set_cookie(
        key=ASSESSMENT_COOKIE_NAME,
        value=token,
        max_age=max(1, exp_epoch - now),
        path="/",
        httponly=True,
        samesite="lax",
        secure=os.getenv("ENVIRONMENT", "development") == "production",
    )


def decode_assessment_capability(token: str) -> dict:
    """Verify signature + exp of a capability token.

    Deliberately NOT aud/iss-verified: this is not a Supabase JWT (those
    claims do not apply); unforgeability comes from the derived server key.
    """
    try:
        payload = jwt.decode(
            token,
            _capability_key(),
            algorithms=["HS256"],
            options={"verify_aud": False, "verify_iss": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Assessment access expired",
            headers={"WWW-Authenticate": "Cookie"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid assessment access",
            headers={"WWW-Authenticate": "Cookie"},
        )
    if (
        payload.get("typ") != ASSESSMENT_CAPABILITY_TYPE
        or not payload.get("sub")
        or not payload.get("att")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid assessment access",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return payload


def validate_assessment_capability(
    request: Request,
    expected_attempt_id: Optional[str] = None,
) -> dict:
    """Validate the capability cookie against the attempt ROW.

    The row is always authoritative: ownership (profile_id), lifecycle
    (status == in_progress) and the frozen expiry are re-checked on every
    call, so a capability becomes useless the moment the assessment is
    submitted or its expires_at passes — regardless of the cookie's own exp.
    """
    token = request.cookies.get(ASSESSMENT_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Cookie"},
        )

    claims = decode_assessment_capability(token)

    # A capability is valid for exactly ONE attempt: it can never be pointed
    # at another attempt id by changing the URL.
    if expected_attempt_id is not None and claims.get("att") != expected_attempt_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Assessment access denied",
        )

    from core.supabase import supabase_client

    result = (
        supabase_client.table("assessment_attempts")
        .select("id, profile_id, status, expires_at")
        .eq("id", claims["att"])
        .execute()
    )
    attempt = result.data[0] if result.data else None
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.get("profile_id") != claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Assessment access denied",
        )
    if attempt.get("status") != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Attempt is not in progress",
        )
    if _parse_aware(attempt["expires_at"]).timestamp() <= time.time():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Assessment time has expired",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return attempt


async def get_assessment_actor(
    request: Request,
    attempt_id: str = Path(...),
) -> AuthUser:
    """Authorize access to ONE specific attempt.

    Fast path: a valid normal session — all existing rules (signature, aud,
    iss, exp, 2-hour iat ceiling) apply; the endpoint's own ownership checks
    still run against whoever this user is.

    Fallback: the assessment capability, valid only for THIS attempt while its
    row is in_progress and not expired. Used solely so an in-flight assessment
    survives login-session expiry; a candidate with no live attempt gets a
    plain 401 exactly as before.
    """
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        try:
            payload = decode_supabase_token(session_token)
            user_id = payload.get("sub")
            if user_id:
                return AuthUser(id=user_id, email=payload.get("email"))
        except HTTPException:
            pass  # expired/invalid login session → try assessment capability

    attempt = validate_assessment_capability(
        request, expected_attempt_id=attempt_id
    )
    return AuthUser(id=attempt["profile_id"])
