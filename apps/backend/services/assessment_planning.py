"""Database resolution + orchestration for modular assessment planning.

This module is the ONLY bridge between the database and the pure planner in
``services.assessment_planner``. It:

    1. resolves the candidate's assessment programme (semester -> scope/tier),
    2. resolves the selected domains and their assessment_module_config rows,
    3. fetches the candidate-eligible content pools,
    4. hands everything to the pure planner and returns the frozen plan.

The planner itself stays free of database access: nothing here leaks into it,
and every value it receives is an already-resolved plain input model.

WHY THIS IS SEPARATE FROM THE ROUTER
    ``routers/assessment.py`` should stay an HTTP layer. All the query shapes
    and the planner wiring live here so the endpoint body stays small.

TECHNICAL MODULE CONFIGURATION IS OPTIONAL
    A technical assessment needs no module rows at all: its MCQ quantity is
    derived from ``assessment_program.mcq_total`` and the number of selected
    domains, its coding selection is global, and descriptive questions do not
    exist for it. Module rows exist only to switch on OPTIONAL modules (today
    just hands-on), so an unauthored matrix simply means no optional module is
    enabled. The organizational scope is the opposite: it derives its whole
    content from its module row, so a missing row is a hard 400.

LEGACY TECHNICAL FALLBACK (removed)
    The pre-modular bridge that fed the global ``assessment_config`` counts to
    the planner no longer exists: neither the ``LegacyTechnicalFallback`` input
    model nor ``build_legacy_technical_fallback`` is defined any more. Nothing
    derives technical MCQ or descriptive quantity from the global config — the
    derived programme rule replaced it and descriptive questions became
    organizational-only — so there is no path left that could mix the two
    models.

WHAT THIS MODULE DOES NOT DO
    - It never writes. The only write in the whole creation flow is the router's
      INSERT of the new assessment_attempt.
    - It never reads or writes ``assessment_config`` other than through the
      config dict its caller already fetched.
    - It never exposes the plan or its fingerprint to the candidate.
"""

import logging
import secrets

from fastapi import HTTPException
from pydantic import ValidationError

from core.supabase import supabase_client
from services.assessment_planner import (
    AssessmentPlan,
    AssessmentPlanRequest,
    AssessmentPlanningError,
    CodingPoolItem,
    ConfigFamily,
    DescriptivePoolItem,
    DomainInput,
    HandsOnPoolItem,
    MCQPoolItem,
    ModuleConfigInput,
    ProgramInput,
    Scope,
    assert_organizational_exclusive,
    assessment_mode_of,
    plan_assessment,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Programme resolution (semester -> scope / tier / max_domains)
# ---------------------------------------------------------------------------


def resolve_program(semester: int) -> ProgramInput:
    """Resolve the active assessment_program row for a candidate's semester.

    The database is the source of truth for semester -> scope/tier policy, so
    the router never hardcodes "semester 3 is junior". Raises 400 when no
    active programme exists (semester 7 is seeded with scope 'none' and is
    rejected separately by the caller / planner).
    """
    response = (
        supabase_client.table("assessment_program")
        .select(
            "semester, scope, tier, max_domains, coding_enabled, mcq_total"
        )
        .eq("semester", semester)
        .eq("is_active", True)
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No active assessment programme is configured for semester "
                f"{semester}"
            ),
        )
    try:
        return ProgramInput(**rows[0])
    except ValidationError as exc:
        logger.error(
            "Misconfigured assessment_program row for semester %s: %s", semester, exc
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"The assessment programme for semester {semester} is "
                f"misconfigured. Contact an administrator."
            ),
        ) from exc


def config_family_for(program: ProgramInput, mode=None):
    """The assessment_module_config.applies_to value for this assessment.

    technical      -> the programme's tier (junior / senior)
    organizational -> "organizational" (common, never semester-keyed)

    ``mode`` is the assessment MODE derived from the SELECTED domains
    (:func:`assessment_mode_of`), not the semester's default: a 3rd/5th
    semester candidate who chooses Organizational Roles gets the
    ``organizational`` family exactly like a 1st semester candidate. When no
    selection has resolved yet, ``mode`` is None and the programme's default
    decides (it only ever shapes a config query that will find nothing).

    Returns None when the family cannot resolve at all (a technical
    selection with no tier); the caller then skips the config query and the
    planner rejects the selection outright.
    """
    if mode is None:
        if program.scope is Scope.NONE:
            return None
        mode = (
            Scope.ORGANIZATIONAL
            if program.scope is Scope.ORGANIZATIONAL
            else Scope.TECHNICAL
        )
    if mode is Scope.TECHNICAL:
        return program.tier.value if program.tier is not None else None
    if mode is Scope.ORGANIZATIONAL:
        return ConfigFamily.ORGANIZATIONAL.value
    return None


# ---------------------------------------------------------------------------
# Domain + module configuration resolution
# ---------------------------------------------------------------------------


def load_domain_catalogue(domain_ids) -> list:
    """Load the requested domains for the planner to validate.

    Deliberately NOT filtered by is_active or assessment_scope: the planner is
    the single authority on eligibility, and handing it the raw rows lets it
    distinguish "does not exist" from "inactive" from "wrong scope" instead of
    collapsing all three into a missing row.
    """
    if not domain_ids:
        return []
    response = (
        supabase_client.table("domains")
        .select("id, name, slug, assessment_scope, is_active")
        .in_("id", list(domain_ids))
        .execute()
    )
    catalogue = []
    for row in response.data or []:
        try:
            catalogue.append(DomainInput(**row))
        except ValidationError as exc:
            logger.error("Misconfigured domains row %s: %s", row.get("id"), exc)
            raise HTTPException(
                status_code=400,
                detail=(
                    "A selected domain is misconfigured (missing assessment "
                    "scope). Contact an administrator."
                ),
            ) from exc
    return catalogue


def load_module_configs(domain_ids, family) -> list:
    """Load assessment_module_config rows for the selected domains + family."""
    if not domain_ids or not family:
        return []
    response = (
        supabase_client.table("assessment_module_config")
        .select(
            "domain_id, applies_to, mcq_count, descriptive_count, "
            "hands_on_enabled, hands_on_count, hands_on_additional_minutes"
        )
        .in_("domain_id", list(domain_ids))
        .eq("applies_to", family)
        .execute()
    )
    # hands_on_module is added by a later migration and may not exist yet in
    # every environment. Absent column -> None -> the planner's legacy
    # fallback (per-challenge deduplication) applies, so un-migrated
    # databases keep their exact current behaviour.
    rows = []
    for row in response.data or []:
        rows.append(
            ModuleConfigInput(
                **{**row, "hands_on_module": row.get("hands_on_module") or ""}
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Content pools
# ---------------------------------------------------------------------------


def load_mcq_pool(domain_ids, semester) -> list:
    """The candidate-eligible MCQ pool for every selected domain at once.

    Preserves the existing semester-aware selection model exactly — MCQs are
    filtered by the candidate's semester AND is_active AND one of the selected
    domains. `domain_id` is selected so each pool item carries the domain it
    genuinely belongs to (mcq_questions.domain_id is a single FK, so ids are
    unique across domains).
    """
    if not domain_ids:
        return []
    response = (
        supabase_client.table("mcq_questions")
        .select("id, domain_id")
        .eq("semester", semester)
        .eq("is_active", True)
        .in_("domain_id", list(domain_ids))
        .execute()
    )
    # semester / is_active are guaranteed by the query itself.
    return [
        MCQPoolItem(
            id=row["id"],
            domain_id=row["domain_id"],
            semester=semester,
            is_active=True,
        )
        for row in response.data or []
    ]


def load_descriptive_pool(domain_ids) -> list:
    """Active descriptive questions overlapping any selected domain.

    domain_ids is an ARRAY on this table, so a question can be eligible for
    several domains at once. Cross-domain uniqueness is the planner's job.
    """
    if not domain_ids:
        return []
    response = (
        supabase_client.table("descriptive_questions")
        .select("id, domain_ids")
        .eq("is_active", True)
        .overlaps("domain_ids", list(domain_ids))
        .execute()
    )
    return [
        DescriptivePoolItem(
            id=row["id"], domain_ids=row.get("domain_ids") or [], is_active=True
        )
        for row in response.data or []
    ]


def load_hands_on_pool(domain_ids) -> list:
    """Active hands-on challenges overlapping any selected domain."""
    if not domain_ids:
        return []
    response = (
        supabase_client.table("hands_on_questions")
        .select("id, domain_ids, challenge_type")
        .eq("is_active", True)
        .overlaps("domain_ids", list(domain_ids))
        .execute()
    )
    # challenge_type is the challenge module the row runs (the SQL challenge
    # today). The planner groups by module so the same module on several
    # selected domains deduplicates to one shared requirement group.
    return [
        HandsOnPoolItem(
            id=row["id"],
            domain_ids=row.get("domain_ids") or [],
            hands_on_modules=[row.get("challenge_type") or ""],
            is_active=True,
        )
        for row in response.data or []
    ]


def load_coding_pool() -> list:
    """The GLOBAL active coding problem pool. No domain filtering, ever."""
    response = (
        supabase_client.table("coding_problems")
        .select("id")
        .eq("is_active", True)
        .execute()
    )
    return [CodingPoolItem(id=row["id"], is_active=True) for row in response.data or []]


def generate_seed() -> int:
    """A server-side planner seed.

    Never accepted from the candidate, never persisted. It only varies WHICH of
    several valid selections a candidate receives; identical inputs plus an
    identical seed always reproduce the same plan.
    """
    return secrets.randbits(63)


def _pool_required(modular_counts) -> bool:
    """Whether a descriptive/hands-on pool fetch can possibly be needed.

    Module configuration is the ONLY thing that can request items from these
    pools, so a zero quota in every relevant row means the planner cannot ask
    for anything and the query is skipped — preserving the existing behaviour
    of not querying a section that is switched off. Anything else fetches
    conservatively: the planner remains the authority on how many of the
    fetched items are actually used, and it fails loudly on a shortfall.
    """
    return any(count > 0 for count in modular_counts)


# ---------------------------------------------------------------------------
# Planner orchestration
# ---------------------------------------------------------------------------


def _planning_refusal(
    exc: AssessmentPlanningError, semester: int, domain_ids
) -> HTTPException:
    """Map a planner refusal onto the candidate-facing 400.

    Planner details are safe candidate-facing text (domain names, counts,
    reasons) — they never contain answers, flags, scores or remarks.
    """
    logger.warning(
        "Assessment planning refused [%s] semester=%s domains=%s: %s",
        exc.kind.value,
        semester,
        domain_ids,
        exc.detail,
    )
    return HTTPException(status_code=400, detail=exc.detail)


def plan_new_attempt(
    *, config: dict, semester: int, requested_domain_ids
) -> AssessmentPlan:
    """Resolve a frozen AssessmentPlan for a NEW attempt.

    Only ever called on the new-attempt path. Resuming an existing attempt must
    NOT call this: an in-progress attempt is returned exactly as frozen.
    """
    domain_ids = list(requested_domain_ids)

    # 1. Semester -> programme (scope / tier / max_domains / coding_enabled).
    program = resolve_program(semester)

    # Semester 7 is seeded with scope 'none'. Reject before any further work.
    if program.scope is Scope.NONE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"No assessment is configured for semester {semester}. "
                f"Nothing can be started for this candidate."
            ),
        )

    # 2. Domain catalogue, then the selection rule.
    #
    # The Organizational domain is mutually exclusive with every other domain,
    # so a mixed selection is refused BEFORE any module configuration or content
    # pool is loaded: an invalid combination must never reach question selection,
    # and must not cost pool queries either. The planner re-asserts the same rule
    # (see assert_organizational_exclusive), so no caller can bypass it.
    domains = load_domain_catalogue(domain_ids)
    try:
        assert_organizational_exclusive(domains)
    except AssessmentPlanningError as exc:
        raise _planning_refusal(exc, semester, domain_ids) from exc

    # The ASSESSMENT MODE comes from the domains the candidate selected, never
    # from their semester: a technical programme may still be taken as the
    # standalone Organizational assessment, and that choice decides the
    # module-config family, whether descriptive questions are in scope, and
    # whether coding applies.
    mode = assessment_mode_of(domains)

    # 3. Per-domain module configuration for this assessment's family.
    #
    # For a technical selection these rows only switch on OPTIONAL modules, so
    # the result may legitimately be empty or partial. For the organizational
    # mode the row is the source of the assessment's content and a missing one
    # makes the planner refuse the plan.
    family = config_family_for(program, mode)
    module_configs = load_module_configs(domain_ids, family)

    # 4. Global, module-independent values.
    coding_problem_count = int(config.get("coding_problem_count", 0) or 0)
    coding_enabled = bool(program.coding_enabled) and mode is Scope.TECHNICAL

    # 5. Build the planner input. The planner performs no database access.
    request = AssessmentPlanRequest(
        program=program,
        requested_domain_ids=domain_ids,
        domains=domains,
        module_configs=module_configs,
        base_duration_minutes=int(config["duration_minutes"]),
        global_coding_problem_count=coding_problem_count,
        mcq_pool=load_mcq_pool(domain_ids, semester),
        # Descriptive questions exist for the ORGANIZATIONAL assessment only, so
        # a technical attempt never even queries the pool. That is stricter than
        # the old "skip when every configured count is zero" rule and removes
        # any chance of a technical assessment acquiring descriptive content.
        descriptive_pool=(
            load_descriptive_pool(domain_ids)
            if mode is Scope.ORGANIZATIONAL
            and _pool_required([c.descriptive_count for c in module_configs])
            else []
        ),
        # The module row is the only switch that can request hands-on content,
        # so a count of zero in every ENABLED row means the pool query is
        # skipped.
        hands_on_pool=(
            load_hands_on_pool(domain_ids)
            if _pool_required(
                [c.hands_on_count for c in module_configs if c.hands_on_enabled]
            )
            else []
        ),
        coding_pool=(
            load_coding_pool() if coding_enabled and coding_problem_count > 0 else []
        ),
        # Optional proctoring policy, frozen into the plan snapshot for this
        # attempt (see migration 023). Absent column / absent key -> False, so a
        # database that has not had migration 023 applied, and every attempt
        # created before this feature, keep monitoring strictly disabled.
        network_integrity_monitoring=bool(config.get("network_integrity_monitoring", False)),
        seed=generate_seed(),
    )

    try:
        return plan_assessment(request)
    except AssessmentPlanningError as exc:
        raise _planning_refusal(exc, semester, domain_ids) from exc
