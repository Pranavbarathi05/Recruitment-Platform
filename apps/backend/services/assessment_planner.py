"""Pure assessment planner for the modular assessment architecture.

WHAT THIS MODULE IS
    A deterministic, side-effect-free function that turns already-resolved
    inputs (candidate program, selected domains, module configuration and
    candidate-eligible content pools) into a single frozen assessment plan:

        inputs -> plan_assessment() -> AssessmentPlan

    It is the planning half of the approved architecture:

        Candidate semester
            -> assessment_program        (scope / tier / max_domains / mcq_total)
            -> selected domains          (validated + deterministically ordered)
            -> assessment_module_config  (OPTIONAL modules only + additional time)
            -> AssessmentPlan            (frozen, ready to persist)

    WHERE EACH QUANTITY COMES FROM
        technical MCQ        program.mcq_total split evenly across the selected
                             domains (total for one, total//2 + total//2 for two).
                             Must be even; 0 is valid.
        descriptive          ORGANIZATIONAL only, from the configured
                             descriptive_count. Technical never has any.
        coding (DSA)         GLOBAL and domain-independent, from the global
                             assessment_config.coding_problem_count.
        practicals           OPTIONAL per-domain switches on the module config.
                             Only the hands-on challenge exists today.
        duration             global base + additional minutes of enabled modules.

WHAT THIS MODULE DELIBERATELY IS NOT
    - It performs NO database access. It does not import the Supabase client,
      fastapi, psycopg or anything that can reach a database, and it never
      reads live configuration itself. Callers resolve rows and pass them in.
    - It writes NOTHING. It never inserts or updates an attempt.
    - It carries NO legacy selection path. The pre-modular global fallback (a
      single assessment_config.total_questions split evenly across the selected
      domains, with global descriptive/hands-on counts drawn from the union of
      the pools) has been deleted. Every quantity now has exactly ONE source,
      listed above, so there is nothing left that can silently mix the two
      models.
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
#
# v2 (final core architecture): the technical MCQ quantity is DERIVED from
#   assessment_program.mcq_total and the number of selected domains rather
#   than read from assessment_module_config.mcq_count; technical scopes carry
#   no descriptive questions at all; and the plan gained the generic
#   `practicals` structure described below.
PLAN_VERSION = 2


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


class PracticalKind(str, Enum):
    """The kind of practical module a plan arm carries.

    ONLY hands_on is implemented. The arm/module shape below, and this enum,
    exist so a new kind can be added without reshaping the frozen plan — but
    no code produces anything other than HANDS_ON today.
    """

    HANDS_ON = "hands_on"


class PracticalModuleKind(str, Enum):
    """How the arms of one practical module relate to each other."""

    # Exactly one arm: the candidate must do it, and it contributes in full.
    SINGLE = "single"
    # Several interchangeable arms: the candidate may attempt any subset and
    # only the best arm contributes. No kind produces this yet.
    ELECTIVE = "elective"


class PracticalScoring(str, Enum):
    """How a practical module's arms combine into one contribution."""

    # The single arm's score.
    SINGLE = "single"
    # max(arm scores) — arms are alternatives, never additive.
    MAX = "max"


class ConfigSource(str, Enum):
    """Where the resolved module counts came from.

    MODULAR is the ONLY source a new plan can use: the module configuration
    rows (plus, for a technical scope, the programme-derived MCQ total, the
    global coding count and the optional per-domain hands-on switch). The
    organizational scope has no other source at all.

    LEGACY_TECHNICAL_FALLBACK is retained as HISTORICAL PLAN VOCABULARY ONLY.
    Exactly one attempt created before the programme/module architecture landed
    has ``config_source = "legacy_technical_fallback"`` stored in its
    assessment_attempts.plan snapshot, and that frozen JSON must stay
    deserialisable with AssessmentPlan, so the member cannot be deleted. No
    code path can produce it any more: the fallback that generated it was
    removed, and ``config_source`` is now always MODULAR for a new plan.
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
# Domain selection rules
# ---------------------------------------------------------------------------

# Candidate-facing text for a selection that mixes the Organizational domain
# with any other domain.
ORGANIZATIONAL_EXCLUSIVE_DETAIL = (
    "The Organizational domain cannot be combined with other domains. "
    "Select it on its own, or choose technical domains only."
)


def assert_organizational_exclusive(domains) -> None:
    """Reject a selection that mixes the Organizational domain with any other.

    The Organizational domain (``domains.assessment_scope = 'organizational'``)
    describes a whole assessment rather than a technical track, so it is
    mutually exclusive with every other domain — in either order. Identity comes
    from ``assessment_scope``, the field the rest of the planner already uses to
    classify a domain, so nothing here relies on a domain name, a slug or a
    hardcoded UUID.

    ``domains`` may be a partial catalogue: ids that do not resolve are ignored
    here so that DOMAIN_NOT_FOUND keeps reporting unknown domains instead of a
    missing row being misreported as a scope problem.

    Shared by the pure planner and by the orchestration layer so the fail-fast
    check and the authoritative check can never drift apart.
    """
    scopes = {domain.assessment_scope for domain in domains}
    if DomainScope.ORGANIZATIONAL in scopes and len(scopes) > 1:
        raise AssessmentPlanningError(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            ORGANIZATIONAL_EXCLUSIVE_DETAIL,
        )


def allowed_domain_scopes(program_scope: Scope) -> tuple:
    """Which ``domains.assessment_scope`` values a programme may offer.

    ``assessment_program.scope`` is the programme's DEFAULT MODE, not an
    exclusive restriction. The product requirement is:

        organizational (semester 1) -> Organizational Roles only
        technical      (3rd / 5th)  -> technical domains AND Organizational
                                       Roles as a STANDALONE assessment
        none           (7th)        -> nothing

    So a technical semester must not make every assessment technical: a
    3rd/5th-semester candidate may take Organizational Roles on its own,
    exactly like a 1st-semester candidate. The mutual exclusion lives on the
    DOMAINS (``assert_organizational_exclusive``), not on the semester.

    Returns domain scopes so the eligibility query and the planner can share
    the same rule; an empty tuple means the programme offers no assessment at
    all.
    """
    if program_scope is Scope.ORGANIZATIONAL:
        return (DomainScope.ORGANIZATIONAL,)
    if program_scope is Scope.TECHNICAL:
        return (DomainScope.TECHNICAL, DomainScope.ORGANIZATIONAL)
    return ()


def assessment_mode_of(domains) -> Scope:
    """The assessment MODE a resolved domain set implies.

    The mode follows the candidate's SELECTION, never the semester: a single
    Organizational domain plans an organizational assessment (organizational
    MCQ/descriptive module config, no coding, no hands-on), while technical
    domains plan a technical one (programme mcq_total, tier-shaped modules,
    coding).

    ``assert_organizational_exclusive`` guarantees the set is either one
    Organizational domain or technical domains only, so the first row
    describes the whole set. An empty set means nothing has resolved yet —
    the planner will refuse it regardless, so technical is only used to pick a
    module-config family for a query that returns nothing.
    """
    if domains and domains[0].assessment_scope is DomainScope.ORGANIZATIONAL:
        return Scope.ORGANIZATIONAL
    return Scope.TECHNICAL


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
    """One assessment_program row (migrations 014 + 018)."""

    semester: int
    scope: Scope
    tier: Optional[Tier] = None
    max_domains: int
    coding_enabled: bool = False

    # The PROGRAM-level MCQ total (migration 018). For a technical scope this
    # is the whole assessment's MCQ count, split evenly across the selected
    # domains: 20 -> a single domain, 10+10 -> two domains. It is deliberately
    # NOT a per-domain value, so it cannot come from module configuration.
    #
    # Ignored for the organizational scope, which derives its MCQ quantity
    # from its own configurable module count instead.
    mcq_total: int = Field(default=20, gt=0)


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

    # Global, module-independent values (assessment_config.duration_minutes and
    # assessment_config.coding_problem_count). Coding count stays global by
    # design and is never per-domain.
    base_duration_minutes: int = Field(..., gt=0)
    global_coding_problem_count: int = Field(default=0, ge=0)

    # Optional proctoring policy (assessment_config.network_integrity_monitoring),
    # read once when the attempt is created and frozen into the plan. It changes
    # no selection, count or duration — it only tells the candidate workspace
    # whether to run the network-integrity monitor for this attempt.
    network_integrity_monitoring: bool = False

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


class PracticalArm(BaseModel):
    """One selectable option inside a practical module.

    Carries ids only. Content, expected values and scores are never part of
    the plan: they are resolved per-request at serve time and the expected
    values never leave the backend.
    """

    model_config = ConfigDict(frozen=True)

    kind: PracticalKind
    question_ids: list[str] = Field(default_factory=list)


class PracticalModule(BaseModel):
    """A frozen practical module: what the candidate is offered, and how it scores.

    Today the planner emits at most one module, with module_kind=SINGLE,
    scoring=SINGLE and exactly one HANDS_ON arm. The ELECTIVE/MAX vocabulary is
    declared so the frozen plan already has a place to describe an elective
    without the serialized shape having to change later.
    """

    model_config = ConfigDict(frozen=True)

    module_kind: PracticalModuleKind
    scoring: PracticalScoring
    arms: list[PracticalArm] = Field(default_factory=list)


class DomainPlanEntry(BaseModel):
    """The resolved module configuration for ONE selected domain.

    mcq_count is the number of MCQs drawn FROM this domain. For a technical
    scope it is the derived even share of the programme's mcq_total (total for
    a single domain, total//2 for each of two), NOT an authored per-domain
    value. For the organizational scope it is the configured mcq_count.

    descriptive_count is always 0 for a technical scope: technical Junior and
    Senior assessments carry no descriptive questions at all.
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

    # The frozen practical modules. At most one today. Kept generic so a new
    # practical kind is an added enum member rather than a plan reshape.
    practicals: list[PracticalModule] = Field(default_factory=list)

    coding_enabled: bool
    coding_count: int

    mcq_total: int
    descriptive_total: int
    hands_on_total: int
    coding_total: int

    base_duration_minutes: int
    additional_minutes: int
    duration_minutes: int

    # Whether the optional network-integrity monitor applies to THIS attempt.
    # Frozen here, in the plan snapshot, so an admin flipping the global toggle
    # can never change the behaviour of an attempt that is already running: the
    # candidate workspace reads the policy from this frozen plan.
    #
    # It is deliberately NOT part of config_fingerprint: the fingerprint
    # identifies the CONFIGURATION that shaped the assessment's content
    # (domains, counts, durations). Whether the machine is network-monitored is
    # an orthogonal proctoring policy that changes no question, no count and no
    # duration, so folding it in would make two content-identical plans look
    # different for a reason that has nothing to do with the plan's content.
    network_integrity_monitoring: bool = False

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


def _family_for(program: ProgramInput, domain_scope: DomainScope) -> ConfigFamily:
    """The assessment_module_config.applies_to family for this assessment.

    The family follows the ASSESSMENT MODE the candidate chose, not the
    semester's default: a 3rd/5th-semester candidate taking Organizational
    Roles gets the ``organizational`` module configuration exactly like a
    1st-semester candidate, while a technical selection keeps the programme's
    tier (junior / senior).
    """
    if domain_scope is DomainScope.ORGANIZATIONAL:
        return ConfigFamily.ORGANIZATIONAL
    if program.tier is None:
        raise AssessmentPlanningError(
            PlanningErrorKind.INVALID_PROGRAM,
            f"Semester {program.semester} has scope 'technical' but no tier",
        )
    return ConfigFamily(program.tier.value)


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

    # The programme's DEFAULT mode decides which assessment modes are allowed
    # for this semester — it does not decide which one the candidate chose.
    allowed_scopes = allowed_domain_scopes(program.scope)

    # -- 2. Domain selection ------------------------------------------------
    requested = list(request.requested_domain_ids)
    if len(requested) < 1:
        raise AssessmentPlanningError(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            "At least one domain must be selected",
        )
    # Organizational is mutually exclusive with EVERY other domain, so a mixed
    # selection is refused here — before the count limits and before any
    # question is selected. It is checked first so a mixed selection is
    # reported as the combination it is, rather than as "exactly one domain"
    # or a scope mismatch.
    catalogue = {domain.id: domain for domain in request.domains}
    # Ids that actually resolve. assert_organizational_exclusive is given only
    # these so an unknown id keeps reporting DOMAIN_NOT_FOUND instead of being
    # misread as a combination problem.
    resolvable = [
        catalogue[domain_id] for domain_id in requested if domain_id in catalogue
    ]
    assert_organizational_exclusive(resolvable)

    # Resolve the requested domains BEFORE any scope or count rule: the
    # assessment mode is derived from the selection, and a selection that
    # references a domain which does not exist (or is inactive) has no mode to
    # decide yet.
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
        selected.append(domain)

    # Deterministic order: (name, id). Matches the project's convention of
    # ordering domains by name, and removes any dependence on the order the
    # caller happened to fetch or pass them in.
    selected.sort(key=lambda domain: (domain.name, domain.id))

    # -- Scope: derived from the SELECTION, validated against the programme --
    #
    # assessment_program.scope only decides WHICH MODES a semester may offer;
    # the mode itself comes from the domains the candidate selected:
    #   [Organizational Roles]          -> organizational assessment
    #   [Web Development]               -> technical assessment
    #   [Web Development, ML]           -> technical assessment
    #   [Organizational Roles, Web Dev] -> already refused above
    #
    # assert_organizational_exclusive guarantees the set is either one
    # Organizational domain or technical domains only, so it has exactly one
    # scope unless something already refused the mixed case.
    scopes_present = {domain.assessment_scope for domain in selected}
    if len(scopes_present) > 1:
        raise AssessmentPlanningError(
            PlanningErrorKind.WRONG_DOMAIN_SCOPE,
            ORGANIZATIONAL_EXCLUSIVE_DETAIL,
        )
    expected_domain_scope = next(iter(scopes_present))
    if expected_domain_scope not in allowed_scopes:
        allowed_text = ", ".join(
            sorted(scope.value for scope in allowed_scopes)
        )
        raise AssessmentPlanningError(
            PlanningErrorKind.WRONG_DOMAIN_SCOPE,
            f"Domain '{selected[0].name}' has assessment_scope "
            f"'{expected_domain_scope.value}' but the "
            f"'{program.scope.value}' assessment for semester "
            f"{program.semester} allows only: {allowed_text}",
        )

    assessment_mode = (
        Scope.TECHNICAL
        if expected_domain_scope is DomainScope.TECHNICAL
        else Scope.ORGANIZATIONAL
    )
    is_technical = assessment_mode is Scope.TECHNICAL
    family = _family_for(program, expected_domain_scope)

    # The organizational assessment is exactly-one-domain by definition. This
    # is asserted explicitly rather than left to max_domains, so the rule holds
    # even if a program row is misconfigured.
    if not is_technical and len(requested) > 1:
        raise AssessmentPlanningError(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            f"The {assessment_mode.value} assessment allows exactly one domain "
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

    if missing:
        if is_technical:
            # Technical module configs are OPTIONAL: MCQ quantity comes from
            # program.mcq_total and coding is global. Module rows exist only
            # to enable OPTIONAL modules (today just hands-on for senior), so
            # a missing row simply means no optional module is enabled.
            pass
        else:
            # Organizational scope requires its module row because it derives
            # its entire content (MCQ + descriptive counts) from it.
            raise AssessmentPlanningError(
                PlanningErrorKind.MISSING_MODULE_CONFIG,
                f"No '{family.value}' configuration for domain(s) "
                f"{[d.name for d in missing]}; the organizational assessment "
                f"derives its entire content from its module configuration",
            )

    config_source = ConfigSource.MODULAR
    rng = random.Random(request.seed) if request.seed is not None else None

    # -- 4. MCQ: per domain, semester-aware ---------------------------------
    mcq_pool = _dedupe_by_id(request.mcq_pool)
    selected_mcq_ids = []
    per_domain_mcq = {}

    if is_technical:
        # AUTHORITY: the master technical MCQ total lives on
        # assessment_program.mcq_total (migration 018). The admin configures
        # one value that applies to ALL technical programs, and the planner
        # splits it evenly across the selected domains:
        #
        #   1 domain  -> all MCQs go to that domain
        #   2 domains -> total // 2 for each
        #
        # The 40-question-per-domain-per-semester pool is question-bank
        # inventory (content inventory), not a configuration value.
        total = program.mcq_total
        if total % 2 != 0:
            raise AssessmentPlanningError(
                PlanningErrorKind.INVALID_PROGRAM,
                f"technical mcq_total ({total}) must be an even number",
            )
        if len(selected) == 1:
            per_domain_mcq[selected[0].id] = total
        else:
            half = total // 2
            for domain in selected:
                per_domain_mcq[domain.id] = half
    else:
        # Organizational: the admin configures the MCQ quantity directly.
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

    if is_technical:
        # TECHNICAL Junior/Senior assessments carry NO descriptive questions at
        # all — not for one selected domain and not for two. This holds
        # regardless of any descriptive_count an authoring mistake may have left
        # on a technical module row. Descriptive questions belong to the
        # ORGANIZATIONAL assessment alone.
        per_domain_descriptive = {d.id: 0 for d in selected}
    else:
        # Organizational only, and the organizational scope REQUIRES a module row
        # (the planner refused above if any was missing), so every selected
        # domain is guaranteed to be present here.
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
    #
    # Practicals are a SENIOR-technical module. A Junior technical assessment is
    # MCQs + 2 DSA/Coding problems and carries no practical at all (and no
    # practical time), and the organizational scope has none either. The guard
    # lives here as well as at authoring time so a mis-authored junior row can
    # never hand a junior candidate a challenge or its additional minutes.
    practicals_allowed = is_technical and program.tier is Tier.SENIOR

    hands_pool = _dedupe_by_id(request.hands_on_pool)
    selected_hands_on_ids = []
    per_domain_hands_on = {}
    additional_minutes = 0

    # Module configuration is OPTIONAL for a technical scope, so a selected
    # domain may legitimately have no row at all: that simply means no optional
    # module is enabled for it. Never index `resolved` directly.
    def _hands_on_enabled(domain):
        config = resolved.get(domain.id)
        return bool(config is not None and config.hands_on_enabled)

    quotas = {
        d.id: (
            resolved[d.id].hands_on_count
            if practicals_allowed and _hands_on_enabled(d)
            else 0
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
        config = resolved.get(domain.id)
        if (
            not practicals_allowed
            or config is None
            or not config.hands_on_enabled
        ):
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

    # -- 6b. Practical modules ----------------------------------------------
    # Frozen description of what the candidate is offered. Today the only
    # implemented practical is the hands-on challenge, so at most ONE module
    # with ONE arm is produced (scoring SINGLE). The arm/module/scoring
    # vocabulary is generic, so a future practical kind becomes an added enum
    # member plus another arm here — the frozen plan's shape does not change.
    #
    # Selection itself is untouched by this structure: the hands-on ids were
    # already resolved above through the exact cross-domain allocator, and the
    # module simply describes them.
    practicals = []
    if selected_hands_on_ids:
        practicals.append(
            PracticalModule(
                module_kind=PracticalModuleKind.SINGLE,
                scoring=PracticalScoring.SINGLE,
                arms=[
                    PracticalArm(
                        kind=PracticalKind.HANDS_ON,
                        question_ids=list(selected_hands_on_ids),
                    )
                ],
            )
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
            "scope": assessment_mode.value,
            "tier": program.tier.value if program.tier else None,
            "max_domains": program.max_domains,
            "program_mcq_total": program.mcq_total,
            "config_source": config_source.value,
            "coding_enabled": coding_enabled,
            "coding_count": coding_count,
            "base_duration_minutes": base_duration,
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
            # The SHAPE of the practicals being offered — a configuration
            # fact. Deliberately excludes the arm question_ids: which specific
            # challenge was drawn is a draw, not configuration, so it must not
            # move the fingerprint (the same reason `seed` is excluded).
            "practicals": [
                {
                    "module_kind": module.module_kind.value,
                    "scoring": module.scoring.value,
                    "arms": [{"kind": arm.kind.value} for arm in module.arms],
                }
                for module in practicals
            ],
        }
    )

    return AssessmentPlan(
        plan_version=PLAN_VERSION,
        semester=program.semester,
        scope=assessment_mode,
        tier=program.tier,
        max_domains=program.max_domains,
        config_source=config_source,
        domain_ids=[domain.id for domain in selected],
        domains=domain_entries,
        selected_mcq_ids=selected_mcq_ids,
        selected_descriptive_question_ids=selected_descriptive_ids,
        selected_hands_on_question_ids=selected_hands_on_ids,
        selected_coding_problem_ids=selected_coding_ids,
        practicals=practicals,
        coding_enabled=coding_enabled,
        coding_count=coding_count,
        mcq_total=len(selected_mcq_ids),
        descriptive_total=len(selected_descriptive_ids),
        hands_on_total=len(selected_hands_on_ids),
        coding_total=len(selected_coding_ids),
        base_duration_minutes=base_duration,
        additional_minutes=additional_minutes,
        duration_minutes=total_duration,
        network_integrity_monitoring=request.network_integrity_monitoring,
        config_fingerprint=fingerprint,
    )
