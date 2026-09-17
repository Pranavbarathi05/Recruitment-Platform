"""Admin API for managing assessment_module_config.

Provides read and upsert endpoints for per-domain, per-tier module
configuration.  Read-only preflight validation checks the available
question pool before writing.

All endpoints require admin authentication (Depends(require_admin)).
"""

from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_admin, AuthUser
from core.supabase import supabase_client
from schemas.assessment import (
    ModuleConfigUpdate,
    SCOPE_ALLOWED_APPLIES_TO,
    APPLIES_TO_VALIDATION_SEMESTER,
)

router = APIRouter(prefix="/admin/assessment/modules", tags=["Admin Modules"])


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _domain_not_found(domain_id: str):
    raise HTTPException(status_code=404, detail=f"Domain not found: {domain_id}")


def _domain_info(row: dict) -> dict:
    """Extract the candidate-safe domain fields for responses."""
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "assessment_scope": row["assessment_scope"],
        "is_active": row["is_active"],
    }


def _config_row(row: dict) -> dict:
    """Extract the config fields for responses."""
    return {
        "id": row["id"],
        "domain_id": row["domain_id"],
        "applies_to": row["applies_to"],
        "mcq_count": row["mcq_count"],
        "descriptive_count": row["descriptive_count"],
        "hands_on_enabled": row["hands_on_enabled"],
        "hands_on_count": row["hands_on_count"],
        "hands_on_additional_minutes": row["hands_on_additional_minutes"],
        "notes": row.get("notes"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Preflight validation helpers
# ---------------------------------------------------------------------------


def _count_mcq_pool(domain_id: str, semester: int) -> int:
    """Count active MCQ questions eligible for a domain + semester."""
    resp = (
        supabase_client.table("mcq_questions")
        .select("id", count="exact")
        .eq("domain_id", domain_id)
        .eq("semester", semester)
        .eq("is_active", True)
        .execute()
    )
    return len(resp.data) if resp.data else 0


def _count_descriptive_pool(domain_id: str) -> int:
    """Count active descriptive questions overlapping a domain.

    Uses the same overlap semantics as the planner: a descriptive question
    with domain_ids containing this domain_id is eligible.
    """
    resp = (
        supabase_client.table("descriptive_questions")
        .select("id")
        .eq("is_active", True)
        .contains("domain_ids", [domain_id])
        .execute()
    )
    return len(resp.data) if resp.data else 0


def _count_hands_on_pool(domain_id: str) -> int:
    """Count active hands-on challenges overlapping a domain."""
    resp = (
        supabase_client.table("hands_on_questions")
        .select("id")
        .eq("is_active", True)
        .contains("domain_ids", [domain_id])
        .execute()
    )
    return len(resp.data) if resp.data else 0


def _count_shared_pool(table: str, domain_id: str) -> int:
    """Count active questions in `table` that list domain_id among SEVERAL domains.

    These are the questions the planner may have to satisfy more than one
    selected domain with, which is exactly what a single-domain preflight
    cannot resolve.  Only ever used to raise an advisory warning — never to
    allow a known per-domain shortage.
    """
    resp = (
        supabase_client.table(table)
        .select("id, domain_ids")
        .eq("is_active", True)
        .contains("domain_ids", [domain_id])
        .execute()
    )
    shared = 0
    for row in resp.data or []:
        if len(row.get("domain_ids") or []) > 1:
            shared += 1
    return shared


def _build_preflight(
    domain_id: str,
    applies_to: str,
    mcq_count: int,
    descriptive_count: int,
    hands_on_enabled: bool,
    hands_on_count: int,
    is_technical: bool = True,
) -> dict:
    """Build the preflight validation object.

    TWO SEVERITIES, deliberately kept apart:

    hard_errors
        A PER-DOMAIN pool shortage: the requested count exceeds this domain's
        own eligible pool, so the configuration could never be satisfied. The
        caller rejects the request and performs NO write.

    warnings
        Cross-domain feasibility uncertainty. Descriptive questions and hands-on
        challenges may be shared between domains, and a single-domain preflight
        cannot prove that a multi-domain plan is jointly satisfiable. These are
        advisory only; the planner validates the real allocation.

    FINAL SEMANTICS
        ``mcq_count`` IS the per-domain MCQ quantity — it is authoritative.
        For technical domains, it replaces the old programme-level split.
        For organizational domains, it was always authoritative.
        ``descriptive_count`` is organizational-only; rejected at the endpoint
        for technical domains.
    """
    semester = APPLIES_TO_VALIDATION_SEMESTER[applies_to]
    mcq_available = _count_mcq_pool(domain_id, semester)
    descriptive_available = _count_descriptive_pool(domain_id)
    hands_on_available = _count_hands_on_pool(domain_id)

    hard_errors = []
    warnings = []

    # MCQ pool validation: mcq_count is authoritative for ALL scopes.
    # mcq_count=0 is valid (domain contributes zero MCQs) and never
    # triggers a shortage.
    if mcq_count > mcq_available:
        hard_errors.append(
            f"Requested mcq_count ({mcq_count}) exceeds the available "
            f"MCQ pool ({mcq_available}) for semester {semester}"
        )
    if descriptive_count > descriptive_available:
        hard_errors.append(
            f"Requested descriptive_count ({descriptive_count}) exceeds the "
            f"available descriptive pool ({descriptive_available})"
        )
    if hands_on_enabled and hands_on_count > hands_on_available:
        hard_errors.append(
            f"Requested hands_on_count ({hands_on_count}) exceeds the "
            f"available hands-on pool ({hands_on_available})"
        )

    # Advisory only: a single-domain preflight cannot prove that a
    # multi-domain plan is jointly satisfiable when questions are shared.
    if descriptive_count > 0 and _count_shared_pool(
        "descriptive_questions", domain_id
    ) > 0:
        warnings.append(
            "Some descriptive questions are shared with other domains; the "
            "planner validates cross-domain feasibility when an assessment "
            "is created"
        )
    if (
        hands_on_enabled
        and hands_on_count > 0
        and _count_shared_pool("hands_on_questions", domain_id) > 0
    ):
        warnings.append(
            "Some hands-on challenges are shared with other domains; the "
            "planner validates cross-domain feasibility when an assessment "
            "is created"
        )

    return {
        "mcq_available": mcq_available,
        "mcq_required_semester": semester,
        "descriptive_available": descriptive_available,
        "hands_on_available": hands_on_available,
        "hard_errors": hard_errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_all_module_configs(admin: AuthUser = Depends(require_admin)):
    """List all module configurations with domain metadata.

    Returns an empty list when no configurations exist.
    """
    try:
        # Fetch all domains
        domains_resp = (
            supabase_client.table("domains")
            .select("id, name, slug, assessment_scope, is_active")
            .order("name")
            .execute()
        )
        domains = {d["id"]: d for d in (domains_resp.data or [])}

        # Fetch all module configs
        configs_resp = (
            supabase_client.table("assessment_module_config")
            .select("*")
            .execute()
        )

        # Group configs by domain_id
        configs_by_domain = {}
        for row in (configs_resp.data or []):
            did = row["domain_id"]
            configs_by_domain.setdefault(did, []).append(_config_row(row))

        result = []
        for domain_id, domain_row in domains.items():
            domain_configs = configs_by_domain.get(domain_id, [])
            result.append({
                "domain": _domain_info(domain_row),
                "configs": domain_configs,
            })

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{domain_id}")
def get_domain_module_config(
    domain_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Get module configuration for a specific domain.

    Returns domain info and any existing configurations.
    If no configuration exists, configs is an empty list.
    """
    try:
        domain_resp = (
            supabase_client.table("domains")
            .select("id, name, slug, assessment_scope, is_active")
            .eq("id", domain_id)
            .execute()
        )
        if not domain_resp.data:
            _domain_not_found(domain_id)

        domain_row = domain_resp.data[0]

        configs_resp = (
            supabase_client.table("assessment_module_config")
            .select("*")
            .eq("domain_id", domain_id)
            .execute()
        )

        configs = [_config_row(r) for r in (configs_resp.data or [])]

        return {
            "domain": _domain_info(domain_row),
            "configs": configs,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{domain_id}")
def upsert_domain_module_config(
    domain_id: str,
    payload: ModuleConfigUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Create or update a module configuration for a domain + tier.

    Upsert semantics: if a row already exists for (domain_id, applies_to),
    it is updated.  Otherwise a new row is created.

    Returns the resulting configuration plus preflight validation data.
    """
    try:
        # 1. Resolve domain
        domain_resp = (
            supabase_client.table("domains")
            .select("id, name, slug, assessment_scope, is_active")
            .eq("id", domain_id)
            .execute()
        )
        if not domain_resp.data:
            _domain_not_found(domain_id)

        domain_row = domain_resp.data[0]
        domain_scope = domain_row["assessment_scope"]

        # 2. Validate applies_to against domain scope
        allowed = SCOPE_ALLOWED_APPLIES_TO.get(domain_scope, [])
        if payload.applies_to not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"applies_to '{payload.applies_to}' is not valid for "
                    f"a '{domain_scope}' domain.  Allowed: {allowed}"
                ),
            )

        is_technical = domain_scope == "technical"

        # 3. FINAL core semantics, validated BEFORE any write so a rejected
        #    request never touches the database.
        #
        #    TECHNICAL: descriptive questions belong to the organizational
        #    assessment alone, so a technical row must configure none. The
        #    planner ignores the value regardless, but rejecting it here stops a
        #    meaningless configuration being authored in the first place.
        #    mcq_count stays accepted (and stored) but is unused, so it is
        #    deliberately NOT rejected: an author configuring a senior hands-on
        #    module should not have to satisfy an unrelated MCQ pool.
        #
        #    JUNIOR: the practical is a senior-only module. A junior row that
        #    enables hands-on would be silently inert at runtime, so it is
        #    refused loudly instead.
        if is_technical:
            if payload.descriptive_count != 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "descriptive_count must be 0 for a technical domain: "
                        "descriptive questions belong to the organizational "
                        "assessment only"
                    ),
                )
            if payload.applies_to == "junior" and payload.hands_on_enabled:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "hands-on is a senior-only practical; a junior "
                        "configuration cannot enable it"
                    ),
                )

        # 4. Validate counts and hands-on coupling (Pydantic already
        #    enforces non-negative and the disabled-coupling rules via
        #    model_post_init, but we double-check the coupling here for
        #    a clear HTTP error if the model validation is somehow bypassed.)
        if not payload.hands_on_enabled:
            if payload.hands_on_count != 0 or payload.hands_on_additional_minutes != 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "hands_on_count and hands_on_additional_minutes "
                        "must be 0 when hands_on_enabled is false"
                    ),
                )

        # 5. Read-only preflight.
        #
        # A per-domain pool shortage is a HARD failure: the configuration
        # could never be satisfied for this domain, so it must not be saved.
        # This check happens BEFORE any write, so a rejected request leaves
        # the database completely untouched.
        preflight = _build_preflight(
            domain_id=domain_id,
            applies_to=payload.applies_to,
            mcq_count=payload.mcq_count,
            descriptive_count=payload.descriptive_count,
            hands_on_enabled=payload.hands_on_enabled,
            hands_on_count=payload.hands_on_count,
            is_technical=is_technical,
        )
        if preflight["hard_errors"]:
            raise HTTPException(
                status_code=400,
                detail="; ".join(preflight["hard_errors"]),
            )

        # 6. Upsert the configuration row
        config_data = {
            "domain_id": domain_id,
            "applies_to": payload.applies_to,
            "mcq_count": payload.mcq_count,
            "descriptive_count": payload.descriptive_count,
            "hands_on_enabled": payload.hands_on_enabled,
            "hands_on_count": payload.hands_on_count,
            "hands_on_additional_minutes": payload.hands_on_additional_minutes,
            "notes": payload.notes,
        }

        # Check for existing row
        existing = (
            supabase_client.table("assessment_module_config")
            .select("id")
            .eq("domain_id", domain_id)
            .eq("applies_to", payload.applies_to)
            .execute()
        )

        if existing.data:
            # Update
            row_id = existing.data[0]["id"]
            result = (
                supabase_client.table("assessment_module_config")
                .update(config_data)
                .eq("id", row_id)
                .execute()
            )
        else:
            # Insert
            result = (
                supabase_client.table("assessment_module_config")
                .insert(config_data)
                .execute()
            )

        saved = result.data[0] if result.data else {**config_data, "id": None}

        return {
            "domain": _domain_info(domain_row),
            "config": _config_row(saved),
            "preflight": preflight,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
