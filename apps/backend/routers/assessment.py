import random
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user, AuthUser
from core.supabase import supabase_client
from schemas.assessment import AssessmentStartRequest, AnswerSaveRequest

router = APIRouter(prefix="/assessment", tags=["Assessment"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_config() -> dict:
    """Read the active assessment configuration from the database."""
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
    """Check whether an attempt has expired based on server time."""
    expires_at = attempt.get("expires_at")
    if not expires_at:
        return False
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return _utcnow() > expires_at


def _score_attempt(attempt_id: str) -> dict:
    """Score an attempt server-side. Returns the scoring result."""
    # Fetch answers
    answers_resp = (
        supabase_client.table("assessment_answers")
        .select("id, question_id, selected_option")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    answers = answers_resp.data or []

    # Fetch correct answers from the question bank
    question_ids = [a["question_id"] for a in answers]
    if not question_ids:
        # No answers submitted — score as 0
        supabase_client.table("assessment_attempts").update({
            "status": "scored",
            "submitted_at": _utcnow().isoformat(),
            "score": 0,
            "max_score": 0,
        }).eq("id", attempt_id).execute()
        return {"score": 0, "max_score": 0}

    questions_resp = (
        supabase_client.table("mcq_questions")
        .select("id, correct_option")
        .in_("id", question_ids)
        .execute()
    )
    correct_map = {q["id"]: q["correct_option"] for q in (questions_resp.data or [])}

    # Score each answer
    score = 0
    for answer in answers:
        is_correct = answer["selected_option"] == correct_map.get(answer["question_id"])
        if is_correct:
            score += 1
        supabase_client.table("assessment_answers").update({
            "is_correct": is_correct,
        }).eq("id", answer["id"]).execute()

    # Update attempt
    supabase_client.table("assessment_attempts").update({
        "status": "scored",
        "submitted_at": _utcnow().isoformat(),
        "score": score,
        "max_score": len(answers),
    }).eq("id", attempt_id).execute()

    return {"score": score, "max_score": len(answers)}


# ---------------------------------------------------------------------------
# Start an assessment
# ---------------------------------------------------------------------------

@router.post("/start")
def start_assessment(
    payload: AssessmentStartRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Start a new MCQ assessment with 1 or 2 selected domains."""
    profile_id = current_user.id

    # 1. Read active assessment configuration
    config = _get_active_config()
    total_questions = config["total_questions"]
    duration_minutes = config["duration_minutes"]
    max_domains = config["max_domains"]

    # 2. Verify candidate profile exists
    profile = (
        supabase_client.table("profiles")
        .select("id")
        .eq("id", profile_id)
        .execute()
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    # 3. Get candidate record (semester comes from here, NOT from request)
    candidate = (
        supabase_client.table("candidates")
        .select("id, semester")
        .eq("profile_id", profile_id)
        .execute()
    )
    if not candidate.data:
        raise HTTPException(status_code=404, detail="Candidate record not found")

    candidate_semester = candidate.data[0]["semester"]

    # 4. Check for existing in_progress attempt
    existing = (
        supabase_client.table("assessment_attempts")
        .select("id")
        .eq("profile_id", profile_id)
        .eq("status", "in_progress")
        .execute()
    )
    if existing.data:
        attempt_id = existing.data[0]["id"]
        # Check if it's expired — if so, auto-submit it
        attempt_resp = (
            supabase_client.table("assessment_attempts")
            .select("*")
            .eq("id", attempt_id)
            .execute()
        )
        if attempt_resp.data and _is_expired(attempt_resp.data[0]):
            _score_attempt(attempt_id)
            raise HTTPException(
                status_code=409,
                detail=(
                    f"You have an expired attempt ({attempt_id}) that has been "
                    "auto-submitted. Check your results."
                ),
            )
        raise HTTPException(
            status_code=409,
            detail=f"You already have an in-progress attempt: {attempt_id}",
        )

    # 5. Validate domains
    domain_ids = payload.domain_ids
    if len(domain_ids) < 1 or len(domain_ids) > max_domains:
        raise HTTPException(
            status_code=400,
            detail=f"Select between 1 and {max_domains} domains",
        )

    # Fetch and validate all domains are active
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

    # 6. Determine question distribution
    num_domains = len(domain_ids)

    if num_domains == 1:
        per_domain = total_questions
    else:
        if total_questions % 2 != 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Total questions ({total_questions}) must be even "
                    f"when selecting 2 domains for an equal split."
                ),
            )
        per_domain = total_questions // 2

    # 7. Randomly select questions from each domain + semester
    selected_question_ids = []

    for domain in active_domains:
        count = per_domain

        q_resp = (
            supabase_client.table("mcq_questions")
            .select("id")
            .eq("domain_id", domain["id"])
            .eq("semester", candidate_semester)
            .eq("is_active", True)
            .execute()
        )

        available = q_resp.data or []
        if len(available) < count:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Domain '{domain['name']}' (Semester {candidate_semester}) "
                    f"has only {len(available)} active questions, need {count}"
                ),
            )

        sampled = random.sample(available, count)
        selected_question_ids.extend([q["id"] for q in sampled])

    random.shuffle(selected_question_ids)

    # 8. Calculate timestamps
    now = _utcnow()
    expires_at = now + timedelta(minutes=duration_minutes)

    # 9. Create the attempt
    result = supabase_client.table("assessment_attempts").insert({
        "profile_id": profile_id,
        "status": "in_progress",
        "domain_ids": domain_ids,
        "selected_question_ids": selected_question_ids,
        "total_questions": len(selected_question_ids),
        "duration_minutes": duration_minutes,
        "started_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }).execute()

    attempt = result.data[0] if result.data else None
    if not attempt:
        raise HTTPException(status_code=500, detail="Failed to create attempt")

    return {
        "attempt_id": attempt["id"],
        "total_questions": attempt["total_questions"],
        "duration_minutes": attempt["duration_minutes"],
        "domain_ids": domain_ids,
        "expires_at": attempt["expires_at"],
    }


# ---------------------------------------------------------------------------
# Get current attempt (or active attempt)
# ---------------------------------------------------------------------------

@router.get("/current")
def get_current_attempt(current_user: AuthUser = Depends(get_current_user)):
    """Get the candidate's most recent in-progress attempt.

    Does NOT return score, max_score, or any scoring information.
    """
    result = (
        supabase_client.table("assessment_attempts")
        .select("id, profile_id, status, domain_ids, selected_question_ids, total_questions, duration_minutes, started_at, expires_at, submitted_at, created_at")
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


# ---------------------------------------------------------------------------
# Get attempt details (no scoring data for candidates)
# ---------------------------------------------------------------------------

@router.get("/attempt/{attempt_id}")
def get_attempt(attempt_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Get attempt details. Only the owner can access their attempt.

    Does NOT return score, max_score, or any scoring information.
    """
    result = (
        supabase_client.table("assessment_attempts")
        .select("id, profile_id, status, domain_ids, selected_question_ids, total_questions, duration_minutes, started_at, expires_at, submitted_at, created_at")
        .eq("id", attempt_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt = result.data[0]

    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Auto-submit if expired
    if attempt["status"] == "in_progress" and _is_expired(attempt):
        _score_attempt(attempt_id)
        attempt["status"] = "scored"

    return attempt


# ---------------------------------------------------------------------------
# Get questions for an attempt (without correct answers)
# ---------------------------------------------------------------------------

@router.get("/attempt/{attempt_id}/questions")
def get_attempt_questions(
    attempt_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Get the questions for an attempt. Correct answers are NEVER sent."""
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
        return []

    questions_resp = (
        supabase_client.table("mcq_questions")
        .select("id, domain_id, question_text, option_a, option_b, option_c, option_d")
        .in_("id", question_ids)
        .execute()
    )

    q_map = {q["id"]: q for q in (questions_resp.data or [])}
    ordered_questions = [q_map[qid] for qid in question_ids if qid in q_map]

    domain_ids = attempt["domain_ids"]
    domains_resp = (
        supabase_client.table("domains")
        .select("id, name")
        .in_("id", domain_ids)
        .execute()
    )
    domain_map = {d["id"]: d["name"] for d in (domains_resp.data or [])}

    for q in ordered_questions:
        q["domainName"] = domain_map.get(q.get("domain_id"), "")

    answers_resp = (
        supabase_client.table("assessment_answers")
        .select("question_id, selected_option")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    answers_map = {
        a["question_id"]: a["selected_option"]
        for a in (answers_resp.data or [])
    }

    return {
        "attempt_id": attempt_id,
        "total_questions": attempt["total_questions"],
        "duration_minutes": attempt["duration_minutes"],
        "expires_at": attempt.get("expires_at"),
        "questions": ordered_questions,
        "answers": answers_map,
    }


# ---------------------------------------------------------------------------
# Save/update an answer
# ---------------------------------------------------------------------------

@router.put("/attempt/{attempt_id}/answers")
def save_answer(
    attempt_id: str,
    payload: AnswerSaveRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Save or update a single answer. Only on in_progress, non-expired attempts."""
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
# Submit attempt (score it)
# ---------------------------------------------------------------------------

@router.post("/attempt/{attempt_id}/submit")
def submit_attempt(
    attempt_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Submit and score the attempt. Locks the attempt permanently.

    Does NOT return score or scoring data to the candidate.
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
        "total_questions": attempt["total_questions"],
    }
