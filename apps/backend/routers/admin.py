from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import require_admin, AuthUser
from core.supabase import supabase_client
from schemas.assessment import (
    DomainCreate, DomainUpdate, MCQCreate, MCQUpdate,
    AssessmentConfigUpdate, AssessmentConfigUpdateHandsOn,
    VALID_SEMESTERS, SEMESTER_LABELS, AdminRemarkUpdate,
)

router = APIRouter(prefix="/admin", tags=["Admin"])

MAX_ADMIN_REMARK_LENGTH = 10_000


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


# ---------------------------------------------------------------------------
# Assessment submissions list (admin only)
# ---------------------------------------------------------------------------

# Valid sort fields and their database column equivalents
_VALID_SORTS = {
    "score": "score",
    "percentage": "percentage_computed",
    "submitted_at": "submitted_at",
    "name": "full_name",
}


@router.get("/assessments/submissions")
def list_submissions(
    admin: AuthUser = Depends(require_admin),
    semester: int = Query(None, description="Filter by semester: 1, 3, 5, or 7"),
    branch: str = Query(None, description="Filter by branch"),
    domain_id: str = Query(None, description="Filter by domain UUID"),
    search: str = Query(None, description="Search by name, email, or USN"),
    sort: str = Query("score", description="Sort field: score, percentage, submitted_at, name"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    limit: int = Query(200, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List all submitted/scored assessment attempts with candidate info.

    Admin only. Returns lightweight records (no question/answer data).
    Server-side sorting and filtering for 200+ candidate scalability.
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        # 1. Fetch submitted/scored attempts (admin_remark is admin-only and
        # only ever leaves the database through admin endpoints)
        attempts_resp = (
            supabase_client.table("assessment_attempts")
            .select("id, profile_id, domain_ids, total_questions, score, max_score, mcq_score, mcq_max_score, coding_score, coding_max_score, total_coding_problems, total_descriptive_questions, started_at, submitted_at, status, admin_remark")
            .in_("status", ["submitted", "scored", "reset"])
            .execute()
        )
        attempts = attempts_resp.data or []

        if not attempts:
            logger.warning("SUBMISSIONS DEBUG: No attempts found, returning empty list")
            return []

        # 2. Batch-fetch profiles and candidates
        profile_ids = list({a["profile_id"] for a in attempts})

        profiles_resp = (
            supabase_client.table("profiles")
            .select("id, full_name, email")
            .in_("id", profile_ids)
            .execute()
        )
        profile_map = {p["id"]: p for p in (profiles_resp.data or [])}

        candidates_resp = (
            supabase_client.table("candidates")
            .select("profile_id, usn, semester, branch")
            .in_("profile_id", profile_ids)
            .execute()
        )
        candidate_map = {c["profile_id"]: c for c in (candidates_resp.data or [])}

        # 3. Fetch all domain names (small table)
        domains_resp = (
            supabase_client.table("domains")
            .select("id, name")
            .execute()
        )
        domain_map = {d["id"]: d["name"] for d in (domains_resp.data or [])}

        # 4. Assemble records
        records = []
        for attempt in attempts:
            pid = attempt["profile_id"]
            profile = profile_map.get(pid, {})
            candidate = candidate_map.get(pid, {}
)

            score_val = attempt.get("score") or 0
            max_score_val = attempt.get("max_score") or 1
            percentage = round((score_val / max_score_val) * 100) if max_score_val > 0 else 0
            mcq_score = attempt.get("mcq_score") or 0
            mcq_max = attempt.get("mcq_max_score") or 0
            coding_score = attempt.get("coding_score") or 0
            coding_max = attempt.get("coding_max_score") or 0

            records.append({
                "attempt_id": attempt["id"],
                "candidate_name": profile.get("full_name", ""),
                "email": profile.get("email", ""),
                "usn": candidate.get("usn", ""),
                "branch": candidate.get("branch", ""),
                "semester": candidate.get("semester"),
                "domain_ids": attempt.get("domain_ids") or [],
                "domain_names": [domain_map.get(did, "") for did in (attempt.get("domain_ids") or [])],
                "score": score_val,
                "max_score": max_score_val,
                "percentage": percentage,
                "mcq_score": mcq_score,
                "mcq_max_score": mcq_max,
                "coding_score": coding_score,
                "coding_max_score": coding_max,
                "total_mcq_questions": attempt["total_questions"],
                "total_coding_problems": attempt.get("total_coding_problems") or 0,
                "total_descriptive_questions": attempt.get("total_descriptive_questions") or 0,
                "admin_remark": attempt.get("admin_remark"),
                "status": attempt.get("status"),
                "started_at": attempt.get("started_at"),
                "submitted_at": attempt.get("submitted_at"),
            })

        # 5. Apply filters
        if semester is not None:
            records = [r for r in records if r["semester"] == semester]

        if branch:
            branch_lower = branch.lower()
            records = [r for r in records if branch_lower in (r.get("branch") or "").lower()]

        if domain_id:
            records = [r for r in records if domain_id in (r.get("domain_ids") or [])]

        if search:
            search_lower = search.lower()
            records = [
                r for r in records
                if search_lower in (r.get("candidate_name") or "").lower()
                or search_lower in (r.get("email") or "").lower()
                or search_lower in (r.get("usn") or "").lower()
            ]

        # 6. Apply sorting
        sort_key = sort if sort in _VALID_SORTS else "score"
        reverse = order != "asc"

        if sort_key == "name":
            records.sort(key=lambda r: (r.get("candidate_name") or "").lower(), reverse=reverse)
        elif sort_key == "submitted_at":
            records.sort(key=lambda r: r.get("submitted_at") or "", reverse=reverse)
        elif sort_key == "percentage":
            records.sort(key=lambda r: r.get("percentage", 0), reverse=reverse)
        else:  # score
            records.sort(key=lambda r: r.get("score", 0), reverse=reverse)

        # 7. Apply pagination
        return records[offset:offset + limit]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Assessment results (admin only)
# ---------------------------------------------------------------------------

@router.get("/assessments/{attempt_id}/results")
def get_assessment_results(
    attempt_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Get complete assessment results for an attempt. Admin only."""
    try:
        # Fetch attempt
        attempt_resp = (
            supabase_client.table("assessment_attempts")
            .select("*")
            .eq("id", attempt_id)
            .execute()
        )

        if not attempt_resp.data:
            raise HTTPException(status_code=404, detail="Attempt not found")

        attempt = attempt_resp.data[0]

        # Fetch candidate profile
        profile_resp = (
            supabase_client.table("profiles")
            .select("id, full_name, email")
            .eq("id", attempt["profile_id"])
            .execute()
        )
        profile = profile_resp.data[0] if profile_resp.data else {}

        # Fetch candidate record for semester
        candidate_resp = (
            supabase_client.table("candidates")
            .select("usn, semester, branch")
            .eq("profile_id", attempt["profile_id"])
            .execute()
        )
        candidate = candidate_resp.data[0] if candidate_resp.data else {}

        # Fetch answers with correctness
        answers_resp = (
            supabase_client.table("assessment_answers")
            .select("question_id, selected_option, is_correct")
            .eq("attempt_id", attempt_id)
            .execute()
        )
        answers = answers_resp.data or []
        answers_map = {a["question_id"]: a for a in answers}

        # Count correct/incorrect/unanswered
        correct_count = sum(1 for a in answers if a.get("is_correct"))
        incorrect_count = sum(1 for a in answers if not a.get("is_correct") and a.get("selected_option"))
        unanswered_count = attempt["total_questions"] - len(answers)

        # Fetch questions with correct answers
        question_ids = attempt["selected_question_ids"]
        questions_resp = (
            supabase_client.table("mcq_questions")
            .select("id, domain_id, question_text, option_a, option_b, option_c, option_d, correct_option, explanation")
            .in_("id", question_ids)
            .execute()
        )
        q_map = {q["id"]: q for q in (questions_resp.data or [])}

        # Fetch domain names
        domains_resp = (
            supabase_client.table("domains")
            .select("id, name")
            .in_("id", attempt["domain_ids"])
            .execute()
        )
        domain_map = {d["id"]: d["name"] for d in (domains_resp.data or [])}

        # Build question-by-question results
        questions_with_answers = []
        for qid in question_ids:
            q = q_map.get(qid, {})
            a = answers_map.get(qid, {})
            questions_with_answers.append({
                "question_text": q.get("question_text", ""),
                "option_a": q.get("option_a", ""),
                "option_b": q.get("option_b", ""),
                "option_c": q.get("option_c", ""),
                "option_d": q.get("option_d", ""),
                "correct_option": q.get("correct_option", ""),
                "explanation": q.get("explanation"),
                "selected_option": a.get("selected_option"),
                "is_correct": a.get("is_correct", False),
                "domainName": domain_map.get(q.get("domain_id"), ""),
            })

        # coding_problems are global/domain-independent (domain_id was removed in
        # migration 007). Do NOT select domain_id from coding_problems. The MCQ
        # question domain context is already captured via `domain_map` above.
        coding_problem_ids = attempt.get("selected_coding_problem_ids") or []
        coding_problems_map = {}
        if coding_problem_ids:
            cp_resp = (
                supabase_client.table("coding_problems")
                .select("id, title")
                .in_("id", coding_problem_ids)
                .execute()
            )
            coding_problems_map = {p["id"]: p for p in (cp_resp.data or [])}

        max_score = attempt["max_score"] if attempt.get("max_score") else 1
        score = attempt.get("score", 0) if attempt.get("score") is not None else 0
        percentage = round((score / max_score) * 100) if max_score > 0 else 0
        mcq_score = attempt.get("mcq_score") or 0
        mcq_max = attempt.get("mcq_max_score") or 0
        coding_score = attempt.get("coding_score") or 0
        coding_max = attempt.get("coding_max_score") or 0

        # Fetch coding submissions for this attempt
        coding_subs_resp = (
            supabase_client.table("coding_submissions")
            .select("problem_id, language, source_code, status, score, max_score, tests_passed, tests_total, execution_time_ms")
            .eq("attempt_id", attempt_id)
            .execute()
        )
        coding_subs = coding_subs_resp.data or []

        # Build results for each frozen coding problem. A single submission must
        # never be reused for multiple problems: each problem_id in
        # selected_coding_problem_ids gets its own result entry, and only problems
        # that have at least one submission appear with submission data. Problems
        # with no submission contribute 0 points.
        sub_map = {s["problem_id"]: s for s in coding_subs}
        coding_results = []
        for pid in coding_problem_ids:
            sub = sub_map.get(pid)
            cp = coding_problems_map.get(pid, {})
            if sub:
                coding_results.append({
                    "problem_title": cp.get("title", ""),
                    "language": sub["language"],
                    "source_code": sub["source_code"],
                    "status": sub["status"],
                    "score": sub.get("score", 0),
                    "max_score": sub.get("max_score", 0),
                    "tests_passed": sub.get("tests_passed", 0),
                    "tests_total": sub.get("tests_total", 0),
                    "execution_time_ms": sub.get("execution_time_ms"),
                })

        # Descriptive questions + candidate answers. Questions are listed even
        # when unanswered (answer maps default to None) — admins must see what
        # was NOT answered too. answer_text/answered_at/image/word_limit mirror
        # the candidate payload conventions (snake_case).
        descriptive_results = []
        desc_ids = attempt.get("selected_descriptive_question_ids") or []
        if desc_ids:
            dq_resp = (
                supabase_client.table("descriptive_questions")
                .select("id, question_text, image_url, word_limit")
                .in_("id", desc_ids)
                .execute()
            )
            dq_map = {q["id"]: q for q in (dq_resp.data or [])}

            da_resp = (
                supabase_client.table("assessment_descriptive_answers")
                .select("question_id, answer_text, answered_at")
                .eq("attempt_id", attempt_id)
                .execute()
            )
            da_map = {a["question_id"]: a for a in (da_resp.data or [])}

            for qid in desc_ids:
                dq = dq_map.get(qid, {})
                da = da_map.get(qid, {})
                descriptive_results.append({
                    "question_id": qid,
                    "question_text": dq.get("question_text", ""),
                    "image_url": dq.get("image_url"),
                    "word_limit": dq.get("word_limit"),
                    "answer_text": da.get("answer_text"),
                    "answered_at": da.get("answered_at"),
                })

        # Hands-On challenge results. Every frozen challenge is listed, even
        # when not attempted (evidence "Not attempted"). expected_flag is
        # NEVER returned — admins see the candidate's submitted flag and the
        # backend's verification verdict, not the secret itself.
        hands_on_results = []
        hands_ids = attempt.get("selected_hands_on_question_ids") or []
        if hands_ids:
            hq_resp = (
                supabase_client.table("hands_on_questions")
                .select("id, title, difficulty, points, challenge_type")
                .in_("id", hands_ids)
                .execute()
            )
            hq_map = {q["id"]: q for q in (hq_resp.data or [])}

            hr_resp = (
                supabase_client.table("assessment_hands_on_results")
                .select("question_id, submitted_input, submitted_flag, verified, score, started_at, completed_at")
                .eq("attempt_id", attempt_id)
                .execute()
            )
            hr_map = {r["question_id"]: r for r in (hr_resp.data or [])}

            for qid in hands_ids:
                hq = hq_map.get(qid, {})
                hr = hr_map.get(qid, {})
                attempted = bool(hr) and (hr.get("submitted_input") or hr.get("submitted_flag"))
                hands_on_results.append({
                    "question_id": qid,
                    "title": hq.get("title", ""),
                    "challenge_type": hq.get("challenge_type", ""),
                    "difficulty": hq.get("difficulty", ""),
                    "points": hq.get("points", 0),
                    "submitted_input": hr.get("submitted_input") if hr else None,
                    "submitted_flag": hr.get("submitted_flag") if hr else None,
                    "verified": bool(hr.get("verified")) if hr else False,
                    "score": hr.get("score") if hr else None,
                    "started_at": hr.get("started_at") if hr else None,
                    "completed_at": hr.get("completed_at") if hr else None,
                    "attempted": attempted,
                })

        return {
            "attempt_id": attempt_id,
            "status": attempt["status"],
            "candidate": {
                "profile_id": attempt["profile_id"],
                "full_name": profile.get("full_name", ""),
                "email": profile.get("email", ""),
                "usn": candidate.get("usn", ""),
                "semester": candidate.get("semester"),
                "semester_label": SEMESTER_LABELS.get(candidate.get("semester"), "Unknown"),
                "branch": candidate.get("branch", ""),
            },
            "domain_ids": attempt["domain_ids"],
            "domain_names": [domain_map.get(did, "") for did in attempt["domain_ids"]],
            "total_mcq_questions": attempt["total_questions"],
            "total_coding_problems": attempt.get("total_coding_problems") or 0,
            "total_descriptive_questions": attempt.get("total_descriptive_questions") or 0,
            "descriptive_results": descriptive_results,
            "total_hands_on_questions": attempt.get("total_hands_on_questions") or 0,
            "hands_on_results": hands_on_results,
            "hands_on_score": attempt.get("hands_on_score") or 0,
            "hands_on_max_score": attempt.get("hands_on_max_score") or 0,
            "duration_minutes": attempt["duration_minutes"],
            "started_at": attempt["started_at"],
            "submitted_at": attempt.get("submitted_at"),
            "expires_at": attempt.get("expires_at"),
            "score": score,
            "max_score": max_score,
            "percentage": percentage,
            "mcq_score": mcq_score,
            "mcq_max_score": mcq_max,
            "coding_score": coding_score,
            "coding_max_score": coding_max,
            "correct_count": correct_count,
            "incorrect_count": incorrect_count,
            "unanswered_count": unanswered_count,
            "mcq_questions": questions_with_answers,
            "coding_results": coding_results,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Assessment configuration management
# ---------------------------------------------------------------------------

@router.get("/config")
def list_config(admin: AuthUser = Depends(require_admin)):
    """List all assessment configurations. Admin only."""
    try:
        result = (
            supabase_client.table("assessment_config")
            .select("*")
            .order("created_at")
            .execute()
        )
        return result.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config/{config_id}")
def update_config(
    config_id: str,
    payload: AssessmentConfigUpdateHandsOn,
    admin: AuthUser = Depends(require_admin),
):
    """Update an assessment configuration. Admin only."""
    try:
        existing = (
            supabase_client.table("assessment_config")
            .select("id")
            .eq("id", config_id)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Configuration not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Validate configuration consistency
        if any(k in updates for k in ("total_questions", "coding_problem_count", "max_domains")):
            current = (
                supabase_client.table("assessment_config")
                .select("total_questions, coding_problem_count, max_domains")
                .eq("id", config_id)
                .execute()
            )
            if current.data:
                cur = current.data[0]
                tq = updates.get("total_questions", cur["total_questions"])
                cc = updates.get("coding_problem_count", cur.get("coding_problem_count", 0))
                md = updates.get("max_domains", cur["max_domains"])
                if md > 2:
                    raise HTTPException(status_code=400, detail="max_domains cannot exceed 2")
                if md == 2 and tq % 2 != 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"total_questions ({tq}) must be even when max_domains is 2",
                    )
                if md == 2 and cc % 2 != 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"coding_problem_count ({cc}) must be even when max_domains is 2",
                    )

        # If this config is being activated, deactivate all other configs first.
        # The DB partial unique index enforces at most one active config,
        # so we must clear others before setting this one active.
        if updates.get("is_active") is True:
            (
                supabase_client.table("assessment_config")
                .update({"is_active": False})
                .neq("id", config_id)
                .eq("is_active", True)
                .execute()
            )

        result = (
            supabase_client.table("assessment_config")
            .update(updates)
            .eq("id", config_id)
            .execute()
        )
        return result.data[0] if result.data else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Assessment bulk operations (admin only)
# ---------------------------------------------------------------------------

@router.post("/assessments/reset-all")
def reset_all_assessments(admin: AuthUser = Depends(require_admin)):
    """Reset ALL assessment attempts. Sets status to 'reset' for every attempt.

    Preserves all historical data. Candidates can start new assessments.
    """
    try:
        # Cancel any in_progress attempts first
        active_resp = (
            supabase_client.table("assessment_attempts")
            .select("id")
            .eq("status", "in_progress")
            .execute()
        )
        if active_resp.data:
            from routers.assessment import _score_attempt
            for act in active_resp.data:
                _score_attempt(act["id"])

        # Set all attempts to 'reset'
        result = (
            supabase_client.table("assessment_attempts")
            .update({"status": "reset"})
            .neq("status", "reset")
            .execute()
        )

        # Count all attempts that are now reset
        count_resp = (
            supabase_client.table("assessment_attempts")
            .select("id", count="exact")
            .execute()
        )
        total = len(count_resp.data) if count_resp.data else 0

        return {
            "status": "reset_all",
            "reset_count": total,
            "message": f"All {total} assessment attempts have been reset.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/assessments/all")
def delete_all_assessments(admin: AuthUser = Depends(require_admin)):
    """Delete ALL assessment attempts and their associated data.

    Uses ON DELETE CASCADE to remove child records:
    - assessment_answers
    - coding_submissions
    - coding_drafts

    Does NOT delete: users, profiles, domains, MCQs, coding problems,
    coding test cases, assessment configuration.
    """
    try:
        # Count attempts before deletion
        count_resp = (
            supabase_client.table("assessment_attempts")
            .select("id", count="exact")
            .execute()
        )
        total = len(count_resp.data) if count_resp.data else 0

        if total == 0:
            return {
                "status": "deleted_all",
                "deleted_count": 0,
                "message": "No assessment attempts to delete.",
            }

        # Delete all attempts — CASCADE removes child records
        supabase_client.table("assessment_attempts").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

        return {
            "status": "deleted_all",
            "deleted_count": total,
            "message": f"All {total} assessment attempts and associated data have been deleted.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Assessment individual operations (admin only)
# ---------------------------------------------------------------------------

@router.post("/assessments/{attempt_id}/reset")
def reset_assessment(
    attempt_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Reset a candidate's assessment so they can retake.

    Does NOT delete the previous attempt — it remains as historical data.
    If the candidate has an active in_progress attempt, it is cancelled (scored).
    After reset, the candidate can start a new assessment.
    """
    try:
        attempt_resp = (
            supabase_client.table("assessment_attempts")
            .select("id, profile_id, status")
            .eq("id", attempt_id)
            .execute()
        )
        if not attempt_resp.data:
            raise HTTPException(status_code=404, detail="Attempt not found")

        attempt = attempt_resp.data[0]
        profile_id = attempt["profile_id"]

        # Cancel any active in_progress attempt for this candidate
        active = (
            supabase_client.table("assessment_attempts")
            .select("id")
            .eq("profile_id", profile_id)
            .eq("status", "in_progress")
            .execute()
        )
        if active.data:
            from routers.assessment import _score_attempt
            for act in active.data:
                _score_attempt(act["id"])

        # Mark the submitted attempt as "reset" so it's historical but not blocking
        # We keep the original status but add a note via the submitted_at timestamp
        # The key insight: we just need the candidate to be able to start a new one.
        # The simplest approach: change status to "reset" for the specific attempt.
        supabase_client.table("assessment_attempts").update(
            {"status": "reset"}
        ).eq("id", attempt_id).execute()

        # Hands-On: clear the challenge result on the reset attempt (evidence,
        # flag, verification, score, timestamps) so a retake starts clean. The
        # shared challenge server keeps running — nothing container-like to
        # tear down. Challenge rows and the static expected flag are untouched.
        supabase_client.table("assessment_hands_on_results").delete().eq(
            "attempt_id", attempt_id
        ).execute()

        return {
            "status": "reset",
            "attempt_id": attempt_id,
            "candidate_profile_id": profile_id,
            "message": "Candidate can now start a new assessment. Previous attempt preserved.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/assessments/{attempt_id}")
def delete_assessment(
    attempt_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Delete a specific assessment attempt and all associated data.

    Uses ON DELETE CASCADE to remove child records:
    - assessment_answers
    - coding_submissions
    - coding_drafts

    Does NOT delete: users, profiles, domains, MCQs, coding problems,
    coding test cases, assessment configuration.
    """
    try:
        attempt_resp = (
            supabase_client.table("assessment_attempts")
            .select("id, profile_id")
            .eq("id", attempt_id)
            .execute()
        )
        if not attempt_resp.data:
            raise HTTPException(status_code=404, detail="Attempt not found")

        # Delete the attempt — CASCADE removes child records
        supabase_client.table("assessment_attempts").delete().eq("id", attempt_id).execute()

        return {
            "status": "deleted",
            "attempt_id": attempt_id,
            "message": "Assessment attempt and all associated data have been deleted.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Assessment submission remark (admin only)
# ---------------------------------------------------------------------------
# One private administrative note per attempt, stored directly on the
# canonical submission record (assessment_attempts.admin_remark).
#
# Security model:
#   - require_admin dependency enforces profiles.is_admin on every call.
#   - These endpoints live under the /admin prefix — candidate routers never
#     select admin_remark, so the value can only leave the database here.
#   - Writes go through FastAPI using service_role (bypasses RLS), matching
#     the existing pattern; RLS adds defense-in-depth (see migration 011).


def _verify_attempt_exists(attempt_id: str) -> dict:
    """Fetch an attempt or raise 404. Shared by the remark endpoints."""
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("id, profile_id")
        .eq("id", attempt_id)
        .execute()
    )
    if not attempt_resp.data:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt_resp.data[0]


@router.get("/assessments/{attempt_id}/remark")
def get_admin_remark(
    attempt_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Get the private admin remark for an assessment submission. Admin only."""
    try:
        _verify_attempt_exists(attempt_id)

        resp = (
            supabase_client.table("assessment_attempts")
            .select("id, admin_remark")
            .eq("id", attempt_id)
            .execute()
        )
        return {
            "attempt_id": attempt_id,
            "admin_remark": resp.data[0].get("admin_remark") if resp.data else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/assessments/{attempt_id}/remark")
def set_admin_remark(
    attempt_id: str,
    payload: AdminRemarkUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Create or update the private admin remark for a submission. Admin only.

    Empty/whitespace-only remark is stored as NULL (cleared).
    """
    try:
        _verify_attempt_exists(attempt_id)

        remark = payload.admin_remark.strip() if payload.admin_remark else None
        if remark == "":
            remark = None  # whitespace-only → cleared

        if remark is not None and len(remark) > MAX_ADMIN_REMARK_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Remark too long (max {MAX_ADMIN_REMARK_LENGTH} characters)",
            )

        result = (
            supabase_client.table("assessment_attempts")
            .update({"admin_remark": remark})
            .eq("id", attempt_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Attempt not found")

        return {
            "attempt_id": attempt_id,
            "admin_remark": result.data[0].get("admin_remark"),
            "status": "saved",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/assessments/{attempt_id}/remark")
def clear_admin_remark(
    attempt_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Clear (delete) the private admin remark for a submission. Admin only."""
    try:
        _verify_attempt_exists(attempt_id)

        result = (
            supabase_client.table("assessment_attempts")
            .update({"admin_remark": None})
            .eq("id", attempt_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Attempt not found")

        return {
            "attempt_id": attempt_id,
            "admin_remark": None,
            "status": "cleared",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
