"""Shared time helpers for server-authoritative assessment expiry.

Every candidate-facing endpoint enforces the SAME rule against the SAME
frozen column (``assessment_attempts.expires_at``). The assessment and coding
routers previously carried byte-identical private copies of this logic, which
could drift apart; both now use these helpers.

This deliberately does NOT change the timer design: ``expires_at`` stays an
absolute, server-side, frozen timestamp, and an attempt without ``expires_at``
is still treated as never expiring (the behaviour both routers relied on).
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time, timezone-aware."""
    return datetime.now(timezone.utc)


def is_expired(attempt: dict) -> bool:
    """True when the attempt's ``expires_at`` is in the past.

    Accepts the value exactly as stored/returned by Postgres — either a
    ``datetime`` or an ISO-8601 string (including a trailing ``Z``).
    """
    expires_at = attempt.get("expires_at")
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return utcnow() > expires_at
