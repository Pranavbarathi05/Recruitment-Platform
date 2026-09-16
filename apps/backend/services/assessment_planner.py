"""Pure assessment planner for the modular assessment architecture.

WHAT THIS MODULE IS
    A deterministic, side-effect-free function that turns already-resolved
    inputs (candidate program, selected domains, module configuration and
    candidate-eligible content pools) into a single frozen assessment plan:

        inputs -> plan_assessment() -> AssessmentPlan

    It is the planning half of the approved architecture:

        Candidate semester
            -> assessment_program        (scope / tier / max_domains)
            -> selected domains          (validated + deterministically ordered)
            -> assessment_module_config  (per-domain counts + additional time)
            -> AssessmentPlan            (frozen, ready to persist)

WHAT THIS MODULE DELIBERATELY IS NOT
    - It performs NO database access. It does not import the Supabase client,
      fastapi, psycopg or anything that can reach a database, and it never
      reads live configuration itself. Callers resolve rows and pass them in.
    - It writes NOTHING. It never inserts or updates an attempt.
    - It is NOT wired into any endpoint. Phase 3 delivers the planner and its
      tests only; POST /assessment/start still uses the legacy inline
      selection logic and is unchanged.
    - It exposes no secret: no correct answers, explanations, scores, hidden
      test cases, hands-on expected flags or admin remarks ever enter the
      output. Input models ignore unknown fields, so a raw Supabase row
      (which is usually SELECT *) can be passed straight in without leaking.

DETERMINISM
    Identical inputs always produce an identical plan. Selection never
    depends on Python set iteration order or on the order rows came back from
    the database: candidates are always sorted by id first, and domains are
    always processed in a stable (name, id) order.

    Selection is additionally parameterisable by an optional integer `seed`.
    With no seed the planner takes the lowest-sorted eligible ids, which is
    fully reproducible. With a seed it draws via random.Random(seed), which is
    still deterministic for identical inputs while letting the caller vary
    which questions a candidate receives. The seed is NOT part of the
    configuration fingerprint: it changes *which* questions are drawn, not the
    configuration that governs the assessment.

EXACT ALLOCATION (descriptive + hands-on)
    Per-domain descriptive and hands-on quotas are NOT filled greedily. A
    shared question (one whose domain_ids spans several selected domains) can
    satisfy only ONE of them, so the planner solves the whole quota set as a
    bipartite matching and re-assigns already-placed questions when that is
    what it takes to place a later one. It therefore refuses a configuration
    only when no valid allocation exists at all — never merely because the
    domains happened to be processed in an unlucky order.
"""

import hashlib
import json
import random
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# Bumped whenever the plan's shape or resolution rules change in a way that
# makes an older frozen plan interpret differently.
PLAN_VERSION = 1


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


class Scope(str, Enum):
    """assessment_program.scope — what kind of assessment a semester gets."""

    ORGANIZATIONAL = "organizational"
    TECHNICAL = "technical"
    NONE = "none"


class Tier(str, Enum):
    """assessment_program.tier — the technical configuration family."""

    JUNIOR = "junior"
    SENIOR = "senior"


class ConfigFamily(str, Enum):
    """assessment_module_config.applies_to — which config row to resolve."""

    JUNIOR = "junior"
    SENIOR = "senior"
    ORGANIZATIONAL = "organizational"


class DomainScope(str, Enum):
    """domains.assessment_scope — what kind of assessment a domain belongs to."""

    TECHNICAL = "technical"
    ORGANIZATIONAL = "organizational"


class ConfigSource(str, Enum):
    """Where the resolved module counts came from.

    MODULAR is the target architecture. LEGACY_TECHNICAL_FALLBACK is the
    approved TEMPORARY bridge for technical assessments whose module rows have
    not been authored yet. Organizational assessments have NO fallback.
    """

    MODULAR = "modular"
    LEGACY_TECHNICAL_FALLBACK = "legacy_technical_fallback"


class PlanningErrorKind(str, Enum):
    """Machine-checkable reason a plan could not be produced."""

    NO_ASSESSMENT = "no_assessment"
    INVALID_PROGRAM = "invalid_program"
    INVALID_DOMAIN_SELECTION = "invalid_domain_selection"
    DOMAIN_NOT_FOUND = "domain_not_found"
    DOMAIN_INACTIVE = "domain_inactive"
    WRONG_DOMAIN_SCOPE = "wrong_domain_scope"
    DUPLICATE_DOMAINS = "duplicate_domains"
    MISSING_MODULE_CONFIG = "missing_module_config"
    INVALID_MODULE_CONFIG = "invalid_module_config"
    INSUFFICIENT_MCQ_POOL = "insufficient_mcq_pool"
    INSUFFICIENT_DESCRIPTIVE_POOL = "insufficient_descriptive_pool"
    INSUFFICIENT_HANDS_ON_POOL = "insufficient_hands_on_pool"
    INSUFFICIENT_CODING_POOL = "insufficient_coding_pool"


class AssessmentPlanningError(Exception):
    """Raised when a valid plan cannot be produced.

    Follows the project's service-level exception convention (compare
    services.compiler.CompilerError). Errors are never swallowed and
    configuration is never silently repaired or reduced — the caller decides
    how to surface a failure (the routers map it to HTTP 400).
    """

    def __init__(self, kind: PlanningErrorKind, detail: str):
        self.kind = kind
        self.detail = detail
        super().__init__(f"[{kind.value}] {detail}")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
# All input models ignore unknown fields. This is a deliberate safety property:
# callers routinely hold Supabase rows fetched with SELECT *, which contain
# correct_option / explanation / expected_flag / scores. Those never reach the
# plan because they are dropped at the boundary.


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ProgramInput(_Input):
    """One assessment_program row (migration 014)."""

    semester: int
    scope: Scope
    tier: Optional[Tier] = None
    max_domains: int
    coding_enabled: bool = False


class DomainInput(_Input):
    """One domains row (migration 001 + assessment_scope from 015)."""

    id: str
    name: str
    slug: str = ""
    assessment_scope: DomainScope
    is_active: bool = True


class ModuleConfigInput(_Input):
    """One assessment_module_config row (migration 016)."""

    domain_id: str
    applies_to: ConfigFamily
    mcq_count: int = 0
    descriptive_count: int = 0
    hands_on_enabled: bool = False
    hands_on_count: int = 0
    hands_on_additional_minutes: int = 0


class LegacyTechnicalFallback(_Input):
    """The pre-modular GLOBAL counts, for TECHNICAL scopes only.

    Mirrors the legacy assessment_config columns exactly, because the legacy
    aggregation is global rather than per-domain:
      - total_questions is split evenly across the selected domains
        (and must be even when two domains are selected),
      - descriptive_question_count / hands_on_question_count are a SINGLE
        count drawn from the union of the selected domains' pools.

    Passing this is an explicit opt-in. It is refused for organizational
    assessments, which must never inherit technical/global behaviour.
    """

    total_questions: int
    descriptive_question_count: int = 0
    hands_on_question_count: int = 0


class MCQPoolItem(_Input):
    """One candidate-eligible mcq_questions row: single domain, single semester."""

    id: str
    domain_id: str
    semester: int
    is_active: bool = True


class DescriptivePoolItem(_Input):
    """One descriptive_questions row. domain_ids is an ARRAY (may overlap)."""

    id: str
    domain_ids: list[str] = Field(default_factory=list)
    is_active: bool = True


class HandsOnPoolItem(_Input):
    """One hands_on_questions row. domain_ids is an ARRAY (may overlap)."""

    id: str
    domain_ids: list[str] = Field(default_factory=list)
    is_active: bool = True


class CodingPoolItem(_Input):
    """One coding_problems row. Coding is GLOBAL and domain-independent."""

    id: str
    is_active: bool = True


class AssessmentPlanRequest(_Input):
    """Everything the planner needs. Supplied by the caller; never queried."""

    program: ProgramInput
    requested_domain_ids: list[str]
    domains: list[DomainInput]

    # Zero or more assessment_module_config rows. Resolution is all-or-nothing:
    # every selected domain must have a row for its configuration family, or
    # the plan falls back (technical only) / fails.
    module_configs: list[ModuleConfigInput] = Field(default_factory=list)

    # Explicit opt-in legacy bridge. Only honoured for scope=technical, and
    # only when modular configuration is unavailable.
    legacy_technical_fallback: Optional[LegacyTechnicalFallback] = None

    # Global, module-independent values (assessment_config.duration_minutes and
    # assessment_config.coding_problem_count). Coding count stays global by
    # design and is never per-domain.
    base_duration_minutes: int = Field(..., gt=0)
    global_coding_problem_count: int = Field(default=0, ge=0)

    # Candidate-eligible content pools.
    mcq_pool: list[MCQPoolItem] = Field(default_factory=list)
    descriptive_pool: list[DescriptivePoolItem] = Field(default_factory=list)
    hands_on_pool: list[HandsOnPoolItem] = Field(default_factory=list)
    coding_pool: list[CodingPoolItem] = Field(default_factory=list)

    # None -> take the lowest-sorted eligible ids (fully reproducible).
    # An int -> draw with random.Random(seed), still deterministic per seed.
    seed: Optional[int] = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class DomainPlanEntry(BaseModel):
    """The resolved module configuration for ONE selected domain.

    In MODULAR plans these counts are the authored per-domain config, and the
    mcq/descriptive/hands-on counts sum to the plan totals (descriptive and
    hands-on after cross-domain deduplication).

    In LEGACY_TECHNICAL_FALLBACK plans there is no per-domain configuration:
    only mcq_count is meaningful (the even split of the global total). The
    descriptive and hands-on columns are reported as 0 because the legacy
    counts are global and cannot be attributed to one domain; the plan-level
    totals remain authoritative.
    """

    model_config = ConfigDict(frozen=True)

    domain_id: str
    domain_name: str
    domain_slug: str
    config_applies_to: Optional[ConfigFamily] = None
    mcq_count: int = 0
    descriptive_count: int = 0
    hands_on_enabled: bool = False
    hands_on_count: int = 0
    hands_on_additional_minutes: int = 0


class AssessmentPlan(BaseModel):
    """A frozen, serialisable assessment plan.

    This is an INTERNAL planning object. It carries only ids, counts and
    durations — never correct answers, explanations, scores, hidden tests,
    hands-on expected flags or admin remarks.
    """

    model_config = ConfigDict(frozen=True)

    plan_version: int
    semester: int
    scope: Scope
    tier: Optional[Tier] = None
    max_domains: int
    config_source: ConfigSource

    domain_ids: list[str]
    domains: list[DomainPlanEntry]

    selected_mcq_ids: list[str]
    selected_descriptive_question_ids: list[str]
    selected_hands_on_question_ids: list[str]
    selected_coding_problem_ids: list[str]

    coding_enabled: bool
    coding_count: int

    mcq_total: int
    descriptive_total: int
    hands_on_total: int
    coding_total: int

    base_duration_minutes: int
    additional_minutes: int
    duration_minutes: int

    # Stable digest of the CONFIGURATION that produced this plan. Not affected
    # by which questions were drawn, or by `seed`.
    config_fingerprint: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dedupe_by_id(items):
    """Return items with duplicate ids removed, preserving input order."""
    seen = {}
    for item in items:
        if item.id not in seen:
            seen[item.id] = item
    return list(seen.values())


def _pick(candidates, count, rng):
    """Choose exactly `count` ids from a sorted candidate id list.

    rng is None  -> the lowest-sorted ids (fully reproducible).
    rng is given -> rng.sample, then sorted, so the drawn SET varies per seed
                    while the emitted order stays stable.
    """
    if count <= 0:
        return []
    if rng is None:
        return list(candidates[:count])
    return sorted(rng.sample(list(candidates), count))


def _candidate_order(question_ids, rng):
    """The order in which the allocator considers candidate ids for a domain.

    Sorted when no seed is given; a seed-derived permutation otherwise. A seed
    therefore changes WHICH of several equally valid allocations is chosen,
    without making the allocator itself non-deterministic.
    """
    ordered = sorted(question_ids)
    if rng is not None:
        rng.shuffle(ordered)
    return ordered


def _allocate_quotas(domain_order, quotas, eligible_by_domain):
    """Exactly allocate unique question ids to domains, or return None.

    Solved as a maximum bipartite matching: each domain is expanded into
    `quota` unit slots, a slot may be filled by any question eligible for its
    domain, and every question may fill at most one slot overall. Kuhn's
    augmenting-path algorithm finds the matching, and re-assigns a
    question that is already placed whenever that is what it takes to place a
    later one.

    Returns {domain_id: [question_id, ...]} holding exactly quotas[domain_id]
    ids per domain with no id repeated anywhere, or None when no such
    allocation exists at all.

    Unlike a single greedy pass in domain order, this cannot fail while a valid
    assignment exists: by the augmenting-path theorem the matching it settles on
    is maximum, so an unfilled slot is proof that no complete allocation exists.
    Every iteration runs over a fixed order and the recursion carries no
    randomness, so identical inputs always yield an identical allocation.
    Recursion depth is bounded by the number of slots (the sum of the quotas),
    which is a handful in practice.
    """
    slots = [
        (domain_id, index)
        for domain_id in domain_order
        for index in range(quotas.get(domain_id, 0))
    ]
    if not slots:
        return {domain_id: [] for domain_id in domain_order}

    match_question = {}  # question_id -> the slot index currently holding it
    match_slot = {}  # slot index -> question_id

    def augment(slot_index, visited):
        domain_id = slots[slot_index][0]
        for question_id in eligible_by_domain.get(domain_id, ()):
            if question_id in visited:
                continue
            visited.add(question_id)
            holder = match_question.get(question_id)
            if holder is None or augment(holder, visited):
                match_question[question_id] = slot_index
                match_slot[slot_index] = question_id
                return True
        return False

    for slot_index in range(len(slots)):
        if not augment(slot_index, set()):
            return None

    allocation = {domain_id: [] for domain_id in domain_order}
    for slot_index, question_id in match_slot.items():
        allocation[slots[slot_index][0]].append(question_id)
    for question_ids in allocation.values():
        question_ids.sort()
    return allocation


def _allocation_error(kind, label, selected, quotas, eligible_by_domain):
    """Build the loud failure for a genuinely infeasible quota set."""
    union = set()
    for question_ids in eligible_by_domain.values():
        union.update(question_ids)
    summary = ", ".join(
        f"{domain.name}={quotas.get(domain.id, 0)}" for domain in selected
    )
    return AssessmentPlanningError(
        kind,
        f"No valid allocation of {label} exists for the selected domains: "
        f"they require {sum(quotas.values())} unique item(s) in total "
        f"({summary}), but only {len(union)} unique eligible item(s) remain "
        f"after cross-domain deduplication",
    )


def _legacy_union_selection(pool, selected, need, rng, kind, label):
    """Legacy global behaviour: ONE count from the union of eligible items."""
    union = sorted(
        item.id
        for item in pool
        if item.is_active and any(domain.id in item.domain_ids for domain in selected)
    )
    if len(union) < need:
        raise AssessmentPlanningError(
            kind,
            f"Only {len(union)} active {label} available for the selected "
            f"domains, need {need}",
        )
    return _pick(union, need, rng)


def _family_for(program: ProgramInput) -> ConfigFamily:
    """The assessment_module_config.applies_to family for this program."""
    if program.scope is Scope.TECHNICAL:
        if program.tier is None:
            raise AssessmentPlanningError(
                PlanningErrorKind.INVALID_PROGRAM,
                f"Semester {program.semester} has scope 'technical' but no tier",
            )
        return ConfigFamily(program.tier.value)
    return ConfigFamily.ORGANIZATIONAL


def _validate_module_config(config: ModuleConfigInput, domain: DomainInput) -> None:
    """Reject config that migration 016 would have rejected.

    Invalid configuration fails rather than being silently corrected, so a bad
    row can never quietly change what a candidate receives.
    """
    where = f"domain '{domain.name}' / {config.applies_to.value}"
    for label, value in (
        ("mcq_count", config.mcq_count),
        ("descriptive_count", config.descriptive_count),
        ("hands_on_count", config.hands_on_count),
        ("hands_on_additional_minutes", config.hands_on_additional_minutes),
    ):
        if value < 0:
            raise AssessmentPlanningError(
                PlanningErrorKind.INVALID_MODULE_CONFIG,
                f"{where}: {label} is negative ({value})",
            )
    if not config.hands_on_enabled:
        if config.hands_on_count != 0:
            raise AssessmentPlanningError(
                PlanningErrorKind.INVALID_MODULE_CONFIG,
                f"{where}: hands_on disabled but hands_on_count is "
                f"{config.hands_on_count} (must be 0)",
            )
        if config.hands_on_additional_minutes != 0:
            raise AssessmentPlanningError(
                PlanningErrorKind.INVALID_MODULE_CONFIG,
                f"{where}: hands_on disabled but hands_on_additional_minutes "
                f"is {config.hands_on_additional_minutes} (must be 0)",
            )


def _fingerprint(payload: dict) -> str:
    """SHA-256 over a canonical JSON encoding of the planning configuration."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def plan_assessment(request: AssessmentPlanRequest) -> AssessmentPlan:
    """Resolve a frozen AssessmentPlan from already-fetched inputs.

    Raises AssessmentPlanningError (never HTTPException, never a DB call) when
    no valid plan exists. Selection never truncates a requested count and never
    tops up from another domain: if the pool cannot satisfy a quota, the plan
    is refused outright.
    """
    program = request.program

    # -- 1. Program ---------------------------------------------------------
    if program.scope is Scope.NONE:
        raise AssessmentPlanningError(
            PlanningErrorKind.NO_ASSESSMENT,
            f"Semester {program.semester} has scope 'none' — no assessment "
            f"is planned for this candidate",
        )

    is_technical = program.scope is Scope.TECHNICAL
    expected_domain_scope = (
        DomainScope.TECHNICAL if is_technical else DomainScope.ORGANIZATIONAL
    )
    family = _family_for(program)

    # -- 2. Domain selection ------------------------------------------------
    requested = list(request.requested_domain_ids)
    if len(requested) < 1:
        raise AssessmentPlanningError(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            "At least one domain must be selected",
        )
    # The organizational assessment is exactly-one-domain by definition. This
    # is asserted explicitly rather than left to max_domains, so the rule holds
    # even if a program row is misconfigured.
    if not is_technical and len(requested) > 1:
        raise AssessmentPlanningError(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            f"The {program.scope.value} assessment allows exactly one domain "
            f"(got {len(requested)})",
        )
    if len(requested) > program.max_domains:
        raise AssessmentPlanningError(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            f"Select between 1 and {program.max_domains} domains "
            f"(got {len(requested)})",
        )
    if len(set(requested)) != len(requested):
        raise AssessmentPlanningError(
            PlanningErrorKind.DUPLICATE_DOMAINS,
            f"Duplicate domain ids in selection: {requested}",
        )

    catalogue = {domain.id: domain for domain in request.domains}
    selected = []
    for domain_id in requested:
        domain = catalogue.get(domain_id)
        if domain is None:
            raise AssessmentPlanningError(
                PlanningErrorKind.DOMAIN_NOT_FOUND,
                f"Domain '{domain_id}' does not exist",
            )
        if not domain.is_active:
            raise AssessmentPlanningError(
                PlanningErrorKind.DOMAIN_INACTIVE,
                f"Domain '{domain.name}' is inactive",
            )
        if domain.assessment_scope is not expected_domain_scope:
            raise AssessmentPlanningError(
                PlanningErrorKind.WRONG_DOMAIN_SCOPE,
                f"Domain '{domain.name}' has assessment_scope "
                f"'{domain.assessment_scope.value}' but the "
                f"'{program.scope.value}' assessment requires "
                f"'{expected_domain_scope.value}'",
            )
        selected.append(domain)

    # Deterministic order: (name, id). Matches the project's convention of
    # ordering domains by name, and removes any dependence on the order the
    # caller happened to fetch or pass them in.
    selected.sort(key=lambda domain: (domain.name, domain.id))

    # -- 3. Resolve module configuration -----------------------------------
    configs_by_key = {}
    for config in request.module_configs:
        key = (config.domain_id, config.applies_to)
        if key in configs_by_key:
            raise AssessmentPlanningError(
                PlanningErrorKind.INVALID_MODULE_CONFIG,
                f"Duplicate module configuration for domain "
                f"'{config.domain_id}' / {config.applies_to.value}",
            )
        configs_by_key[key] = config

    resolved = {}
    missing = []
    for domain in selected:
        config = configs_by_key.get((domain.id, family))
        if config is None:
            missing.append(domain)
        else:
            _validate_module_config(config, domain)
            resolved[domain.id] = config

    legacy = None
    if missing:
        # Resolution is all-or-nothing. A partially authored tier must not
        # produce a hybrid plan that mixes per-domain counts with global ones.
        if not is_technical:
            raise AssessmentPlanningError(
                PlanningErrorKind.MISSING_MODULE_CONFIG,
                f"No '{family.value}' configuration for domain(s) "
                f"{[d.name for d in missing]}; the organizational assessment "
                f"has no legacy fallback",
            )
        if request.legacy_technical_fallback is None:
            raise AssessmentPlanningError(
                PlanningErrorKind.MISSING_MODULE_CONFIG,
                f"No '{family.value}' configuration for domain(s) "
                f"{[d.name for d in missing]} and no technical legacy "
                f"fallback was supplied",
            )
        legacy = request.legacy_technical_fallback

    config_source = (
        ConfigSource.LEGACY_TECHNICAL_FALLBACK
        if legacy is not None
        else ConfigSource.MODULAR
    )
    rng = random.Random(request.seed) if request.seed is not None else None

    # -- 4. MCQ: per domain, semester-aware ---------------------------------
    mcq_pool = _dedupe_by_id(request.mcq_pool)
    selected_mcq_ids = []
    per_domain_mcq = {}

    if legacy is not None:
        # Legacy global behaviour: split the single global total across the
        # selected domains, requiring an even total for a two-domain split
        # (identical to the existing engine's rule).
        if len(selected) == 1:
            per_domain_mcq[selected[0].id] = legacy.total_questions
        else:
            if legacy.total_questions % 2 != 0:
                raise AssessmentPlanningError(
                    PlanningErrorKind.INVALID_MODULE_CONFIG,
                    f"Legacy total_questions ({legacy.total_questions}) must be "
                    f"even for a {len(selected)}-domain split",
                )
            for domain in selected:
                per_domain_mcq[domain.id] = legacy.total_questions // len(selected)
    else:
        for domain in selected:
            per_domain_mcq[domain.id] = resolved[domain.id].mcq_count

    for domain in selected:
        need = per_domain_mcq[domain.id]
        if need == 0:
            continue
        eligible = sorted(
            item.id
            for item in mcq_pool
            if item.is_active
            and item.semester == program.semester
            and item.domain_id == domain.id
        )
        if len(eligible) < need:
            raise AssessmentPlanningError(
                PlanningErrorKind.INSUFFICIENT_MCQ_POOL,
                f"Domain '{domain.name}' (Semester {program.semester}) has "
                f"only {len(eligible)} active MCQ questions, need {need}",
            )
        selected_mcq_ids.extend(_pick(eligible, need, rng))

    # Final MCQ ordering: shuffle across domains so questions from different
    # domains are interleaved rather than grouped. With a seed this uses the
    # same RNG for reproducibility; without a seed the lowest-sorted order
    # from _pick is kept as-is (fully deterministic).
    if rng is not None and selected_mcq_ids:
        rng.shuffle(selected_mcq_ids)

    # -- 5. Descriptive: exact cross-domain allocation -----------------------
    desc_pool = _dedupe_by_id(request.descriptive_pool)
    selected_descriptive_ids = []
    per_domain_descriptive = {}

    if legacy is not None:
        # Legacy global behaviour: ONE count drawn from the union of the
        # selected domains' eligible questions.
        selected_descriptive_ids = _legacy_union_selection(
            desc_pool,
            selected,
            legacy.descriptive_question_count,
            rng,
            PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL,
            "descriptive questions",
        )
    else:
        quotas = {d.id: resolved[d.id].descriptive_count for d in selected}
        eligible = {
            d.id: _candidate_order(
                (
                    item.id
                    for item in desc_pool
                    if item.is_active and d.id in item.domain_ids
                ),
                rng,
            )
            for d in selected
        }
        allocation = _allocate_quotas([d.id for d in selected], quotas, eligible)
        if allocation is None:
            raise _allocation_error(
                PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL,
                "descriptive question(s)",
                selected,
                quotas,
                eligible,
            )
        for domain in selected:
            per_domain_descriptive[domain.id] = quotas[domain.id]
            selected_descriptive_ids.extend(allocation[domain.id])

    # -- 6. Hands-on: exact cross-domain allocation --------------------------
    hands_pool = _dedupe_by_id(request.hands_on_pool)
    selected_hands_on_ids = []
    per_domain_hands_on = {}
    additional_minutes = 0

    if legacy is not None:
        # Legacy has no hands-on additional-time concept at all: total time is
        # the base duration, exactly as today.
        selected_hands_on_ids = _legacy_union_selection(
            hands_pool,
            selected,
            legacy.hands_on_question_count,
            rng,
            PlanningErrorKind.INSUFFICIENT_HANDS_ON_POOL,
            "hands-on challenges",
        )
        for domain in selected:
            per_domain_hands_on[domain.id] = (False, 0, 0)
    else:
        quotas = {
            d.id: (
                resolved[d.id].hands_on_count if resolved[d.id].hands_on_enabled else 0
            )
            for d in selected
        }
        eligible = {
            d.id: _candidate_order(
                (
                    item.id
                    for item in hands_pool
                    if item.is_active and d.id in item.domain_ids
                ),
                rng,
            )
            for d in selected
        }
        allocation = _allocate_quotas([d.id for d in selected], quotas, eligible)
        if allocation is None:
            raise _allocation_error(
                PlanningErrorKind.INSUFFICIENT_HANDS_ON_POOL,
                "hands-on challenge(s)",
                selected,
                quotas,
                eligible,
            )
        for domain in selected:
            config = resolved[domain.id]
            if not config.hands_on_enabled:
                # Disabled: contributes no challenges AND no time.
                per_domain_hands_on[domain.id] = (False, 0, 0)
                continue
            selected_hands_on_ids.extend(allocation[domain.id])
            # Additional time belongs to the module that carries it, so it is
            # summed only for ENABLED hands-on modules.
            additional_minutes += config.hands_on_additional_minutes
            per_domain_hands_on[domain.id] = (
                True,
                config.hands_on_count,
                config.hands_on_additional_minutes,
            )

    # -- 7. Coding: GLOBAL and domain-independent ---------------------------
    # Organizational and "none" scopes never carry coding, regardless of what
    # program.coding_enabled says.
    coding_enabled = bool(is_technical and program.coding_enabled)
    coding_count = request.global_coding_problem_count if coding_enabled else 0

    selected_coding_ids = []
    if coding_count > 0:
        coding_eligible = sorted(
            item.id for item in _dedupe_by_id(request.coding_pool) if item.is_active
        )
        if len(coding_eligible) < coding_count:
            raise AssessmentPlanningError(
                PlanningErrorKind.INSUFFICIENT_CODING_POOL,
                f"Only {len(coding_eligible)} active coding problems available, "
                f"need {coding_count}",
            )
        selected_coding_ids = _pick(coding_eligible, coding_count, rng)

    # -- 8. Duration: base + the additional time of enabled modules ---------
    base_duration = request.base_duration_minutes
    total_duration = base_duration + additional_minutes

    # -- 9. Per-domain entries ---------------------------------------------
    domain_entries = []
    for domain in selected:
        config = resolved.get(domain.id)
        enabled, hands_count, hands_minutes = per_domain_hands_on[domain.id]
        domain_entries.append(
            DomainPlanEntry(
                domain_id=domain.id,
                domain_name=domain.name,
                domain_slug=domain.slug,
                config_applies_to=family if config is not None else None,
                mcq_count=per_domain_mcq[domain.id],
                descriptive_count=per_domain_descriptive.get(domain.id, 0),
                hands_on_enabled=enabled,
                hands_on_count=hands_count,
                hands_on_additional_minutes=hands_minutes,
            )
        )

    # -- 10. Configuration fingerprint --------------------------------------
    fingerprint = _fingerprint(
        {
            "plan_version": PLAN_VERSION,
            "semester": program.semester,
            "scope": program.scope.value,
            "tier": program.tier.value if program.tier else None,
            "max_domains": program.max_domains,
            "config_source": config_source.value,
            "coding_enabled": coding_enabled,
            "coding_count": coding_count,
            "base_duration_minutes": base_duration,
            "legacy_technical_fallback": (
                {
                    "total_questions": legacy.total_questions,
                    "descriptive_question_count": legacy.descriptive_question_count,
                    "hands_on_question_count": legacy.hands_on_question_count,
                }
                if legacy is not None
                else None
            ),
            "domains": [
                {
                    "domain_id": entry.domain_id,
                    "applies_to": (
                        entry.config_applies_to.value
                        if entry.config_applies_to
                        else None
                    ),
                    "mcq_count": entry.mcq_count,
                    "descriptive_count": entry.descriptive_count,
                    "hands_on_enabled": entry.hands_on_enabled,
                    "hands_on_count": entry.hands_on_count,
                    "hands_on_additional_minutes": entry.hands_on_additional_minutes,
                }
                for entry in domain_entries
            ],
        }
    )

    return AssessmentPlan(
        plan_version=PLAN_VERSION,
        semester=program.semester,
        scope=program.scope,
        tier=program.tier,
        max_domains=program.max_domains,
        config_source=config_source,
        domain_ids=[domain.id for domain in selected],
        domains=domain_entries,
        selected_mcq_ids=selected_mcq_ids,
        selected_descriptive_question_ids=selected_descriptive_ids,
        selected_hands_on_question_ids=selected_hands_on_ids,
        selected_coding_problem_ids=selected_coding_ids,
        coding_enabled=coding_enabled,
        coding_count=coding_count,
        mcq_total=len(selected_mcq_ids),
        descriptive_total=len(selected_descriptive_ids),
        hands_on_total=len(selected_hands_on_ids),
        coding_total=len(selected_coding_ids),
        base_duration_minutes=base_duration,
        additional_minutes=additional_minutes,
        duration_minutes=total_duration,
        config_fingerprint=fingerprint,
    )
