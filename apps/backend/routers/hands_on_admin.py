from fastapi import APIRouter, Depends, HTTPException
from core.auth import require_admin, AuthUser
from core.supabase import is_foreign_key_violation, supabase_client
from schemas.assessment import HandsOnCreate, HandsOnUpdate
import json

router = APIRouter(prefix="/admin/hands-on-questions", tags=["Admin Hands-On"])

# Shared message for both the pre-check and the foreign-key fallback so the
# admin always gets the same, actionable explanation.
_HANDS_ON_IN_USE_DETAIL = (
    "Cannot delete: challenge is referenced by existing attempts. "
    "Use deactivation instead."
)

_UNKNOWN_DOMAIN_DETAIL = "One or more domain IDs not found"


def _assert_domains_exist(domain_ids: list) -> None:
    """Validate that every supplied domain ID exists.

    A malformed (non-UUID) ID makes PostgREST reject the whole ``in_`` filter
    with a raw Postgres 22P02 error, and an unknown-but-valid UUID silently
    returns no rows — both become the same actionable 400 instead of a 500.
    """
    try:
        domains_resp = (
            supabase_client.table("domains")
            .select("id")
            .in_("id", list(domain_ids))
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=400, detail=_UNKNOWN_DOMAIN_DETAIL)

    if not domains_resp.data or len(domains_resp.data) != len(domain_ids):
        raise HTTPException(status_code=400, detail=_UNKNOWN_DOMAIN_DETAIL)


def _hands_on_referenced_by_attempt(question_id: str) -> bool:
    """Return True if any assessment attempt froze this challenge in its selection.

    ``selected_hands_on_question_ids`` is a JSONB array of UUID strings.
    ``.contains`` with a Python list serialises to PostgreSQL array syntax
    (``cs.{uuid}``), which PostgREST cannot parse as JSON for a JSONB column —
    the filter either errors or silently matches nothing. Passing an explicit
    JSON string keeps the containment operator unambiguous (``cs.["uuid"]``).
    """
    attempts = (
        supabase_client.table("assessment_attempts")
        .select("id")
        .filter("selected_hands_on_question_ids", "cs", json.dumps([question_id]))
        .limit(1)
        .execute()
    )
    return bool(attempts.data)


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
            _assert_domains_exist(payload.domain_ids)

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
            # WASM bootstrap fields. They were previously omitted, so a newly
            # created sql_wasm / pandas_wasm challenge lost its dataset and
            # validation spec and could never run for the candidate (NULL for
            # the CTF type, which does not use them).
            "schema_sql": payload.schema_sql,
            "dataset_json": payload.dataset_json,
            "starter_code": payload.starter_code,
            "validation_spec": payload.validation_spec,
            "expected_answer": payload.expected_answer,
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
            _assert_domains_exist(updates["domain_ids"])

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
    """Delete a hands-on challenge if safe (not referenced by attempts). Admin only.

    An unused challenge is removed. A challenge referenced by any existing
    (frozen or in-progress) assessment attempt is protected and rejected with a
    409 so historical attempt data is never broken; deactivate it instead.
    """
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
        if _hands_on_referenced_by_attempt(question_id):
            raise HTTPException(status_code=409, detail=_HANDS_ON_IN_USE_DETAIL)

        try:
            (
                supabase_client.table("hands_on_questions")
                .delete()
                .eq("id", question_id)
                .execute()
            )
        except Exception as delete_exc:
            # The assessment_hands_on_answers FK (ON DELETE RESTRICT) is the
            # ultimate data-integrity guard. If the pre-check missed a reference
            # (e.g. an answer row left behind without a matching selection),
            # surface the same friendly conflict instead of a raw 500.
            if is_foreign_key_violation(delete_exc):
                raise HTTPException(status_code=409, detail=_HANDS_ON_IN_USE_DETAIL)
            raise
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
