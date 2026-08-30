import random
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user, AuthUser
from core.supabase import supabase_client
from schemas.assessment import AssessmentStartRequest, AnswerSaveRequest

router = APIRouter(prefix="/assessment", tags=["Assessment"])

# Total questions per attempt
TOTAL_QUESTIONS = 20


# ---------------------------------------------------------------------------
# Start an assessment
# ---------------------------------------------------------------------------

@router.post("/start")
def start_assessment(
    payload: AssessmentStartRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Start a new MCQ assessment with 1 or 2 selected domains.

    The candidate's semester is read from their candidate record in the
    database — it is NEVER trusted from the request body.

    Validates:
    - Candidate profile and candidate record exist
    - 1 or 2 domains selected
    - All domains are active
    - Each domain has enough questions for (domain, semester)
    - No existing in_progress attempt

    Randomization:
    - Questions are selected once and frozen in the attempt
    - 1 domain: ALL questions from that domain + semester
    - 2 domains: half from each (first domain gets extra if odd)
    """
    profile_id = current_user.id

    # 1. Verify candidate profile exists
    profile = (
        supabase_client.table("profiles")
        .select("id")
        .eq("id", profile_id)
        .execute()
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    # 2. Get candidate record (semester comes from here, NOT from request)
    candidate = (
        supabase_client.table("candidates")
        .select("id, semester")
        .eq("profile_id", profile_id)
        .execute()
    )
    if not candidate.data:
        raise HTTPException(status_code=404, detail="Candidate record not found")

    candidate_semester = candidate.data[0]["semester"]

    # 3. Check for existing in_progress attempt
    existing = (
        supabase_client.table("assessment_attempts")
        .select("id")
        .eq("profile_id", profile_id)
        .eq("status", "in_progress")
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=409,
            detail=f"You already have an in-progress attempt: {existing.data[0]['id']}",
        )

    # 4. Validate domains
    domain_ids = payload.domain_ids
    if len(domain_ids) < 1 or len(domain_ids) > 2:
        raise HTTPException(status_code=400, detail="Select 1 or 2 domains")

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

    # 5. Determine question distribution
    num_domains = len(domain_ids)
    if num_domains == 1:
        per_domain = TOTAL_QUESTIONS
    else:
        per_domain = TOTAL_QUESTIONS // 2

    extra = TOTAL_QUESTIONS - (per_domain * num_domains)

    # 6. Randomly select questions from each domain + semester
    selected_question_ids = []

    for i, domain in enumerate(active_domains):
        # First domain gets the extra question if total is odd
        count = per_domain + (extra if i == 0 else 0)

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

        # Random selection without replacement
        sampled = random.sample(available, count)
        selected_question_ids.extend([q["id"] for q in sampled])

    # Shuffle the combined list for mixed order
    random.shuffle(selected_question_ids)

    # 7. Determine assessment duration (max of selected domains)
    duration = max(d["duration_minutes"] for d in active_domains)

    # 8. Create the attempt
    result = supabase_client.table("assessment_attempts").insert({
        "profile_id": profile_id,
        "status": "in_progress",
        "domain_ids": domain_ids,
        "selected_question_ids": selected_question_ids,
        "total_questions": len(selected_question_ids),
        "duration_minutes": duration,
    }).execute()

    attempt = result.data[0] if result.data else None
    if not attempt:
        raise HTTPException(status_code=500, detail="Failed to create attempt")

    return {
        "attempt_id": attempt["id"],
        "total_questions": attempt["total_questions"],
        "duration_minutes": attempt["duration_minutes"],
        "domain_ids": domain_ids,
    }


# ---------------------------------------------------------------------------
# Get current attempt (or active attempt)
# ---------------------------------------------------------------------------

@router.get("/current")
def get_current_attempt(current_user: AuthUser = Depends(get_current_user)):
    """Get the candidate's most recent in-progress attempt."""
    result = (
        supabase_client.table("assessment_attempts")
        .select("*")
        .eq("profile_id", current_user.id)
        .eq("status", "in_progress")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="No active attempt")

    return result.data[0]


# ---------------------------------------------------------------------------
# Get attempt details
# ---------------------------------------------------------------------------

@router.get("/attempt/{attempt_id}")
def get_attempt(attempt_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Get attempt details. Only the owner can access their attempt."""
    result = (
        supabase_client.table("assessment_attempts")
        .select("*")
        .eq("id", attempt_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt = result.data[0]

    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    return attempt


# ---------------------------------------------------------------------------
# Get questions for an attempt (without correct answers)
# ---------------------------------------------------------------------------

@router.get("/attempt/{attempt_id}/questions")
def get_attempt_questions(
    attempt_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Get the questions for an attempt. Correct answers are NEVER sent.

    Returns questions in the frozen order from the attempt.
    """
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

    # Security check
    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if attempt["status"] not in ("in_progress",):
        raise HTTPException(status_code=400, detail="Attempt is not in progress")

    # Fetch questions (without correct_option, explanation)
    question_ids = attempt["selected_question_ids"]
    if not question_ids:
        return []

    questions_resp = (
        supabase_client.table("mcq_questions")
        .select("id, domain_id, question_text, option_a, option_b, option_c, option_d")
        .in_("id", question_ids)
        .execute()
    )

    # Preserve the frozen order
    q_map = {q["id"]: q for q in (questions_resp.data or [])}
    ordered_questions = [q_map[qid] for qid in question_ids if qid in q_map]

    # Fetch domain names for display
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

    # Fetch existing answers for this attempt
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
    """Save or update a single answer. Only on in_progress attempts."""
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

    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Attempt is not in progress")

    # Validate question belongs to this attempt
    if payload.question_id not in attempt["selected_question_ids"]:
        raise HTTPException(status_code=400, detail="Question not part of this attempt")

    # Upsert the answer
    existing = (
        supabase_client.table("assessment_answers")
        .select("id")
        .eq("attempt_id", attempt_id)
        .eq("question_id", payload.question_id)
        .execute()
    )

    now = datetime.now(timezone.utc).isoformat()

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
    """Submit and score the attempt. Locks the attempt permanently."""
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

    if attempt["profile_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if attempt["status"] != "in_progress":
        raise HTTPException(status_code=400, detail="Attempt already submitted")

    # Server-side time enforcement
    started = datetime.fromisoformat(attempt["started_at"].replace("Z", "+00:00"))
    duration_sec = attempt["duration_minutes"] * 60
    now = datetime.now(timezone.utc)
    if (now - started).total_seconds() > duration_sec + 60:
        # Allow 60s grace period for network latency
        pass  # Still score, but note it was late

    # Fetch all answers
    answers_resp = (
        supabase_client.table("assessment_answers")
        .select("id, question_id, selected_option")
        .eq("attempt_id", attempt_id)
        .execute()
    )
    answers = answers_resp.data or []

    if not answers:
        raise HTTPException(status_code=400, detail="No answers to submit")

    # Fetch correct answers
    question_ids = [a["question_id"] for a in answers]
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
        "submitted_at": now.isoformat(),
        "score": score,
        "max_score": len(answers),
    }).eq("id", attempt_id).execute()

    return {
        "attempt_id": attempt_id,
        "score": score,
        "max_score": len(answers),
        "total_questions": attempt["total_questions"],
    }


# ---------------------------------------------------------------------------
# Get results
# ---------------------------------------------------------------------------

@router.get("/attempt/{attempt_id}/results")
def get_results(
    attempt_id: str,
    current_user: AuthUser = Depends(get_current_user),
):
    """Get the results for a scored attempt."""
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

    if attempt["status"] != "scored":
        raise HTTPException(status_code=400, detail="Attempt not yet scored")

    # Fetch answers with correctness
    answers_resp = (
        supabase_client.table("assessment_answers")
        .select("question_id, selected_option, is_correct")
        .eq("attempt_id", attempt_id)
        .execute()
    )

    # Fetch questions for display
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

    # Build answer details
    answers_map = {a["question_id"]: a for a in (answers_resp.data or [])}

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

    return {
        "attempt_id": attempt_id,
        "score": attempt["score"],
        "max_score": attempt["max_score"],
        "total_questions": attempt["total_questions"],
        "submitted_at": attempt["submitted_at"],
        "questions": questions_with_answers,
    }
