"""
Combined Assessment Router

ONE assessment attempt contains BOTH:
- MCQ section (frozen question IDs in selected_question_ids)
- Coding section (frozen problem IDs in selected_coding_problem_ids)

ONE timer (expires_at), ONE final submission, ONE combined score.
"""

import random
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user, AuthUser
from core.supabase import supabase_client
from schemas.assessment import AssessmentStartRequest, AnswerSaveRequest

router = APIRouter(prefix="/assessment", tags=["Assessment"])


# ---------------------------------------------------------------------------

def _get_active_config() -> dict:
    """Read the active assessment configuration."""
    result = (
        supabase_client.table("assessment_config")
        .select("*")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=500,
            detail="No active assessment configuration found. Contact an admin.",
        )
    return result.data[0]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(attempt: dict) -> bool:
    expires_at = attempt.get("expires_at")
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return _utcnow() > expires_at


# ---------------------------------------------------------------------------

def _score_mcq(attempt_id: str) -> dict:
    """Score the MCQ section of an attempt. Returns {score, max_score}."""
    answers_resp = (
        supabase_client.table("assessment_answers")
        .select("id, question_id, selected_option")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    answers = answers_resp.data or []

    question_ids = [a["question_id"] for a in answers]
    if not question_ids:
        supabase_client.table("assessment_attempts").update(
            {"mcq_score": 0, "mcq_max_score": 0}
        ).eq("id", attempt_id).execute()
        return {"score": 0, "max_score": 0}

    questions_resp = (
        supabase_client.table("mcq_questions")
        .select("id, correct_option")
        .in_("id", question_ids)
        .execute()
    )
    correct_map = {q["id"]: q["correct_option"] for q in (questions_resp.data or [])}

    score = 0
    for answer in answers:
        is_correct = answer["selected_option"] == correct_map.get(answer["question_id"])
        if is_correct:
            score += 1
        supabase_client.table("assessment_answers").update(
            {"is_correct": is_correct}
        ).eq("id", answer["id"]).execute()

    max_score = len(answers)

    # Also compute the total possible from selected_question_ids
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("selected_question_ids")
        .eq("id", attempt_id)
        .execute()
    )
    total_possible = len((attempt_resp.data or [{}])[0].get("selected_question_ids") or [])

    supabase_client.table("assessment_attempts").update(
        {"mcq_score": score, "mcq_max_score": total_possible}
    ).eq("id", attempt_id).execute()

    return {"score": score, "max_score": total_possible}


def _score_coding(attempt_id: str) -> dict:
    """Score the coding section of an attempt. Returns {score, max_score}.

    Each problem in selected_coding_problem_ids is scored independently:
    - If the candidate submitted a passing solution, that problem earns its points.
    - If no submission exists or the submission did not pass, the problem earns 0.
    One problem's submission/result is NEVER copied to another problem.
    """
    # Fetch the frozen problem list for this attempt
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("selected_coding_problem_ids")
        .eq("id", attempt_id)
        .execute()
    )
    problem_ids = (attempt_resp.data or [{}])[0].get("selected_coding_problem_ids") or []

    # Fetch problem points for each selected problem
    problem_points = {}
    if problem_ids:
        probs_resp = (
            supabase_client.table("coding_problems")
            .select("id, points")
            .in_("id", problem_ids)
            .execute()
        )
        problem_points = {p["id"]: p.get("points", 10) for p in (probs_resp.data or [])}

    # Fetch all submissions for this attempt
    subs_resp = (
        supabase_client.table("coding_submissions")
        .select("problem_id, score, max_score, status")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    submissions = subs_resp.data or []

    # Build a map: problem_id -> best passing submission score
    # Only "passed" submissions count. Non-passing submissions earn 0.
    sub_map = {}
    for sub in submissions:
        pid = sub["problem_id"]
        if sub.get("status") == "passed" and pid not in sub_map:
            sub_map[pid] = sub.get("score", 0)

    total_score = 0
    total_max = 0
    for pid in problem_ids:
        points = problem_points.get(pid, 10)
        total_max += points
        total_score += sub_map.get(pid, 0)

    supabase_client.table("assessment_attempts").update(
        {"coding_score": total_score, "coding_max_score": total_max}
    ).eq("id", attempt_id).execute()

    return {"score": total_score, "max_score": total_max}


def _score_attempt(attempt_id: str) -> dict:
    """Score the combined attempt. Returns overall result (not exposed to candidate)."""
    mcq = _score_mcq(attempt_id)
    coding = _score_coding(attempt_id)

    # Combined score: simple sum (MCQ + Coding)
    # Both use raw points, no weighting — straightforward total
    overall_score = mcq["score"] + coding["score"]
    overall_max = mcq["max_score"] + coding["max_score"]

    supabase_client.table("assessment_attempts").update({
        "status": "scored",
        "submitted_at": _utcnow().isoformat(),
        "score": overall_score,
        "max_score": overall_max if overall_max > 0 else 1,
    }).eq("id", attempt_id).execute()

    return {
        "score": overall_score,
        "max_score": overall_max,
        "mcq_score": mcq["score"],
        "mcq_max_score": mcq["max_score"],
        "coding_score": coding["score"],
        "coding_max_score": coding["max_score"],
    }


# ---------------------------------------------------------------------------

def _select_coding_problems(
    coding_problem_count: int,
) -> list[str]:
    """Select coding problems from the GLOBAL active problem pool.

    Coding problems are domain-independent.
    Selection ignores the candidate's chosen domains entirely.
    """
    if coding_problem_count == 0:
        return []

    q_resp = (
        supabase_client.table("coding_problems")
        .select("id")
        .eq("is_active", True)
        .execute()
    )
    available = q_resp.data or []
    if len(available) < coding_problem_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only {len(available)} active coding problems available, "
                f"need {coding_problem_count}"
            ),
        )
    sampled = random.sample(available, coding_problem_count)
    return [p["id"] for p in sampled]


# ---------------------------------------------------------------------------

@router.post("/start")
def start_assessment(
    payload: AssessmentStartRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Start ONE combined assessment with MCQ + Coding sections.

    Selects MCQ questions AND coding problems, freezes both in ONE attempt.
    """
    profile_id = current_user.id

    # 1. Read config
    config = _get_active_config()
    total_mcq = config["total_questions"]
    coding_problem_count = config.get("coding_problem_count", 0)
    duration_minutes = config["duration_minutes"]
    max_domains = config["max_domains"]

    # 2. Verify candidate
    profile = (
        supabase_client.table("profiles")
        .select("id")
        .eq("id", profile_id)
        .execute()
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    candidate = (
        supabase_client.table("candidates")
        .select("id, semester")
        .eq("profile_id", profile_id)
        .execute()
    )
    if not candidate.data:
        raise HTTPException(status_code=404, detail="Candidate record not found")

    candidate_semester = candidate.data[0]["semester"]

    # 3. Check existing in_progress attempt → RESUME it
    existing = (
        supabase_client.table("assessment_attempts")
        .select("id, expires_at, status")
        .eq("profile_id", profile_id)
        .eq("status", "in_progress")
        .execute()
    )
    if existing.data:
        attempt_id = existing.data[0]["id"]
        attempt_resp = (
            supabase_client.table("assessment_attempts")
            .select("*")
            .eq("id", attempt_id)
            .execute()
        )
        if attempt_resp.data and _is_expired(attempt_resp.data[0]):
            _score_attempt(attempt_id)
            # After auto-scoring, fall through to check if a new start is allowed
        else:
            # Active attempt exists and is not expired — resume it
            attempt = attempt_resp.data[0]
            return {
                "attempt_id": attempt["id"],
                "total_mcq_questions": attempt["total_questions"],
                "total_coding_problems": attempt.get("total_coding_problems", 0),
                "duration_minutes": attempt["duration_minutes"],
                "domain_ids": attempt.get("domain_ids", []),
                "expires_at": attempt["expires_at"],
                "resumed": True,
            }

    # 3b. Check if candidate has a submitted/scored attempt — BLOCK new start
    submitted = (
        supabase_client.table("assessment_attempts")
        .select("id, status")
        .eq("profile_id", profile_id)
        .in_("status", ["submitted", "scored"])
        .execute()
    )
    if submitted.data:
        raise HTTPException(
            status_code=409,
            detail="You have already completed an assessment. Contact an admin to retake.",
        )

    # 4. Validate domains
    domain_ids = payload.domain_ids
    if len(domain_ids) < 1 or len(domain_ids) > max_domains:
        raise HTTPException(
            status_code=400,
            detail=f"Select between 1 and {max_domains} domains",
        )

    domains_resp = (
        supabase_client.table("domains")
        .select("id, name, duration_minutes, is_active")
        .in_("id", domain_ids)
        .execute()
    )
    if not domains_resp.data or len(domains_resp.data) != len(domain_ids):
        raise HTTPException(status_code=400, detail="One or more domains not found")

    active_domains = [d for d in domains_resp.data if d["is_active"]]
    if len(active_domains) != len(domain_ids):
        raise HTTPException(status_code=400, detail="One or more selected domains are inactive")

    # 5. Select MCQ questions
    num_domains = len(domain_ids)
    if num_domains == 1:
        mcq_per_domain = total_mcq
    else:
        if total_mcq % 2 != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Total MCQ questions ({total_mcq}) must be even for 2-domain split",
            )
        mcq_per_domain = total_mcq // 2

    selected_question_ids = []
    for domain in active_domains:
        q_resp = (
            supabase_client.table("mcq_questions")
            .select("id")
            .eq("domain_id", domain["id"])
            .eq("semester", candidate_semester)
            .eq("is_active", True)
            .execute()
        )
        available = q_resp.data or []
        if len(available) < mcq_per_domain:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Domain '{domain['name']}' (Semester {candidate_semester}) "
                    f"has only {len(available)} active MCQ questions, need {mcq_per_domain}"
                ),
            )
        sampled = random.sample(available, mcq_per_domain)
        selected_question_ids.extend([q["id"] for q in sampled])

    random.shuffle(selected_question_ids)

    # 6. Select coding problems (from global pool, independent of domains)
    selected_coding_ids = _select_coding_problems(
        coding_problem_count
    )

    # 7. Create ONE combined attempt
    now = _utcnow()
    expires_at = now + timedelta(minutes=duration_minutes)

    result = supabase_client.table("assessment_attempts").insert({
        "profile_id": profile_id,
        "status": "in_progress",
        "domain_ids": domain_ids,
        "selected_question_ids": selected_question_ids,
        "total_questions": len(selected_question_ids),
        "selected_coding_problem_ids": selected_coding_ids,
        "total_coding_problems": len(selected_coding_ids),
        "duration_minutes": duration_minutes,
        "started_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }).execute()

    attempt = result.data[0] if result.data else None
    if not attempt:
        raise HTTPException(status_code=500, detail="Failed to create attempt")

    return {
        "attempt_id": attempt["id"],
        "total_mcq_questions": attempt["total_questions"],
        "total_coding_problems": attempt["total_coding_problems"],
        "duration_minutes": attempt["duration_minutes"],
        "domain_ids": domain_ids,
        "expires_at": attempt["expires_at"],
    }


# ---------------------------------------------------------------------------

@router.get("/current")
def get_current_attempt(current_user: AuthUser = Depends(get_current_user)):
    """Get the candidate's most recent in-progress attempt (combined MCQ+Coding)."""
    result = (
        supabase_client.table("assessment_attempts")
        .select(
            "id, profile_id, status, domain_ids, selected_question_ids, total_questions, "
            "selected_coding_problem_ids, total_coding_problems, "
            "duration_minutes, started_at, expires_at, submitted_at, created_at"
        )
        .eq("profile_id", current_user.id)
        .eq("status", "in_progress")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="No active attempt")

    attempt = result.data[0]
    if _is_expired(attempt):
        _score_attempt(attempt["id"])
        attempt["status"] = "scored"

    return attempt


@router.get("/attempt/{attempt_id}")
def get_attempt(attempt_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Get attempt details (no scoring data for candidates)."""
    result = (
        supabase_client.table("assessment_attempts")
        .select(
            "id, profile_id, status, domain_ids, selected_question_ids, total_questions, "
            "selected_coding_problem_ids, total_coding_problems, "
            "duration_minutes, started_at, expires_at, submitted_at, created_at"
        )
        .eq("id", attempt_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt = result.data[0]
    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if attempt["status"] == "in_progress" and _is_expired(attempt):
        _score_attempt(attempt_id)
        attempt["status"] = "scored"

    return attempt


# ---------------------------------------------------------------------------

@router.get("/attempt/{attempt_id}/questions")
def get_attempt_questions(
    attempt_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Get MCQ questions for the attempt. Correct answers are NEVER sent."""
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("*")
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
        _score_attempt(attempt_id)
        raise HTTPException(status_code=400, detail="Assessment time has expired")

    question_ids = attempt["selected_question_ids"]
    if not question_ids:
        return {
            "attempt_id": attempt_id,
            "total_questions": attempt["total_questions"],
            "duration_minutes": attempt["duration_minutes"],
            "expires_at": attempt.get("expires_at"),
            "questions": [],
            "answers": {},
        }

    questions_resp = (
        supabase_client.table("mcq_questions")
        .select("id, domain_id, question_text, option_a, option_b, option_c, option_d")
        .in_("id", question_ids)
        .execute()
    )
    q_map = {q["id"]: q for q in (questions_resp.data or [])}
    ordered = [q_map[qid] for qid in question_ids if qid in q_map]

    domains_resp = (
        supabase_client.table("domains")
        .select("id, name")
        .in_("id", attempt["domain_ids"])
        .execute()
    )
    domain_map = {d["id"]: d["name"] for d in (domains_resp.data or [])}
    for q in ordered:
        q["domainName"] = domain_map.get(q.get("domain_id"), "")

    answers_resp = (
        supabase_client.table("assessment_answers")
        .select("question_id, selected_option")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    answers_map = {a["question_id"]: a["selected_option"] for a in (answers_resp.data or [])}

    return {
        "attempt_id": attempt_id,
        "total_questions": attempt["total_questions"],
        "duration_minutes": attempt["duration_minutes"],
        "expires_at": attempt.get("expires_at"),
        "questions": ordered,
        "answers": answers_map,
    }


# ---------------------------------------------------------------------------

@router.put("/attempt/{attempt_id}/answers")
def save_answer(
    attempt_id: str,
    payload: AnswerSaveRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Save/update a single MCQ answer."""
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("*")
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
        _score_attempt(attempt_id)
        raise HTTPException(status_code=400, detail="Assessment time has expired")
    if payload.question_id not in attempt["selected_question_ids"]:
        raise HTTPException(status_code=400, detail="Question not part of this attempt")

    existing = (
        supabase_client.table("assessment_answers")
        .select("id")
        .eq("attempt_id", attempt_id)
        .eq("question_id", payload.question_id)
        .execute()
    )

    now = _utcnow().isoformat()
    if existing.data:
        supabase_client.table("assessment_answers").update({
            "selected_option": payload.selected_option,
            "answered_at": now,
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase_client.table("assessment_answers").insert({
            "attempt_id": attempt_id,
            "question_id": payload.question_id,
            "selected_option": payload.selected_option,
            "answered_at": now,
        }).execute()

    return {"status": "saved"}


# ---------------------------------------------------------------------------

@router.post("/attempt/{attempt_id}/submit")
def submit_attempt(
    attempt_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Submit the ONE combined assessment. Scores both MCQ and Coding.

    Does NOT return score to the candidate.
    """
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("*")
        .eq("id", attempt_id)
        .execute()
    )
    if not attempt_resp.data:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt = attempt_resp.data[0]
    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Attempt already submitted")

    _score_attempt(attempt_id)

    return {
        "status": "submitted",
        "attempt_id": attempt_id,
        "total_mcq_questions": attempt["total_questions"],
        "total_coding_problems": attempt["total_coding_problems"],
    }
