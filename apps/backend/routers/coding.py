"""
Candidate-facing coding endpoints within the shared assessment attempt.

All endpoints:
- Reference the ONE shared assessment_attempts.id
- Enforce ownership, expiry, in_progress status
- Never expose hidden test cases
- Use the shared attempt's selected_coding_problem_ids
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user, AuthUser
from core.supabase import supabase_client
from schemas.coding import CodingSubmitRequest, CodingDraftSaveRequest, CodingRunRequest
from services.code_executor import run_code_public, evaluate_submission

router = APIRouter(prefix="/coding", tags=["Coding Assessment"])


def _utcnow():
    return datetime.now(timezone.utc)


def _is_expired(attempt: dict) -> bool:
    expires_at = attempt.get("expires_at")
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return _utcnow() > expires_at


def _verify_attempt_ownership(attempt_id: str, user_id: str) -> dict:
    """Verify attempt exists, is owned by user, is in_progress, and not expired."""
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("id, profile_id, status, expires_at, selected_coding_problem_ids")
        .eq("id", attempt_id)
        .execute()
    )
    if not attempt_resp.data:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt = attempt_resp.data[0]
    if attempt["profile_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Attempt is not in progress")
    if _is_expired(attempt):
        raise HTTPException(status_code=400, detail="Assessment time has expired")

    return attempt


# ============================================================

@router.get("/attempt/{attempt_id}/problems")
def get_coding_problems(
    attempt_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Get coding problems for the shared attempt. Only PUBLIC test cases are sent."""
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("id, profile_id, status, domain_ids, selected_coding_problem_ids, total_coding_problems, duration_minutes, started_at, expires_at")
        .eq("id", attempt_id)
        .execute()
    )
    if not attempt_resp.data:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt = attempt_resp.data[0]
    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Attempt is not in progress")
    if _is_expired(attempt):
        raise HTTPException(status_code=400, detail="Assessment time has expired")

    problem_ids = attempt.get("selected_coding_problem_ids") or []
    if not problem_ids:
        return {"attempt_id": attempt_id, "problems": [], "expires_at": attempt.get("expires_at")}

    # Fetch problems (safe columns only — problems are global)
    problems_resp = (
        supabase_client.table("coding_problems")
        .select(
            "id, title, slug, description, difficulty, constraints, "
            "input_format, output_format, explanation, starter_code, "
            "supported_languages, time_limit_ms, memory_limit_mb, points, "
            "function_name, class_name, function_signature"
        )
        .in_("id", problem_ids)
        .execute()
    )
    problem_map = {p["id"]: p for p in (problems_resp.data or [])}
    ordered = [problem_map[pid] for pid in problem_ids if pid in problem_map]

    # PUBLIC test cases only (with arguments for function-based display)
    for p in ordered:
        tests_resp = (
            supabase_client.table("coding_test_cases")
            .select("id, arguments, expected_output, ordering, points, input")
            .eq("problem_id", p["id"])
            .eq("is_public", True)
            .order("ordering")
            .execute()
        )
        p["test_cases"] = tests_resp.data or []

    # Submission status (no scoring data exposed to candidate)
    subs_resp = (
        supabase_client.table("coding_submissions")
        .select("problem_id, status")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    subs_map = {s["problem_id"]: s for s in (subs_resp.data or [])}
    for p in ordered:
        sub = subs_map.get(p["id"])
        p["submission_status"] = sub["status"] if sub else None

    # Drafts
    drafts_resp = (
        supabase_client.table("coding_drafts")
        .select("problem_id, language, source_code, updated_at")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    drafts_map = {d["problem_id"]: d for d in (drafts_resp.data or [])}
    for p in ordered:
        draft = drafts_map.get(p["id"])
        p["draft"] = {
            "language": draft["language"],
            "source_code": draft["source_code"],
        } if draft else None

    return {
        "attempt_id": attempt_id,
        "total_coding_problems": attempt.get("total_coding_problems", 0),
        "duration_minutes": attempt.get("duration_minutes"),
        "expires_at": attempt.get("expires_at"),
        "problems": ordered,
    }


# ============================================================

@router.put("/attempt/{attempt_id}/draft")
def save_draft(
    attempt_id: str,
    payload: CodingDraftSaveRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Autosave code draft. Does NOT count as submission."""
    attempt = _verify_attempt_ownership(attempt_id, current_user.id)

    problem_ids = attempt.get("selected_coding_problem_ids") or []
    if payload.problem_id not in problem_ids:
        raise HTTPException(status_code=400, detail="Problem not part of this attempt")

    existing = (
        supabase_client.table("coding_drafts")
        .select("id")
        .eq("attempt_id", attempt_id)
        .eq("problem_id", payload.problem_id)
        .execute()
    )

    now = _utcnow().isoformat()
    if existing.data:
        supabase_client.table("coding_drafts").update({
            "language": payload.language,
            "source_code": payload.source_code,
            "updated_at": now,
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase_client.table("coding_drafts").insert({
            "attempt_id": attempt_id,
            "problem_id": payload.problem_id,
            "language": payload.language,
            "source_code": payload.source_code,
        }).execute()

    return {"status": "saved"}


@router.get("/attempt/{attempt_id}/draft/{problem_id}")
def get_draft(
    attempt_id: str,
    problem_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Get saved draft for a specific problem."""
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("id, profile_id, selected_coding_problem_ids")
        .eq("id", attempt_id)
        .execute()
    )
    if not attempt_resp.data:
        raise HTTPException(status_code=404, detail="Attempt not found")
    attempt = attempt_resp.data[0]
    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if problem_id not in (attempt.get("selected_coding_problem_ids") or []):
        raise HTTPException(status_code=400, detail="Problem not part of this attempt")

    draft_resp = (
        supabase_client.table("coding_drafts")
        .select("language, source_code, updated_at")
        .eq("attempt_id", attempt_id)
        .eq("problem_id", problem_id)
        .execute()
    )
    if not draft_resp.data:
        return {"language": None, "source_code": ""}

    return draft_resp.data[0]


# ============================================================

@router.post("/attempt/{attempt_id}/run")
def run_code(
    attempt_id: str,
    payload: CodingRunRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Run code against PUBLIC test cases only (browser feedback, never scored)."""
    attempt = _verify_attempt_ownership(attempt_id, current_user.id)

    if payload.problem_id not in (attempt.get("selected_coding_problem_ids") or []):
        raise HTTPException(status_code=400, detail="Problem not part of this attempt")

    tests_resp = (
        supabase_client.table("coding_test_cases")
        .select("id, arguments, expected_output, is_public, ordering, input")
        .eq("problem_id", payload.problem_id)
        .eq("is_public", True)
        .order("ordering")
        .execute()
    )
    test_cases = tests_resp.data or []
    if not test_cases:
        return {"all_passed": True, "results": [], "message": "No public test cases"}

    problem_resp = (
        supabase_client.table("coding_problems")
        .select("time_limit_ms, memory_limit_mb, function_name, class_name, function_signature")
        .eq("id", payload.problem_id)
        .execute()
    )
    problem = problem_resp.data[0] if problem_resp.data else {}

    return run_code_public(
        payload.source_code,
        payload.language,
        test_cases,
        time_limit_ms=problem.get("time_limit_ms", 2000),
        memory_limit_mb=problem.get("memory_limit_mb", 256),
        attempt_id=attempt_id,
        problem_id=payload.problem_id,
        function_name=problem.get("function_name", "solve"),
        class_name=problem.get("class_name"),
        function_signature=problem.get("function_signature"),
    )


# ============================================================

@router.post("/attempt/{attempt_id}/submit")
def submit_coding_solution(
    attempt_id: str,
    payload: CodingSubmitRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Submit one coding problem solution for server-side evaluation.

    Evaluates against ALL test cases (public + hidden).
    Score is computed server-side only.
    """
    attempt = _verify_attempt_ownership(attempt_id, current_user.id)

    if payload.problem_id not in (attempt.get("selected_coding_problem_ids") or []):
        raise HTTPException(status_code=400, detail="Problem not part of this attempt")

    # ALL test cases (public + hidden)
    tests_resp = (
        supabase_client.table("coding_test_cases")
        .select("id, arguments, expected_output, is_public, points, ordering, input")
        .eq("problem_id", payload.problem_id)
        .order("ordering")
        .execute()
    )
    test_cases = tests_resp.data or []
    if not test_cases:
        raise HTTPException(status_code=400, detail="No test cases configured")

    problem_resp = (
        supabase_client.table("coding_problems")
        .select("time_limit_ms, memory_limit_mb, function_name, class_name, function_signature")
        .eq("id", payload.problem_id)
        .execute()
    )
    problem = problem_resp.data[0] if problem_resp.data else {}

    eval_result = evaluate_submission(
        payload.source_code,
        payload.language,
        test_cases,
        time_limit_ms=problem.get("time_limit_ms", 2000),
        memory_limit_mb=problem.get("memory_limit_mb", 256),
        attempt_id=attempt_id,
        problem_id=payload.problem_id,
        function_name=problem.get("function_name", "solve"),
        class_name=problem.get("class_name"),
        function_signature=problem.get("function_signature"),
    )

    if eval_result["tests_passed"] == eval_result["tests_total"]:
        status = "passed"
    elif eval_result["tests_passed"] > 0:
        status = "failed"
    elif any(tr["status"] == "compile_error" for tr in eval_result.get("test_results", [])):
        status = "error"
    elif any(tr["status"] == "timeout" for tr in eval_result.get("test_results", [])):
        status = "timeout"
    else:
        status = "failed"

    existing = (
        supabase_client.table("coding_submissions")
        .select("id")
        .eq("attempt_id", attempt_id)
        .eq("problem_id", payload.problem_id)
        .execute()
    )

    sub_data = {
        "attempt_id": attempt_id,
        "problem_id": payload.problem_id,
        "language": payload.language,
        "source_code": payload.source_code,
        "status": status,
        "score": eval_result["score"],
        "max_score": eval_result["max_score"],
        "tests_passed": eval_result["tests_passed"],
        "tests_total": eval_result["tests_total"],
        "execution_time_ms": eval_result["execution_time_ms"],
    }

    if existing.data:
        supabase_client.table("coding_submissions").update(sub_data).eq("id", existing.data[0]["id"]).execute()
        submission_id = existing.data[0]["id"]
    else:
        result = supabase_client.table("coding_submissions").insert(sub_data).execute()
        submission_id = result.data[0]["id"] if result.data else None

    # Clean up draft
    supabase_client.table("coding_drafts").delete().eq("attempt_id", attempt_id).eq("problem_id", payload.problem_id).execute()

    # Do NOT return score/max_score/tests_passed/tests_total to the candidate.
    # The server stores all scoring data; candidates only see submission status.
    return {
        "status": status,
        "submission_id": submission_id,
    }
