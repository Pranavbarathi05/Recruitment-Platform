from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user, AuthUser
from core.supabase import supabase_client

router = APIRouter()


@router.get("/questions/domains")
def get_domains():
    """Get all active domains from Supabase."""
    try:
        response = (
            supabase_client.table("domains")
            .select("id, name, slug, duration_minutes")
            .eq("is_active", True)
            .execute()
        )

        # Transform to match frontend expected format
        domains = []
        for domain in response.data:
            domains.append({
                "id": domain["slug"],  # Frontend uses slug as identifier
                "name": domain["name"],
                "questionCount": 0,  # Will be populated when questions table exists
                "durationMinutes": domain["duration_minutes"],
            })

        return domains
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch domains: {str(e)}")


@router.get("/questions/{domain}")
def get_questions(domain: str):
    """Get questions for a specific domain. Requires authentication."""
    # TODO: Implement when questions table is created
    return []
