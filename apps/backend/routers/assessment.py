"""
Combined Assessment Router

ONE assessment attempt contains BOTH:
- MCQ section (frozen question IDs in selected_question_ids)
- Coding section (frozen problem IDs in selected_coding_problem_ids)

ONE timer (expires_at), ONE final submission, ONE combined score.
"""

import random
import re
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user, AuthUser
from core.supabase import supabase_client
from schemas.assessment import (
    AssessmentStartRequest, AnswerSaveRequest, DescriptiveAnswerSaveRequest,
    HandsOnSubmitRequest,
)
# One expiry rule, shared with routers/coding.py.
from utils.time_utils import is_expired as _is_expired, utcnow as _utcnow
# NEW-attempt planning is delegated to the pure planner through the
# database-resolution service. Resuming an existing attempt never calls this.
from services.assessment_planning import PLAN_PERSISTENCE_ENABLED, plan_new_attempt

router = APIRouter(prefix="/assessment", tags=["Assessment"])


# ---------------------------------------------------------------------------

def _get_active_config() -> dict:
    """Read the active assessment configuration.

    Returns a plain dict with a defensive default for
    descriptive_question_count so callers can rely on the key existing.
    """
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
    config = dict(result.data[0])
    config.setdefault("descriptive_question_count", 0)
    config.setdefault("hands_on_question_count", 0)
    return config


def count_words(text: str) -> int:
    """Count words on a whitespace-run split, ignoring empty tokens.

    Shared canonical rule for display, input enforcement and server-side
    validation: trim, split on runs of whitespace (spaces/newlines/tabs),
    drop empty tokens. E.g. "hello   world\\nthis" -> 3.
    """
    if not text:
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _enforce_word_limit(question: dict, answer_text: str) -> None:
    """Reject answers exceeding the question's configured word_limit.

    Schema convention (migration 010): word_limit is NULL (unlimited) or a
    positive integer — 0 is not representable, so there is no zero-limit
    convention to preserve. Raises 400 when the limit is exceeded so the
    invalid answer is never saved.
    """
    word_limit = question.get("word_limit")
    if not word_limit or word_limit <= 0:
        return
    if count_words(answer_text) > word_limit:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Answer exceeds the word limit ({count_words(answer_text)} "
                f"words > {word_limit} allowed)"
            ),
        )


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

    # Hands-On score: full points for every frozen challenge the candidate
    # verified (flag correct). Unverified or unsubmitted challenges earn 0.
    attempt_resp = (
        supabase_client.table("assessment_attempts")
        .select("selected_hands_on_question_ids")
        .eq("id", attempt_id)
        .execute()
    )
    hands_ids = (attempt_resp.data or [{}])[0].get("selected_hands_on_question_ids") or []
    hands_points = {}
    if hands_ids:
        hq_resp = (
            supabase_client.table("hands_on_questions")
            .select("id, points")
            .in_("id", hands_ids)
            .execute()
        )
        hands_points = {h["id"]: int(h.get("points", 0) or 0) for h in (hq_resp.data or [])}

    hands_score = 0
    hands_max = 0
    if hands_ids:
        results_resp = (
            supabase_client.table("assessment_hands_on_results")
            .select("question_id, verified, score")
            .eq("attempt_id", attempt_id)
            .execute()
        )
        r_map = {
            r["question_id"]: r
            for r in (results_resp.data or [])
            if r.get("verified")
        }
        for hid in hands_ids:
            points = hands_points.get(hid, 0)
            hands_max += points
            r = r_map.get(hid)
            if r:
                # Backend-verified score wins; fall back to stored score
                # (they are identical — score is only ever written by this
                # module) capped at the challenge's points.
                stored = int(r.get("score") or 0)
                hands_score += min(stored, points) if stored > 0 else points

    # Combined score: simple sum (MCQ + Coding + Hands-On)
    # All use raw points, no weighting — straightforward total
    overall_score = mcq["score"] + coding["score"] + hands_score
    overall_max = mcq["max_score"] + coding["max_score"] + hands_max

    final_update = {
        "status": "scored",
        "submitted_at": _utcnow().isoformat(),
        "score": overall_score,
        "max_score": overall_max if overall_max > 0 else 1,
    }
    # Only touch the hands-on score columns when this attempt actually has
    # hands-on challenges. Otherwise the DB defaults (0) already reflect the
    # correct score, and databases predating migration 013 (which adds these
    # columns) stay submittable for every non-hands-on attempt.
    if hands_ids:
        final_update["hands_on_score"] = hands_score
        final_update["hands_on_max_score"] = hands_max

    supabase_client.table("assessment_attempts").update(final_update).eq("id", attempt_id).execute()

    return {
        "score": overall_score,
        "max_score": overall_max,
        "mcq_score": mcq["score"],
        "mcq_max_score": mcq["max_score"],
        "coding_score": coding["score"],
        "coding_max_score": coding["max_score"],
        "hands_on_score": hands_score,
        "hands_on_max_score": hands_max,
    }


# ---------------------------------------------------------------------------

def _select_descriptive_questions(
    descriptive_question_count: int,
    domain_ids: list,
) -> list[str]:
    """Select descriptive questions for the attempt.

    Only ACTIVE questions overlapping the candidate's chosen domains are
    eligible (same conceptual domain filtering as MCQ selection — MCQs by
    domain_id, descriptive by domain_ids overlap). Raises 400 if fewer
    eligible questions exist than requested, mirroring the MCQ/coding
    behavior of failing loudly rather than creating invalid attempts.
    """
    if descriptive_question_count <= 0:
        return []

    desc_resp = (
        supabase_client.table("descriptive_questions")
        .select("id")
        .eq("is_active", True)
        .overlaps("domain_ids", domain_ids)
        .execute()
    )
    available = desc_resp.data or []
    if len(available) < descriptive_question_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only {len(available)} active descriptive questions "
                f"available for selected domains, need {descriptive_question_count}"
            ),
        )
    sampled = random.sample(available, descriptive_question_count)
    return [d["id"] for d in sampled]


def _select_hands_on_questions(
    hands_on_question_count: int,
    domain_ids: list,
) -> list[str]:
    """Select Hands-On challenges for the attempt.

    Only ACTIVE challenges overlapping the candidate's chosen domains are
    eligible (same conceptual domain filtering as descriptive selection).
    Raises 400 if fewer eligible challenges exist than requested — loud
    failure instead of a silently invalid attempt (mirrors MCQ/descriptive).
    """
    if hands_on_question_count <= 0:
        return []

    resp = (
        supabase_client.table("hands_on_questions")
        .select("id")
        .eq("is_active", True)
        .overlaps("domain_ids", domain_ids)
        .execute()
    )
    available = resp.data or []
    if len(available) < hands_on_question_count:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only {len(available)} active hands-on challenges "
                f"available for selected domains, need {hands_on_question_count}"
            ),
        )
    sampled = random.sample(available, hands_on_question_count)
    return [h["id"] for h in sampled]


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
    #
    # Still needed: base duration, the global coding count, and (while the
    # per-domain configuration matrix is authored) the explicit technical
    # legacy fallback counts. It is NOT the source of domain limits or module
    # counts for a new attempt any more — the assessment_program row and
    # assessment_module_config are.
    config = _get_active_config()

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
            # Active attempt exists and is not expired — resume it.
            #
            # FROZEN RESUME: the attempt is returned exactly as stored. Its
            # domain_ids, every selected_*_ids array, every total_* count,
            # duration_minutes and expires_at were resolved and frozen when the
            # attempt was created. This path therefore performs NO re-selection,
            # NO assessment_config read for the purpose of changing the attempt,
            # and NO write (INSERT/UPDATE/DELETE) to assessment_attempts — so a
            # later admin configuration change can never alter an active
            # attempt.
            attempt = attempt_resp.data[0]
            return {
                "attempt_id": attempt["id"],
                "total_mcq_questions": attempt["total_questions"],
                "total_coding_problems": attempt.get("total_coding_problems", 0),
                "total_descriptive_questions": attempt.get("total_descriptive_questions", 0),
                "selected_descriptive_question_ids": attempt.get(
                    "selected_descriptive_question_ids") or [],
                "total_hands_on_questions": attempt.get("total_hands_on_questions", 0),
                "selected_hands_on_question_ids": attempt.get(
                    "selected_hands_on_question_ids") or [],
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

    # 4. Resolve the frozen assessment plan for this NEW attempt.
    #
    # From here the PLANNER owns the decision: domain eligibility (exists /
    # active / scope matches the programme), the selected-domain limit
    # (programme max_domains), per-domain module configuration, cross-domain
    # exact allocation of descriptive questions and hands-on challenges, the
    # global coding selection, and the total duration. It fails loudly (400)
    # rather than substituting, truncating or topping up anything.
    plan = plan_new_attempt(
        config=config,
        semester=candidate_semester,
        requested_domain_ids=payload.domain_ids,
    )

    # 5. Create ONE combined attempt from the planner's frozen values.
    #
    # The plan snapshot (plan / base_duration_minutes / additional_minutes)
    # is persisted when PLAN_PERSISTENCE_ENABLED is True (migration 017+).
    # When False, only the existing frozen columns are written.
    now = _utcnow()
    expires_at = now + timedelta(minutes=plan.duration_minutes)

    insert_payload = {
        "profile_id": profile_id,
        "status": "in_progress",
        "domain_ids": plan.domain_ids,
        "selected_question_ids": plan.selected_mcq_ids,
        "total_questions": plan.mcq_total,
        "selected_coding_problem_ids": plan.selected_coding_problem_ids,
        "total_coding_problems": plan.coding_total,
        "selected_descriptive_question_ids": plan.selected_descriptive_question_ids,
        "total_descriptive_questions": plan.descriptive_total,
        "selected_hands_on_question_ids": plan.selected_hands_on_question_ids,
        "total_hands_on_questions": plan.hands_on_total,
        "duration_minutes": plan.duration_minutes,
        "started_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    if PLAN_PERSISTENCE_ENABLED:
        insert_payload["plan"] = plan.model_dump(mode="json")
        insert_payload["base_duration_minutes"] = plan.base_duration_minutes
        insert_payload["additional_minutes"] = plan.additional_minutes

    result = supabase_client.table("assessment_attempts").insert(
        insert_payload
    ).execute()

    attempt = result.data[0] if result.data else None
    if not attempt:
        raise HTTPException(status_code=500, detail="Failed to create attempt")

    return {
        "attempt_id": attempt["id"],
        "total_mcq_questions": attempt["total_questions"],
        "total_coding_problems": attempt["total_coding_problems"],
        "total_descriptive_questions": attempt["total_descriptive_questions"],
        "selected_descriptive_question_ids": attempt.get(
            "selected_descriptive_question_ids", []),
        "total_hands_on_questions": attempt["total_hands_on_questions"],
        "selected_hands_on_question_ids": attempt.get(
            "selected_hands_on_question_ids", []),
        "duration_minutes": attempt["duration_minutes"],
        "domain_ids": plan.domain_ids,
        "expires_at": attempt["expires_at"],
    }


# ---------------------------------------------------------------------------

@router.get("/current")
def get_current_attempt(current_user: AuthUser = Depends(get_current_user)):
    """Get the candidate's most recent in-progress attempt (combined MCQ+Coding)."""
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

    attempt = result.data[0]
    if _is_expired(attempt):
        _score_attempt(attempt["id"])
        attempt["status"] = "scored"

    # admin_remark is admin-only — never returned through candidate endpoints.
    attempt.pop("admin_remark", None)
    return attempt


@router.get("/attempt/{attempt_id}")
def get_attempt(attempt_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Get attempt details (no scoring data for candidates)."""
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

    if attempt["status"] == "in_progress" and _is_expired(attempt):
        _score_attempt(attempt_id)
        attempt["status"] = "scored"

    # admin_remark is admin-only — never returned through candidate endpoints.
    attempt.pop("admin_remark", None)
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

    # FROZEN READ: Descriptive and Hands-on selections were resolved and frozen
    # at attempt creation. They are read verbatim here — never re-selected, never
    # topped up — so this endpoint cannot mutate the attempt either.
    question_ids = attempt["selected_question_ids"]
    desc_ids = attempt.get("selected_descriptive_question_ids") or []
    hands_ids = attempt.get("selected_hands_on_question_ids") or []

    # Fetch MCQ questions (empty list if none selected)
    questions = []
    answers_map = {}
    if question_ids:
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
        questions = ordered

    # Fetch descriptive questions (empty list if none selected)
    descriptive_questions = []
    descriptive_answers_map = {}
    if desc_ids:
        desc_resp = (
            supabase_client.table("descriptive_questions")
            .select("id, question_text, image_url, word_limit")
            .in_("id", desc_ids)
            .execute()
        )
        desc_q_map = {q["id"]: q for q in (desc_resp.data or [])}
        descriptive_questions = [desc_q_map[qid] for qid in desc_ids if qid in desc_q_map]

        desc_answers_resp = (
            supabase_client.table("assessment_descriptive_answers")
            .select("question_id, answer_text")
            .eq("attempt_id", attempt_id)
            .execute()
        )
        descriptive_answers_map = {
            a["question_id"]: a["answer_text"] for a in (desc_answers_resp.data or [])
        }

    # Fetch hands-on challenges (metadata only — NEVER the expected flag)
    hands_on_questions = []
    hands_on_results = []
    if hands_ids:
        ho_resp = (
            supabase_client.table("hands_on_questions")
            .select("id, title, description, difficulty, points, challenge_type, challenge_url")
            .in_("id", hands_ids)
            .execute()
        )
        ho_map = {q["id"]: q for q in (ho_resp.data or [])}
        hands_on_questions = [ho_map[qid] for qid in hands_ids if qid in ho_map]

        # Candidate's own submissions — evidence only (their SQL input and
        # flag, so the read-only form can be pre-filled on reload).
        # verified/score are deliberately excluded: the candidate is never
        # told whether their flag was correct (admins see it via the admin
        # response endpoint). Rows are projected explicitly so those fields
        # can never leak through even if the query shape changes.
        ho_results_resp = (
            supabase_client.table("assessment_hands_on_results")
            .select("question_id, submitted_input, submitted_flag, started_at, completed_at")
            .eq("attempt_id", attempt_id)
            .execute()
        )
        hands_on_results = [
            {
                "question_id": r.get("question_id"),
                "submitted_input": r.get("submitted_input"),
                "submitted_flag": r.get("submitted_flag"),
                "started_at": r.get("started_at"),
                "completed_at": r.get("completed_at"),
            }
            for r in (ho_results_resp.data or [])
        ]

    # admin_remark is admin-only. Never include it in candidate responses.
    return {
        "attempt_id": attempt_id,
        "total_questions": attempt["total_questions"],
        "total_descriptive_questions": attempt.get("total_descriptive_questions", 0),
        "total_hands_on_questions": attempt.get("total_hands_on_questions", 0),
        "duration_minutes": attempt["duration_minutes"],
        "expires_at": attempt.get("expires_at"),
        "questions": questions,
        "answers": answers_map,
        "descriptive_questions": descriptive_questions,
        "descriptive_answers": descriptive_answers_map,
        "hands_on_questions": hands_on_questions,
        "hands_on_results": hands_on_results,
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

@router.put("/attempt/{attempt_id}/descriptive-answers")
def save_descriptive_answer(
    attempt_id: str,
    payload: DescriptiveAnswerSaveRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Save/update a descriptive question answer."""
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

    desc_ids = attempt.get("selected_descriptive_question_ids") or []
    if payload.question_id not in desc_ids:
        raise HTTPException(status_code=400, detail="Question not part of this attempt")

    # Server-side word limit enforcement (do not trust the frontend).
    question_resp = (
        supabase_client.table("descriptive_questions")
        .select("word_limit")
        .eq("id", payload.question_id)
        .execute()
    )
    question = question_resp.data[0] if question_resp.data else {}
    _enforce_word_limit(question, payload.answer_text)

    existing = (
        supabase_client.table("assessment_descriptive_answers")
        .select("id")
        .eq("attempt_id", attempt_id)
        .eq("question_id", payload.question_id)
        .execute()
    )

    now = _utcnow().isoformat()
    if existing.data:
        supabase_client.table("assessment_descriptive_answers").update({
            "answer_text": payload.answer_text,
            "answered_at": now,
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase_client.table("assessment_descriptive_answers").insert({
            "attempt_id": attempt_id,
            "question_id": payload.question_id,
            "answer_text": payload.answer_text,
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
        # 409 Conflict, matching /assessment/start's already-completed convention:
        # the attempt IS finalized, so this is an idempotent no-op, not a client error.
        raise HTTPException(status_code=409, detail="Attempt already submitted")

    _score_attempt(attempt_id)

    return {
        "status": "submitted",
        "attempt_id": attempt_id,
        "total_mcq_questions": attempt["total_questions"],
        "total_coding_problems": attempt["total_coding_problems"],
        "total_descriptive_questions": attempt.get("total_descriptive_questions", 0),
        "total_hands_on_questions": attempt.get("total_hands_on_questions", 0),
    }


# ---------------------------------------------------------------------------

@router.put("/attempt/{attempt_id}/hands-on")
def submit_hands_on(
    attempt_id: str,
    payload: HandsOnSubmitRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """Submit a Hands-On challenge result (SQL evidence + flag).

    Only the flag is verified. The SQL input is stored verbatim as evidence
    and is never parsed, executed or validated.

    Verification is backend-authoritative:
      - the challenge must belong to this attempt (frozen selection),
      - the expected flag never leaves the backend and is compared exactly
        after trimming surrounding whitespace,
      - score is full question points when correct, 0 otherwise — a
        candidate-provided score is never trusted (the schema has no such
        field in the request at all).

    Each challenge may be submitted exactly ONCE per (attempt, question):
    a second submission — via refresh, another tab, or a direct API call —
    is rejected with 409 before any scoring happens.

    Returns only {status: "submitted"}. The candidate is deliberately NOT
    told whether the flag was correct, and never sees the score, the
    verification result, or the expected flag. Admins see all of it via
    the admin response endpoint.
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
        raise HTTPException(status_code=400, detail="Attempt is not in progress")
    if _is_expired(attempt):
        _score_attempt(attempt_id)
        raise HTTPException(status_code=400, detail="Assessment time has expired")

    hands_ids = attempt.get("selected_hands_on_question_ids") or []
    if payload.question_id not in hands_ids:
        raise HTTPException(status_code=400, detail="Challenge not part of this attempt")

    # ONE submission per (attempt, question). Enforced server-side BEFORE any
    # scoring: refresh/re-opened tabs/direct API calls all land here and get
    # 409. The candidate can never overwrite or re-roll a stored result.
    existing = (
        supabase_client.table("assessment_hands_on_results")
        .select("id")
        .eq("attempt_id", attempt_id)
        .eq("question_id", payload.question_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=409, detail="Challenge has already been submitted"
        )

    # Load the challenge server-side. expected_flag is only ever read here.
    question_resp = (
        supabase_client.table("hands_on_questions")
        .select("id, points, expected_flag")
        .eq("id", payload.question_id)
        .execute()
    )
    if not question_resp.data:
        raise HTTPException(status_code=404, detail="Challenge not found")
    question = question_resp.data[0]

    submitted_flag = (payload.submitted_flag or "").strip()
    expected_flag = (question.get("expected_flag") or "").strip()
    verified = bool(expected_flag) and submitted_flag == expected_flag
    points = int(question.get("points", 0) or 0)
    score = points if verified else 0

    now = _utcnow().isoformat()
    supabase_client.table("assessment_hands_on_results").insert({
        "attempt_id": attempt_id,
        "question_id": payload.question_id,
        "submitted_input": payload.submitted_input or "",
        "submitted_flag": submitted_flag,
        "verified": verified,
        "score": score,
        "started_at": now,
        "completed_at": now if verified else None,
    }).execute()

    # Neutral ack only: no verified, no score, no points, no expected flag.
    return {"status": "submitted"}
