"""
Supabase client configuration for the backend.

Uses the service role key for server-side operations.
This client bypasses RLS — use with caution.
"""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError(
        "Missing Supabase configuration. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env"
    )

supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def is_foreign_key_violation(exc: Exception) -> bool:
    """Best-effort detection of a PostgreSQL FK (RESTRICT) violation.

    Supabase surfaces the SQLSTATE on the raised APIError (``code == '23503'``)
    and includes it in the message, so both shapes are checked. Used by the
    admin delete routes to turn a blocked delete into an actionable 409 instead
    of leaking a raw Postgres error as a 500.
    """
    code = getattr(exc, "code", None)
    if code == "23503":
        return True
    text = str(exc).lower()
    return (
        "23503" in text
        or "foreign key constraint" in text
        or "violates foreign key" in text
    )
