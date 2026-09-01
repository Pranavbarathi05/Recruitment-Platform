from fastapi import APIRouter, Depends, HTTPException
from core.auth import require_admin, AuthUser
from core.supabase import supabase_client
from schemas.coding import (
    CodingProblemCreate, CodingProblemUpdate,
    CodingTestCaseCreate, CodingTestCaseUpdate,
    VALID_CODING_LANGUAGES, VALID_DIFFICULTIES,
)

router = APIRouter(prefix="/admin/coding", tags=["Admin Coding"])


# ============================================================
# CODING PROBLEM MANAGEMENT
# ============================================================

@router.get("/problems")
def list_coding_problems(
    admin: AuthUser = Depends(require_admin),
):
    """List all coding problems. Admin only."""
    try:
        response = supabase_client.table("coding_problems").select("*").order("title").execute()

        problems = response.data or []

        # Enrich with test case counts
        for p in problems:
            # Count public + total test cases
            public_count = (
                supabase_client.table("coding_test_cases")
                .select("id", count="exact")
                .eq("problem_id", p["id"])
                .eq("is_public", True)
                .execute()
            )
            total_count = (
                supabase_client.table("coding_test_cases")
                .select("id", count="exact")
                .eq("problem_id", p["id"])
                .execute()
            )
            p["public_test_count"] = len(public_count.data) if public_count.data else 0
            p["total_test_count"] = len(total_count.data) if total_count.data else 0

        return problems
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/problems", status_code=201)
def create_coding_problem(
    payload: CodingProblemCreate,
    admin: AuthUser = Depends(require_admin),
):
    """Create a new coding problem. Admin only."""
    try:
        # Check slug uniqueness
        existing = supabase_client.table("coding_problems").select("id").eq("slug", payload.slug).execute()
        if existing.data:
            raise HTTPException(status_code=409, detail="Problem slug already exists")

        result = supabase_client.table("coding_problems").insert({
            "title": payload.title,
            "slug": payload.slug,
            "description": payload.description,
            "difficulty": payload.difficulty,
            "constraints": payload.constraints,
            "input_format": payload.input_format,
            "output_format": payload.output_format,
            "explanation": payload.explanation,
            "starter_code": payload.starter_code or {},
            "supported_languages": payload.supported_languages,
            "time_limit_ms": payload.time_limit_ms,
            "memory_limit_mb": payload.memory_limit_mb,
            "points": payload.points,
            "is_active": payload.is_active,
        }).execute()

        return result.data[0] if result.data else {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/problems/{problem_id}")
def update_coding_problem(
    problem_id: str,
    payload: CodingProblemUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Update a coding problem. Admin only."""
    try:
        existing = supabase_client.table("coding_problems").select("id").eq("id", problem_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Coding problem not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        result = supabase_client.table("coding_problems").update(updates).eq("id", problem_id).execute()
        return result.data[0] if result.data else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/problems/{problem_id}/activate")
def activate_coding_problem(problem_id: str, admin: AuthUser = Depends(require_admin)):
    """Activate a coding problem. Admin only."""
    try:
        existing = supabase_client.table("coding_problems").select("id").eq("id", problem_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Coding problem not found")

        supabase_client.table("coding_problems").update({"is_active": True}).eq("id", problem_id).execute()
        return {"status": "activated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/problems/{problem_id}/deactivate")
def deactivate_coding_problem(problem_id: str, admin: AuthUser = Depends(require_admin)):
    """Deactivate a coding problem. Admin only."""
    try:
        existing = supabase_client.table("coding_problems").select("id").eq("id", problem_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Coding problem not found")

        supabase_client.table("coding_problems").update({"is_active": False}).eq("id", problem_id).execute()
        return {"status": "deactivated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/problems/{problem_id}")
def delete_coding_problem(problem_id: str, admin: AuthUser = Depends(require_admin)):
    """Delete a coding problem. Only if no submissions reference it. Admin only."""
    try:
        existing = supabase_client.table("coding_problems").select("id").eq("id", problem_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Coding problem not found")

        # Check for existing submissions
        subs = (
            supabase_client.table("coding_submissions")
            .select("id")
            .eq("problem_id", problem_id)
            .limit(1)
            .execute()
        )
        if subs.data:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete: problem has existing submissions. Deactivate instead.",
            )

        # Delete test cases first (CASCADE handles this, but be explicit)
        supabase_client.table("coding_test_cases").delete().eq("problem_id", problem_id).execute()
        supabase_client.table("coding_drafts").delete().eq("problem_id", problem_id).execute()
        supabase_client.table("coding_problems").delete().eq("id", problem_id).execute()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# TEST CASE MANAGEMENT
# ============================================================

@router.get("/problems/{problem_id}/tests")
def list_test_cases(
    problem_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """List all test cases for a problem. Admin only — sees both public and hidden."""
    try:
        existing = supabase_client.table("coding_problems").select("id").eq("id", problem_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Coding problem not found")

        response = (
            supabase_client.table("coding_test_cases")
            .select("*")
            .eq("problem_id", problem_id)
            .order("ordering")
            .execute()
        )
        return response.data or []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/problems/{problem_id}/tests", status_code=201)
def create_test_case(
    problem_id: str,
    payload: CodingTestCaseCreate,
    admin: AuthUser = Depends(require_admin),
):
    """Create a test case for a coding problem. Admin only."""
    try:
        existing = supabase_client.table("coding_problems").select("id").eq("id", problem_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Coding problem not found")

        result = supabase_client.table("coding_test_cases").insert({
            "problem_id": problem_id,
            "input": payload.input,
            "expected_output": payload.expected_output,
            "is_public": payload.is_public,
            "points": payload.points,
            "ordering": payload.ordering,
        }).execute()

        return result.data[0] if result.data else {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/tests/{test_id}")
def update_test_case(
    test_id: str,
    payload: CodingTestCaseUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Update a test case. Admin only."""
    try:
        existing = supabase_client.table("coding_test_cases").select("id").eq("id", test_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Test case not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        result = supabase_client.table("coding_test_cases").update(updates).eq("id", test_id).execute()
        return result.data[0] if result.data else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tests/{test_id}")
def delete_test_case(test_id: str, admin: AuthUser = Depends(require_admin)):
    """Delete a test case. Admin only."""
    try:
        existing = supabase_client.table("coding_test_cases").select("id").eq("id", test_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail="Test case not found")

        supabase_client.table("coding_test_cases").delete().eq("id", test_id).execute()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
