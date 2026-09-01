from fastapi import APIRouter, HTTPException
from core.supabase import supabase_client

router = APIRouter()


@router.get("/questions/domains")
def get_active_domains():
    """Get all active domains with question counts and assessment duration."""
    try:
        response = (
            supabase_client.table("domains")
            .select("id, name, slug, description")
            .eq("is_active", True)
            .order("name")
            .execute()
        )

        # Fetch the active assessment config for the duration
        config_resp = (
            supabase_client.table("assessment_config")
            .select("duration_minutes")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        assessment_duration = (
            config_resp.data[0]["duration_minutes"]
            if config_resp.data
            else 20  # fallback default
        )

        domains = []
        for domain in response.data:
            # Count active MCQ questions for this domain
            q_count_resp = (
                supabase_client.table("mcq_questions")
                .select("id", count="exact")
                .eq("domain_id", domain["id"])
                .eq("is_active", True)
                .execute()
            )

            domains.append({
                "id": domain["id"],
                "slug": domain["slug"],
                "name": domain["name"],
                "description": domain.get("description", ""),
                "questionCount": len(q_count_resp.data) if q_count_resp.data else 0,
                "durationMinutes": assessment_duration,
            })

        return domains
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch domains: {str(e)}")


@router.get("/questions/domains/{domain_id}")
def get_domain_detail(domain_id: str):
    """Get details for a single domain."""
    try:
        response = (
            supabase_client.table("domains")
            .select("id, name, slug, description, is_active")
            .eq("id", domain_id)
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Domain not found")

        domain = response.data[0]

        q_count_resp = (
            supabase_client.table("mcq_questions")
            .select("id", count="exact")
            .eq("domain_id", domain_id)
            .eq("is_active", True)
            .execute()
        )

        # Fetch the active assessment config for the duration
        config_resp = (
            supabase_client.table("assessment_config")
            .select("duration_minutes")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        assessment_duration = (
            config_resp.data[0]["duration_minutes"]
            if config_resp.data
            else 20  # fallback default
        )

        return {
            "id": domain["id"],
            "slug": domain["slug"],
            "name": domain["name"],
            "description": domain.get("description", ""),
            "questionCount": len(q_count_resp.data) if q_count_resp.data else 0,
            "durationMinutes": assessment_duration,
            "isActive": domain["is_active"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch domain: {str(e)}")
