from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import require_admin, AuthUser
from core.supabase import supabase_client
from schemas.assessment import DomainCreate, DomainUpdate, MCQCreate, MCQUpdate, VALID_SEMESTERS

router = APIRouter(prefix="/admin", tags=["Admin"])


# ---------------------------------------------------------------------------
# Domain management
# ---------------------------------------------------------------------------

@router.get("/domains")
def list_all_domains(admin: AuthUser = Depends(require_admin)):
    """List all domains (active and inactive) with per-semester MCQ counts. Admin only."""
    try:
        response = (
            supabase_client.table("domains")
            .select("id, name, slug, description, duration_minutes, is_active, created_at")
            .order("name")
            .execute()
        )

        domains = []
        for d in response.data:
            # Get MCQ counts per semester
            semester_counts = {}
            for sem in VALID_SEMESTERS:
                q_count = (
                    supabase_client.table("mcq_questions")
                    .select("id", count="exact")
                    .eq("domain_id", d["id"])
                    .eq("semester", sem)
                    .execute()
                )
                semester_counts[str(sem)] = len(q_count.data) if q_count.data else 0

            # Total count
            total = (
                supabase_client.table("mcq_questions")
                .select("id", count="exact")
                .eq("domain_id", d["id"])
                .execute()
            )

            domains.append({
                **d,
                "questionCount": len(total.data) if total.data else 0,
                "semesterCounts": semester_counts,
            })

        return domains
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domains", status_code=201)
def create_domain(payload: DomainCreate, admin: AuthUser = Depends(require_admin)):
    """Create a new domain. Admin only."""
    try:
        existing = (
            supabase_client.table("domains")
            .select("id")
            .eq("slug", payload.slug)
            .execute()
        )
        if existing.data:
            raise HTTPException(status_code=409, detail="Domain slug already exists")

        result = supabase_client.table("domains").insert({
            "name": payload.name,
            "slug": payload.slug,
            "description": payload.description,
            "duration_minutes": payload.duration_minutes,
            "is_active": payload.is_active,
        }).execute()

        return result.data[0] if result.data else {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/domains/{domain_id}")
def update_domain(
    domain_id: str,
    payload: DomainUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Update a domain. Admin only."""
    try:
        existing = supabase_client.table("domains").select("id").eq("id", domain_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Domain not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        if "slug" in updates:
            slug_check = (
                supabase_client.table("domains")
                .select("id")
                .eq("slug", updates["slug"])
                .neq("id", domain_id)
                .execute()
            )
            if slug_check.data:
                raise HTTPException(status_code=409, detail="Domain slug already exists")

        result = supabase_client.table("domains").update(updates).eq("id", domain_id).execute()
        return result.data[0] if result.data else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domains/{domain_id}/deactivate")
def deactivate_domain(domain_id: str, admin: AuthUser = Depends(require_admin)):
    """Deactivate a domain (safe alternative to deletion). Admin only."""
    try:
        existing = supabase_client.table("domains").select("id").eq("id", domain_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Domain not found")

        supabase_client.table("domains").update({"is_active": False}).eq("id", domain_id).execute()
        return {"status": "deactivated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domains/{domain_id}/activate")
def activate_domain(domain_id: str, admin: AuthUser = Depends(require_admin)):
    """Activate a domain. Admin only."""
    try:
        existing = supabase_client.table("domains").select("id").eq("id", domain_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Domain not found")

        supabase_client.table("domains").update({"is_active": True}).eq("id", domain_id).execute()
        return {"status": "activated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# MCQ management
# ---------------------------------------------------------------------------

@router.get("/domains/{domain_id}/mcqs")
def list_mcqs(
    domain_id: str,
    semester: int = Query(None, description="Filter by semester: 1, 3, 5, or 7"),
    admin: AuthUser = Depends(require_admin),
):
    """List MCQs for a domain, optionally filtered by semester. Admin only."""
    try:
        domain = supabase_client.table("domains").select("id").eq("id", domain_id).execute()
        if not domain.data:
            raise HTTPException(status_code=404, detail="Domain not found")

        query = (
            supabase_client.table("mcq_questions")
            .select("*")
            .eq("domain_id", domain_id)
        )

        if semester is not None:
            if semester not in VALID_SEMESTERS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid semester. Must be one of {VALID_SEMESTERS}",
                )
            query = query.eq("semester", semester)

        response = query.order("semester").order("created_at").execute()
        return response.data or []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domains/{domain_id}/mcqs", status_code=201)
def create_mcq(
    domain_id: str,
    payload: MCQCreate,
    admin: AuthUser = Depends(require_admin),
):
    """Create an MCQ question for a domain. Admin only."""
    try:
        domain = supabase_client.table("domains").select("id").eq("id", domain_id).execute()
        if not domain.data:
            raise HTTPException(status_code=404, detail="Domain not found")

        if payload.domain_id != domain_id:
            raise HTTPException(status_code=400, detail="Domain ID mismatch")

        result = supabase_client.table("mcq_questions").insert({
            "domain_id": domain_id,
            "semester": payload.semester,
            "question_text": payload.question_text,
            "option_a": payload.option_a,
            "option_b": payload.option_b,
            "option_c": payload.option_c,
            "option_d": payload.option_d,
            "correct_option": payload.correct_option,
            "explanation": payload.explanation,
            "is_active": payload.is_active,
        }).execute()

        return result.data[0] if result.data else {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/mcqs/{mcq_id}")
def update_mcq(
    mcq_id: str,
    payload: MCQUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Update an MCQ question. Admin only."""
    try:
        existing = supabase_client.table("mcq_questions").select("id").eq("id", mcq_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="MCQ not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        result = supabase_client.table("mcq_questions").update(updates).eq("id", mcq_id).execute()
        return result.data[0] if result.data else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mcqs/{mcq_id}/activate")
def activate_mcq(mcq_id: str, admin: AuthUser = Depends(require_admin)):
    """Activate an MCQ. Admin only."""
    try:
        existing = supabase_client.table("mcq_questions").select("id").eq("id", mcq_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="MCQ not found")

        supabase_client.table("mcq_questions").update({"is_active": True}).eq("id", mcq_id).execute()
        return {"status": "activated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mcqs/{mcq_id}/deactivate")
def deactivate_mcq(mcq_id: str, admin: AuthUser = Depends(require_admin)):
    """Deactivate an MCQ (safe alternative to deletion). Admin only."""
    try:
        existing = supabase_client.table("mcq_questions").select("id").eq("id", mcq_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="MCQ not found")

        supabase_client.table("mcq_questions").update({"is_active": False}).eq("id", mcq_id).execute()
        return {"status": "deactivated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/mcqs/{mcq_id}")
def delete_mcq(mcq_id: str, admin: AuthUser = Depends(require_admin)):
    """Delete an MCQ question. Admin only.

    Use deactivation instead when historical attempt data exists.
    """
    try:
        existing = supabase_client.table("mcq_questions").select("id").eq("id", mcq_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="MCQ not found")

        # Check if this question is referenced by any assessment attempt
        attempts = (
            supabase_client.table("assessment_attempts")
            .select("id")
            .contains("selected_question_ids", [mcq_id])
            .limit(1)
            .execute()
        )
        if attempts.data:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete: question is referenced by existing attempts. Use deactivation instead.",
            )

        supabase_client.table("mcq_questions").delete().eq("id", mcq_id).execute()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
