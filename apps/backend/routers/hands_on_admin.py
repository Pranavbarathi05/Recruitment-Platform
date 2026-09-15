from fastapi import APIRouter, Depends, HTTPException
from core.auth import require_admin, AuthUser
from core.supabase import supabase_client
from schemas.assessment import HandsOnCreate, HandsOnUpdate

router = APIRouter(prefix="/admin/hands-on-questions", tags=["Admin Hands-On"])


def _enrich_domain_names(questions: list) -> list:
    """Attach domain names to challenges via their domain_ids array."""
    all_ids = set()
    for q in questions:
        all_ids.update(q.get("domain_ids") or [])
    if not all_ids:
        return questions

    domains_resp = (
        supabase_client.table("domains")
        .select("id, name")
        .in_("id", list(all_ids))
        .execute()
    )
    domain_map = {d["id"]: d["name"] for d in (domains_resp.data or [])}
    for q in questions:
        q["domain_names"] = [domain_map.get(did, "") for did in (q.get("domain_ids") or [])]
    return questions


@router.get("")
def list_hands_on_questions(admin: AuthUser = Depends(require_admin)):
    """List all hands-on challenges. Admin only."""
    try:
        response = (
            supabase_client.table("hands_on_questions")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return _enrich_domain_names(response.data or [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}")
def get_hands_on_question(
    question_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Get a single hands-on challenge (includes the expected flag). Admin only."""
    try:
        resp = (
            supabase_client.table("hands_on_questions")
            .select("*")
            .eq("id", question_id)
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Hands-on challenge not found")
        q = resp.data[0]
        _enrich_domain_names([q])
        return q
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", status_code=201)
def create_hands_on_question(
    payload: HandsOnCreate,
    admin: AuthUser = Depends(require_admin),
):
    """Create a hands-on challenge. Admin only."""
    try:
        if payload.domain_ids:
            domains_resp = (
                supabase_client.table("domains")
                .select("id")
                .in_("id", payload.domain_ids)
                .execute()
            )
            if not domains_resp.data or len(domains_resp.data) != len(payload.domain_ids):
                raise HTTPException(status_code=400, detail="One or more domain IDs not found")

        result = supabase_client.table("hands_on_questions").insert({
            "title": payload.title,
            "description": payload.description,
            "domain_ids": payload.domain_ids,
            "challenge_type": payload.challenge_type,
            "difficulty": payload.difficulty,
            "points": payload.points,
            "challenge_url": payload.challenge_url,
            "expected_flag": payload.expected_flag.strip(),
            "is_active": payload.is_active,
        }).execute()

        return result.data[0] if result.data else {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{question_id}")
def update_hands_on_question(
    question_id: str,
    payload: HandsOnUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Update a hands-on challenge. Admin only."""
    try:
        existing = (
            supabase_client.table("hands_on_questions")
            .select("id")
            .eq("id", question_id)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Hands-on challenge not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        if "domain_ids" in updates and updates["domain_ids"]:
            domains_resp = (
                supabase_client.table("domains")
                .select("id")
                .in_("id", updates["domain_ids"])
                .execute()
            )
            if not domains_resp.data or len(domains_resp.data) != len(updates["domain_ids"]):
                raise HTTPException(status_code=400, detail="One or more domain IDs not found")

        if "expected_flag" in updates and updates["expected_flag"] is not None:
            updates["expected_flag"] = updates["expected_flag"].strip()

        result = (
            supabase_client.table("hands_on_questions")
            .update(updates)
            .eq("id", question_id)
            .execute()
        )
        return result.data[0] if result.data else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{question_id}")
def delete_hands_on_question(
    question_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Delete a hands-on challenge if safe (not referenced by attempts). Admin only."""
    try:
        existing = (
            supabase_client.table("hands_on_questions")
            .select("id")
            .eq("id", question_id)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Hands-on challenge not found")

        # Check if referenced by any assessment attempt
        attempts = (
            supabase_client.table("assessment_attempts")
            .select("id")
            .contains("selected_hands_on_question_ids", [question_id])
            .limit(1)
            .execute()
        )
        if attempts.data:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete: challenge is referenced by existing attempts. Use deactivation instead.",
            )

        supabase_client.table("hands_on_questions").delete().eq("id", question_id).execute()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
