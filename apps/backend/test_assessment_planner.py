"""Focused unit tests for the pure assessment planner.

These tests never touch Supabase, a database, or an HTTP endpoint. Every input
is an in-memory fixture, which is the whole point of the planner being pure:
resolution can be exercised exhaustively without a live assessment pipeline.
"""

import ast
import copy
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from services import assessment_planner
from services.assessment_planner import (
    AssessmentPlanRequest,
    AssessmentPlanningError,
    CodingPoolItem,
    ConfigSource,
    DescriptivePoolItem,
    DomainInput,
    HandsOnPoolItem,
    MCQPoolItem,
    ModuleConfigInput,
    PlanningErrorKind,
    ProgramInput,
    Scope,
    plan_assessment,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CYBER_ID = "d-cyber"
WEB_ID = "d-web"
ORG_ID = "d-org"

CYBER = DomainInput(
    id=CYBER_ID,
    name="Cyber Security",
    slug="cyberSecurity",
    assessment_scope="technical",
)
WEB = DomainInput(
    id=WEB_ID,
    name="Web Development",
    slug="webDevelopment",
    assessment_scope="technical",
)
ORG = DomainInput(
    id=ORG_ID,
    name="Organizational Roles",
    slug="organizationalRoles",
    assessment_scope="organizational",
)
CATALOGUE = [CYBER, WEB, ORG]

# Mirrors the seeded assessment_program rows from migration 014.
PROGRAM_1 = ProgramInput(
    semester=1,
    scope=Scope.ORGANIZATIONAL,
    tier=None,
    max_domains=1,
    coding_enabled=False,
)
# The mcq_total field still exists on assessment_program (migration 018)
# but the planner no longer reads it for technical MCQ quantity. Technical
# MCQ counts now come from assessment_module_config.mcq_count per domain.
TECH_MCQ_TOTAL = 20  # legacy default; tests use configured per-domain values

PROGRAM_3 = ProgramInput(
    semester=3,
    scope=Scope.TECHNICAL,
    tier="junior",
    max_domains=2,
    coding_enabled=True,
    mcq_total=TECH_MCQ_TOTAL,
)
PROGRAM_5 = ProgramInput(
    semester=5,
    scope=Scope.TECHNICAL,
    tier="senior",
    max_domains=2,
    coding_enabled=True,
    mcq_total=TECH_MCQ_TOTAL,
)
PROGRAM_7 = ProgramInput(
    semester=7,
    scope=Scope.NONE,
    tier=None,
    max_domains=1,
    coding_enabled=False,
)


def cfg(
    domain_id,
    applies_to,
    mcq=0,
    desc=0,
    hands_on=False,
    hands_on_count=0,
    minutes=0,
    hands_on_module="",
):
    """Build an assessment_module_config row."""
    return ModuleConfigInput(
        domain_id=domain_id,
        applies_to=applies_to,
        mcq_count=mcq,
        descriptive_count=desc,
        hands_on_enabled=hands_on,
        hands_on_count=hands_on_count,
        hands_on_additional_minutes=minutes,
        hands_on_module=hands_on_module,
    )


# The approved CyberSec / Web Senior + Junior shapes.
CYBER_SENIOR = cfg(
    CYBER_ID, "senior", mcq=5, desc=2, hands_on=True, hands_on_count=1, minutes=20
)
CYBER_JUNIOR = cfg(CYBER_ID, "junior", mcq=5, desc=1)
WEB_SENIOR = cfg(WEB_ID, "senior", mcq=5, desc=1)
WEB_JUNIOR = cfg(WEB_ID, "junior", mcq=4, desc=1)
ORG_COMMON = cfg(ORG_ID, "organizational", mcq=10, desc=0)


def mcq_items(domain_id, semester, count, prefix):
    return [
        MCQPoolItem(id=f"{prefix}-{i:02d}", domain_id=domain_id, semester=semester)
        for i in range(count)
    ]


def desc_items(ids, domain_ids, active=True):
    return [
        DescriptivePoolItem(id=i, domain_ids=list(domain_ids), is_active=active)
        for i in ids
    ]


def hands_items(ids, domain_ids, active=True, module=""):
    """Build hands-on pool rows; `module` declares the challenge module."""
    return [
        HandsOnPoolItem(
            id=i,
            domain_ids=list(domain_ids),
            hands_on_modules=[module] if module else [],
            is_active=active,
        )
        for i in ids
    ]


def coding_items(count, prefix="code"):
    return [CodingPoolItem(id=f"{prefix}-{i:02d}") for i in range(count)]


def big_pools(
    program,
    domains,
    mcq_per=25,
    desc_ids=("d1", "d2", "d3", "d4"),
    hands_ids=("h1", "h2", "h3"),
):
    """Generous pools so a test can focus on the rule under test."""
    domain_ids = [d.id for d in domains]
    mcq_pool = []
    for domain in domains:
        mcq_pool.extend(
            mcq_items(domain.id, program.semester, mcq_per, f"q{domain.id}")
        )
    return {
        "mcq_pool": mcq_pool,
        "descriptive_pool": desc_items(desc_ids, domain_ids),
        "hands_on_pool": hands_items(hands_ids, domain_ids),
    }


def build(program, domain_ids, module_configs=None, coding=0, base=90, **kwargs):
    pools = big_pools(program, [d for d in CATALOGUE if d.id in domain_ids])
    pools.update(kwargs)
    return AssessmentPlanRequest(
        program=program,
        requested_domain_ids=list(domain_ids),
        domains=CATALOGUE,
        module_configs=module_configs if module_configs is not None else [],
        base_duration_minutes=base,
        global_coding_problem_count=coding,
        coding_pool=coding_items(max(coding, 5)),
        **pools,
    )


def expect_failure(kind, **kwargs):
    """Assert planning fails with a specific kind, and return the error."""
    with pytest.raises(AssessmentPlanningError) as excinfo:
        plan_assessment(build(**kwargs))
    assert excinfo.value.kind is kind, excinfo.value
    return excinfo.value


# ---------------------------------------------------------------------------
# 1-3. The three planning scopes
# ---------------------------------------------------------------------------


class TestProgramScopes:
    def test_semester_1_organizational_plan(self):
        plan = plan_assessment(build(PROGRAM_1, [ORG_ID], [ORG_COMMON], coding=5))
        assert plan.plan_version == 2
        assert plan.semester == 1
        assert plan.scope is Scope.ORGANIZATIONAL
        assert plan.tier is None
        assert plan.max_domains == 1
        assert plan.domain_ids == [ORG_ID]
        assert plan.mcq_total == 10
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 0
        # Organizational never carries coding, even when the global coding
        # count is supplied and the pool is non-empty.
        assert plan.coding_enabled is False
        assert plan.coding_count == 0
        assert plan.coding_total == 0
        assert plan.selected_coding_problem_ids == []

    def test_semester_3_junior_technical_plan(self):
        plan = plan_assessment(
            build(PROGRAM_3, [CYBER_ID], [CYBER_JUNIOR], coding=2, base=90)
        )
        assert plan.scope is Scope.TECHNICAL
        assert plan.tier.value == "junior"
        assert plan.config_source is ConfigSource.MODULAR
        # Junior technical: program.mcq_total (20) for ONE selected domain.
        assert plan.mcq_total == 20  # PROGRAM_3.mcq_total
        assert [e.mcq_count for e in plan.domains] == [20]
        # Technical Junior carries NO descriptive questions, ever.
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []
        assert plan.hands_on_total == 0
        assert plan.practicals == []
        assert plan.coding_enabled is True
        assert plan.coding_total == 2
        assert plan.additional_minutes == 0
        assert plan.duration_minutes == 90

    def test_semester_5_senior_technical_plan(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2, base=90)
        )
        assert plan.scope is Scope.TECHNICAL
        assert plan.tier.value == "senior"
        # Senior technical: program.mcq_total (20) for ONE selected domain.
        assert plan.mcq_total == 20  # PROGRAM_5.mcq_total
        # Technical carries NO descriptive questions, even though the module
        # row still says desc=2 (technical descriptive is not used).
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 1
        # The hands-on challenge is described by the generic practicals shape.
        assert len(plan.practicals) == 1
        assert plan.practicals[0].module_kind.value == "single"
        assert plan.practicals[0].scoring.value == "single"
        assert plan.practicals[0].arms[0].kind.value == "hands_on"
        assert (
            plan.practicals[0].arms[0].question_ids
            == plan.selected_hands_on_question_ids
        )
        assert plan.coding_total == 2
        # Senior CyberSec: hands-on enabled with +20 minutes.
        assert plan.additional_minutes == 20
        assert plan.duration_minutes == 110

    def test_semester_7_scope_none_is_rejected(self):
        err = expect_failure(
            PlanningErrorKind.NO_ASSESSMENT,
            program=PROGRAM_7,
            domain_ids=[ORG_ID],
        )
        assert "no assessment" in err.detail.lower()

    def test_technical_program_without_tier_fails(self):
        broken = ProgramInput(
            semester=3,
            scope=Scope.TECHNICAL,
            tier=None,
            max_domains=2,
            coding_enabled=True,
        )
        err = expect_failure(
            PlanningErrorKind.INVALID_PROGRAM,
            program=broken,
            domain_ids=[CYBER_ID],
        )
        assert "tier" in err.detail


# ---------------------------------------------------------------------------
# 5-8. Domain selection validation
# ---------------------------------------------------------------------------


class TestDomainSelection:
    def test_zero_domains_rejected(self):
        expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_5,
            domain_ids=[],
        )

    def test_more_than_max_domains_rejected(self):
        expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID, WEB_ID, ORG_ID],
        )

    def test_organizational_more_than_one_domain_rejected(self):
        """The organizational assessment allows exactly one domain.

        Uses a SECOND real organizational row: the rule is about the
        assessment's shape, so it must be exercised with two rows that both
        resolve rather than with an unresolvable id (which would correctly
        report DOMAIN_NOT_FOUND first).
        """
        second_org = DomainInput(
            id="d-org-2",
            name="Second Organizational Roles",
            slug="secondOrganizationalRoles",
            assessment_scope="organizational",
            is_active=True,
        )
        request = build(PROGRAM_1, [ORG_ID, second_org.id], [ORG_COMMON])
        request = request.model_copy(
            update={"domains": [*request.domains, second_org]}
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(request)
        assert excinfo.value.kind is PlanningErrorKind.INVALID_DOMAIN_SELECTION
        assert "exactly one" in excinfo.value.detail

    def test_organizational_one_domain_allowed_even_if_max_domains_wrong(self):
        """The one-domain rule holds even if a program row says max_domains=2."""
        second_org = DomainInput(
            id="d-org-2",
            name="Second Organizational Roles",
            slug="secondOrganizationalRoles",
            assessment_scope="organizational",
            is_active=True,
        )
        misconfigured = ProgramInput(
            semester=1,
            scope=Scope.ORGANIZATIONAL,
            tier=None,
            max_domains=2,
            coding_enabled=False,
        )
        request = build(
            misconfigured, [ORG_ID, second_org.id], [ORG_COMMON]
        )
        request = request.model_copy(
            update={"domains": [*request.domains, second_org]}
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(request)
        assert excinfo.value.kind is PlanningErrorKind.INVALID_DOMAIN_SELECTION
        assert "exactly one" in excinfo.value.detail

    def test_duplicate_domains_rejected(self):
        expect_failure(
            PlanningErrorKind.DUPLICATE_DOMAINS,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID, CYBER_ID],
            module_configs=[CYBER_SENIOR],
        )

    def test_unknown_domain_rejected(self):
        err = expect_failure(
            PlanningErrorKind.DOMAIN_NOT_FOUND,
            program=PROGRAM_5,
            domain_ids=["d-does-not-exist"],
        )
        assert "does not exist" in err.detail

    def test_inactive_domain_rejected(self):
        inactive = DomainInput(
            id="d-old",
            name="Retired Domain",
            slug="retired",
            assessment_scope="technical",
            is_active=False,
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(
                AssessmentPlanRequest(
                    program=PROGRAM_5,
                    requested_domain_ids=["d-old"],
                    domains=CATALOGUE + [inactive],
                    module_configs=[cfg("d-old", "senior", mcq=1)],
                    base_duration_minutes=90,
                    mcq_pool=mcq_items("d-old", 5, 5, "old"),
                )
            )
        assert excinfo.value.kind is PlanningErrorKind.DOMAIN_INACTIVE

    def test_technical_programme_accepts_standalone_organizational_domain(self):
        """CORRECTED RULE: ``assessment_program.scope`` is a DEFAULT mode.

        A technical programme (3rd/5th) may still be taken as the standalone
        Organizational assessment, because the assessment MODE is derived from
        the SELECTED domains, not from the semester. The programme's scope
        still decides which domains are eligible at all — see
        ``test_organizational_assessment_rejects_technical_domain`` for a
        1st-semester candidate picking a technical domain, which stays
        rejected.
        """
        plan = plan_assessment(build(PROGRAM_5, [ORG_ID], [ORG_COMMON]))
        assert plan.scope is Scope.ORGANIZATIONAL
        assert plan.domain_ids == [ORG_ID]
        # Organizational mode: module-config quantity, no coding, no hands-on.
        assert plan.mcq_total == 10
        assert plan.coding_total == 0
        assert plan.hands_on_total == 0

    def test_organizational_assessment_rejects_technical_domain(self):
        err = expect_failure(
            PlanningErrorKind.WRONG_DOMAIN_SCOPE,
            program=PROGRAM_1,
            domain_ids=[CYBER_ID],
            module_configs=[CYBER_SENIOR],
        )
        assert "technical" in err.detail


class TestOrganizationalExclusivity:
    """The Organizational domain is mutually exclusive with every other domain.

    Identity comes from ``domains.assessment_scope`` — the same field used
    everywhere else in the planner — so nothing here depends on a domain name,
    a slug or a hardcoded UUID.
    """

    MESSAGE = "cannot be combined with other domains"

    def test_organizational_alone_is_allowed(self):
        """The standalone Organizational assessment keeps working untouched."""
        plan = plan_assessment(build(PROGRAM_1, [ORG_ID], [ORG_COMMON]))
        assert plan.scope is Scope.ORGANIZATIONAL
        assert plan.domain_ids == [ORG_ID]

    def test_multiple_non_organizational_domains_are_unaffected(self):
        """Ordinary multi-domain technical selection is untouched."""
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR])
        )
        assert plan.scope is Scope.TECHNICAL
        assert sorted(plan.domain_ids) == sorted([CYBER_ID, WEB_ID])

    def test_organizational_then_technical_rejected(self):
        err = expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_1,
            domain_ids=[ORG_ID, CYBER_ID],
        )
        assert self.MESSAGE in err.detail
        assert "Organizational" in err.detail

    def test_technical_then_organizational_rejected(self):
        """Order must not matter."""
        err = expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_1,
            domain_ids=[CYBER_ID, ORG_ID],
        )
        assert self.MESSAGE in err.detail

    def test_mixed_selection_rejected_for_a_technical_program_too(self):
        """The rule is program-independent, not just the semester-1 one-domain cap."""
        err = expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID, ORG_ID],
        )
        assert self.MESSAGE in err.detail

    def test_organizational_plus_multiple_technical_domains_rejected(self):
        """Organizational alongside SEVERAL technical domains is refused too."""
        err = expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID, WEB_ID, ORG_ID],
        )
        assert self.MESSAGE in err.detail

    def test_mixed_selection_is_reported_before_the_domain_count_rules(self):
        """A mixed pair is a COMBINATION error, not "exactly one domain"."""
        err = expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_1,
            domain_ids=[ORG_ID, CYBER_ID],
        )
        assert "exactly one" not in err.detail

    def test_unknown_id_next_to_organizational_is_still_not_found(self):
        """An unresolvable id must not be misreported as a combination error."""
        err = expect_failure(
            PlanningErrorKind.DOMAIN_NOT_FOUND,
            program=PROGRAM_5,
            domain_ids=["d-missing", ORG_ID],
        )
        assert "does not exist" in err.detail
        assert self.MESSAGE not in err.detail


# ---------------------------------------------------------------------------
# 9-10, 29. Module configuration (the only content source)
# ---------------------------------------------------------------------------


class TestModuleConfiguration:
    def test_missing_technical_module_config_is_ok(self):
        """Technical module configuration is OPTIONAL.

        MCQ quantity comes from program.mcq_total; module rows exist only
        to enable optional hands-on for senior. A missing row is fine.
        """
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], module_configs=[])
        )
        assert plan.mcq_total == 20  # PROGRAM_5.mcq_total
        assert plan.domains[0].mcq_count == 20

    def test_technical_mcq_total_comes_from_program(self):
        """program.mcq_total is the authoritative source for technical MCQs.

        The module-config mcq_count is NOT used for technical MCQ quantity.
        """
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], module_configs=[])
        )
        assert plan.mcq_total == 20  # PROGRAM_5.mcq_total = 20
        assert plan.domains[0].mcq_count == 20

    def test_technical_descriptive_count_is_not_used(self):
        """A technical module row cannot introduce descriptive questions."""
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], [cfg(CYBER_ID, "senior", mcq=5, desc=9)])
        )
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []
        assert plan.domains[0].descriptive_count == 0



    def test_missing_organizational_config_fails(self):
        """Organizational content has exactly one source: its module row.

        There is no fallback of any kind — not the retired global counts, and
        not anything else — so a missing row is a hard refusal.
        """
        err = expect_failure(
            PlanningErrorKind.MISSING_MODULE_CONFIG,
            program=PROGRAM_1,
            domain_ids=[ORG_ID],
        )
        assert "module configuration" in err.detail

    def test_legacy_fallback_inputs_no_longer_exist(self):
        """The retired pre-modular fallback model is gone from the planner.

        Guards the cleanup: nothing may re-introduce a second content source,
        and the request model must not silently accept one (input models
        ignore unknown fields, so a stray kwarg would otherwise be dropped).
        """
        import services.assessment_planner as planner

        assert not hasattr(planner, "LegacyTechnicalFallback")
        assert not hasattr(planner, "_legacy_union_selection")
        assert (
            "legacy_technical_fallback" not in AssessmentPlanRequest.model_fields
        )

    def test_partial_technical_config_is_ok(self):
        """Missing module config for a technical domain is fine.

        MCQ count comes from program.mcq_total, not module config.
        """
        cyber = cfg(
            CYBER_ID, "senior", mcq=5, hands_on=True, hands_on_count=1, minutes=20
        )
        # WEB deliberately unconfigured — still fine for technical
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], module_configs=[cyber])
        )
        # Both domains get 10 MCQs each (mcq_total=20, split evenly)
        assert plan.mcq_total == 20
        assert [e.mcq_count for e in plan.domains] == [10, 10]

    def test_technical_plan_is_always_modular(self):
        """A technical plan's content source is MODULAR.

        Module configuration is optional for technical; MCQ count comes
        from program.mcq_total.
        """
        # With rows
        with_rows = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        )
        assert with_rows.config_source is ConfigSource.MODULAR
        assert with_rows.mcq_total == 20  # PROGRAM_5.mcq_total
        # Without rows: also works (module config optional for technical)
        without_rows = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], module_configs=[])
        )
        assert without_rows.mcq_total == 20

    def test_duplicate_module_config_rejected(self):
        err = expect_failure(
            PlanningErrorKind.INVALID_MODULE_CONFIG,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID],
            module_configs=[CYBER_SENIOR, CYBER_SENIOR],
        )
        assert "Duplicate module configuration" in err.detail

    def test_negative_counts_rejected(self):
        for field, value in (
            ("mcq_count", -1),
            ("descriptive_count", -1),
            ("hands_on_count", -1),
            ("hands_on_additional_minutes", -1),
        ):
            bad = cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=1)
            setattr(bad, field, value)
            expect_failure(
                PlanningErrorKind.INVALID_MODULE_CONFIG,
                program=PROGRAM_5,
                domain_ids=[CYBER_ID],
                module_configs=[bad],
            )

    def test_config_for_wrong_tier_is_ignored(self):
        """A junior row is ignored for a senior programme.

        The row belongs to a different configuration family. Since module
        config is optional for technical, the plan still succeeds using
        program.mcq_total.
        """
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], module_configs=[CYBER_JUNIOR])
        )
        assert plan.mcq_total == 20  # from PROGRAM_5.mcq_total
        assert plan.domains[0].config_applies_to is None  # no matching config


# ---------------------------------------------------------------------------
# 11-13. MCQ
# ---------------------------------------------------------------------------


class TestMCQSelection:
    def test_two_domain_mcq_even_split(self):
        """Two domains: program.mcq_total is split evenly.

        PROGRAM_3 has mcq_total=20, so each domain gets 10.
        """
        plan = plan_assessment(
            build(PROGRAM_3, [CYBER_ID, WEB_ID], module_configs=[])
        )
        assert [e.mcq_count for e in plan.domains] == [10, 10]
        assert plan.mcq_total == 20

    def test_mcq_pool_is_filtered_by_candidate_semester(self):
        """Only the candidate's semester pool is eligible."""
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        # Replace the Cyber pool with semester-9 questions only.
        req.mcq_pool = mcq_items(CYBER_ID, 9, 25, "q9")
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_MCQ_POOL
        assert "Semester 5" in excinfo.value.detail

    def test_organizational_uses_the_semester_1_pool(self):
        """gamma decision: Organizational Roles draws the semester-1 pool."""
        req = build(PROGRAM_1, [ORG_ID], [ORG_COMMON])
        req.mcq_pool = mcq_items(ORG_ID, 1, 12, "org")
        plan = plan_assessment(req)
        assert plan.mcq_total == 10
        assert all(qid.startswith("org-") for qid in plan.selected_mcq_ids)

    def test_insufficient_mcq_pool_fails_loudly(self):
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        req.mcq_pool = mcq_items(CYBER_ID, 5, 3, "q")  # only 3 questions
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_MCQ_POOL
        # The requirement is program.mcq_total (20), only 3 exist.
        assert "only 3 active MCQ questions, need 20" in excinfo.value.detail

    def test_mcq_does_not_top_up_from_another_domain(self):
        """Web has plenty; Cyber is short. The plan must still fail."""
        req = build(PROGRAM_3, [CYBER_ID, WEB_ID], module_configs=[])
        # PROGRAM_3.mcq_total=20, split 10+10. Cyber only has 1.
        req.mcq_pool = mcq_items(CYBER_ID, 3, 1, "cyber") + mcq_items(
            WEB_ID, 3, 40, "web"
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_MCQ_POOL

    def test_inactive_mcq_questions_are_excluded(self):
        req = build(PROGRAM_5, [CYBER_ID], module_configs=[])
        req.mcq_pool = [
            MCQPoolItem(id=f"q{i}", domain_id=CYBER_ID, semester=5, is_active=i < 3)
            for i in range(10)
        ]
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_MCQ_POOL
        # program.mcq_total=20, only 3 active
        assert "only 3 active" in excinfo.value.detail


# ---------------------------------------------------------------------------
# 14-16. Descriptive
# ---------------------------------------------------------------------------


class TestDescriptiveSelection:
    """Descriptive questions are an ORGANIZATIONAL-only module.

    The organizational assessment is exactly one domain, so the descriptive
    quota is a plain configured count. Cross-domain allocation no longer
    applies to descriptive questions at all; the shared allocator is still
    exercised through hands-on (see TestHandsOnSelection and TestExactAllocation),
    which is the only multi-domain allocatable module left.
    """

    def test_organizational_descriptive_count_is_configurable(self):
        plan = plan_assessment(
            build(PROGRAM_1, [ORG_ID], [cfg(ORG_ID, "organizational", mcq=10, desc=3)])
        )
        assert plan.descriptive_total == 3
        assert [e.descriptive_count for e in plan.domains] == [3]
        assert len(set(plan.selected_descriptive_question_ids)) == 3

    def test_organizational_zero_descriptive_is_allowed(self):
        """20 MCQ + 0 descriptive must be representable."""
        plan = plan_assessment(
            build(PROGRAM_1, [ORG_ID], [cfg(ORG_ID, "organizational", mcq=20, desc=0)])
        )
        assert plan.mcq_total == 20
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []

    def test_organizational_zero_mcq_is_allowed(self):
        """0 MCQ + 5 descriptive must be representable, with no fixed total."""
        plan = plan_assessment(
            build(
                PROGRAM_1,
                [ORG_ID],
                [cfg(ORG_ID, "organizational", mcq=0, desc=5)],
                descriptive_pool=desc_items(
                    [f"od{i}" for i in range(8)], [ORG_ID]
                ),
            )
        )
        assert plan.mcq_total == 0
        assert plan.selected_mcq_ids == []
        assert plan.descriptive_total == 5

    def test_organizational_mcq_and_descriptive_mix_independently(self):
        """Two different mixes with different totals must both be exact."""
        rich_desc = desc_items([f"od{i}" for i in range(8)], [ORG_ID])
        fifteen_three = plan_assessment(
            build(
                PROGRAM_1,
                [ORG_ID],
                [cfg(ORG_ID, "organizational", mcq=15, desc=3)],
                descriptive_pool=rich_desc,
            )
        )
        ten_five = plan_assessment(
            build(
                PROGRAM_1,
                [ORG_ID],
                [cfg(ORG_ID, "organizational", mcq=10, desc=5)],
                descriptive_pool=rich_desc,
            )
        )
        assert (fifteen_three.mcq_total, fifteen_three.descriptive_total) == (15, 3)
        assert (ten_five.mcq_total, ten_five.descriptive_total) == (10, 5)
        assert fifteen_three.config_fingerprint != ten_five.config_fingerprint

    def test_technical_never_selects_descriptive_even_with_a_rich_pool(self):
        """The pool is deliberately generous and technical still gets none."""
        req = build(PROGRAM_5, [CYBER_ID, WEB_ID], module_configs=[])
        req.descriptive_pool = desc_items(
            [f"d{i}" for i in range(20)], [CYBER_ID, WEB_ID]
        )
        plan = plan_assessment(req)
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []
        assert [e.descriptive_count for e in plan.domains] == [0, 0]

    def test_descriptive_does_not_reduce_the_requested_count(self):
        req = build(
            PROGRAM_1,
            [ORG_ID],
            [cfg(ORG_ID, "organizational", mcq=10, desc=2)],
            descriptive_pool=desc_items(["d1"], [ORG_ID]),  # needs 2
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL

    def test_inactive_descriptive_questions_excluded(self):
        req = build(
            PROGRAM_1,
            [ORG_ID],
            [cfg(ORG_ID, "organizational", mcq=10, desc=4)],
            descriptive_pool=desc_items(
                ["d1", "d2", "d3", "d4"], [ORG_ID], active=False
            ),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL

    def test_shared_question_is_reallocated_so_both_domains_are_satisfied(self):
        """The case a greedy pass in domain order used to get WRONG.

        Now expressed with hands-on challenges, the only multi-domain
        allocatable module: Web's only eligible challenge is the one shared
        with Cyber, and it sorts before Cyber's exclusive one. A lowest-sorted
        greedy pass therefore starves Web unless the allocator can move Cyber
        onto its exclusive challenge instead. The plan must succeed.
        """
        pool = hands_items(["a-shared"], [CYBER_ID, WEB_ID]) + hands_items(
            ["b-cyber-only"], [CYBER_ID]
        )
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=1),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=1),
            ],
            hands_on_pool=pool,
        )
        plan = plan_assessment(req)

        assert plan.hands_on_total == 2
        assert sorted(plan.selected_hands_on_question_ids) == [
            "a-shared",
            "b-cyber-only",
        ]
        assert [(e.hands_on_enabled, e.hands_on_count) for e in plan.domains] == [
            (True, 1),
            (True, 1),
        ]


# ---------------------------------------------------------------------------
# 17-20. Hands-on
# ---------------------------------------------------------------------------


class TestHandsOnSelection:
    def test_per_domain_hands_on_counts(self):
        """Different modules: Cyber 1 + Web 1 -> 2 distinct challenges."""
        cyber = cfg(
            CYBER_ID,
            "senior",
            hands_on=True,
            hands_on_count=1,
            minutes=20,
            hands_on_module="sql_injection_employee_portal",
        )
        web = cfg(
            WEB_ID,
            "senior",
            hands_on=True,
            hands_on_count=1,
            minutes=10,
            hands_on_module="web_module_x",
        )
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [cyber, web],
                hands_on_pool=(
                    hands_items(
                        ["h-sql"], [CYBER_ID, WEB_ID], module=SQL_MODULE
                    )
                    + hands_items(["h-web"], [WEB_ID], module=OTHER_MODULE)
                ),
            )
        )
        assert plan.hands_on_total == 2
        assert len(set(plan.selected_hands_on_question_ids)) == 2
        assert [(e.hands_on_enabled, e.hands_on_count) for e in plan.domains] == [
            (True, 1),
            (True, 1),
        ]

    def test_hands_on_cross_domain_deduplication(self):
        """Two domains each needing 2, pool entirely shared: 4 unique.

        The domains run DIFFERENT modules, so no module-level deduplication
        applies and the allocator still needs 4 unique challenges.
        """
        shared = hands_items(
            ["h1", "h2", "h3", "h4"], [CYBER_ID, WEB_ID], module=SQL_MODULE
        ) + hands_items(
            ["w1", "w2", "w3", "w4"], [CYBER_ID, WEB_ID], module=OTHER_MODULE
        )
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(
                    CYBER_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=2,
                    hands_on_module=SQL_MODULE,
                ),
                cfg(
                    WEB_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=2,
                    hands_on_module=OTHER_MODULE,
                ),
            ],
            hands_on_pool=shared,
        )
        plan = plan_assessment(req)
        assert plan.hands_on_total == 4
        # Two distinct draws from EACH module's four-challenge pool.
        assert sorted(plan.selected_hands_on_question_ids) == [
            "h1",
            "h2",
            "w1",
            "w2",
        ]

    def test_hands_on_insufficient_unique_pool_fails(self):
        shared = hands_items(["h1", "h2", "h3"], [CYBER_ID, WEB_ID])
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=shared,
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_HANDS_ON_POOL

    def test_disabled_hands_on_with_count_is_rejected(self):
        bad = ModuleConfigInput(
            domain_id=CYBER_ID,
            applies_to="senior",
            hands_on_enabled=False,
            hands_on_count=1,
        )
        err = expect_failure(
            PlanningErrorKind.INVALID_MODULE_CONFIG,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID],
            module_configs=[bad],
        )
        assert "hands_on disabled but hands_on_count" in err.detail

    def test_disabled_hands_on_with_additional_minutes_is_rejected(self):
        """The Phase-2 invariant: a disabled module can never grant its time."""
        bad = ModuleConfigInput(
            domain_id=CYBER_ID,
            applies_to="senior",
            hands_on_enabled=False,
            hands_on_additional_minutes=20,
        )
        err = expect_failure(
            PlanningErrorKind.INVALID_MODULE_CONFIG,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID],
            module_configs=[bad],
        )
        assert "hands_on_additional_minutes is 20" in err.detail
        assert "must be 0" in err.detail

    def test_enabled_hands_on_contributes_additional_time(self):
        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], base=90))
        assert plan.domains[0].hands_on_additional_minutes == 20
        assert plan.additional_minutes == 20
        assert plan.duration_minutes == 110

    def test_disabled_hands_on_contributes_zero_time(self):
        plan = plan_assessment(build(PROGRAM_3, [CYBER_ID], [CYBER_JUNIOR], base=90))
        assert plan.domains[0].hands_on_enabled is False
        assert plan.additional_minutes == 0
        assert plan.duration_minutes == 90

    def test_enabled_with_zero_count_still_contributes_its_minutes(self):
        """Pins DB-permitted edge case: migration 016 allows enabled+count 0.

        The approved rule is "additional time is summed for ENABLED modules",
        so an enabled-but-empty module still contributes its minutes. If that
        is not wanted, migration 016 should gain the reverse CHECK.
        """
        odd = cfg(
            CYBER_ID, "senior", mcq=1, hands_on=True, hands_on_count=0, minutes=15
        )
        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID], [odd], base=60))
        assert plan.hands_on_total == 0
        assert plan.additional_minutes == 15
        assert plan.duration_minutes == 75


# ---------------------------------------------------------------------------
# 21. Duration
# ---------------------------------------------------------------------------


class TestDuration:
    def test_duration_is_base_plus_additional(self):
        cyber = cfg(
            CYBER_ID, "senior", mcq=1, hands_on=True, hands_on_count=1, minutes=20
        )
        web = cfg(WEB_ID, "senior", mcq=1, hands_on=True, hands_on_count=1, minutes=10)
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [cyber, web], base=90)
        )
        assert plan.base_duration_minutes == 90
        assert plan.additional_minutes == 30
        assert plan.duration_minutes == 120

    def test_no_additional_time_is_just_the_base(self):
        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], base=45))
        assert (
            plan.base_duration_minutes,
            plan.additional_minutes,
            plan.duration_minutes,
        ) == (45, 20, 65)

    def test_domains_duration_minutes_field_is_not_used(self):
        """domains.duration_minutes is deprecated/inert — never read."""
        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], base=33))
        assert plan.base_duration_minutes == 33
        assert plan.duration_minutes == 53


# ---------------------------------------------------------------------------
# 22-24. Coding stays global
# ---------------------------------------------------------------------------


class TestCoding:
    def test_coding_disabled_yields_zero(self):
        program = ProgramInput(
            semester=5,
            scope=Scope.TECHNICAL,
            tier="senior",
            max_domains=2,
            coding_enabled=False,
        )
        plan = plan_assessment(build(program, [CYBER_ID], [CYBER_SENIOR], coding=5))
        assert plan.coding_enabled is False
        assert plan.coding_count == 0
        assert plan.coding_total == 0
        assert plan.selected_coding_problem_ids == []

    def test_technical_coding_enabled_uses_the_global_count(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR], coding=3)
        )
        assert plan.coding_enabled is True
        assert plan.coding_count == 3
        assert plan.coding_total == 3
        assert len(set(plan.selected_coding_problem_ids)) == 3

    def test_coding_is_domain_independent(self):
        """Coding ids come from the global pool, not from domain filtering."""
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
        req.coding_pool = coding_items(10, "global")
        plan = plan_assessment(req)
        assert all(
            cid.startswith("global-") for cid in plan.selected_coding_problem_ids
        )

    def test_insufficient_coding_pool_fails(self):
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=5)
        req.coding_pool = coding_items(2)
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_CODING_POOL
        assert "need 5" in excinfo.value.detail

    def test_inactive_coding_problems_excluded(self):
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=3)
        req.coding_pool = [
            CodingPoolItem(id=f"c{i}", is_active=i < 2) for i in range(10)
        ]
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_CODING_POOL

    def test_exactly_two_dsa_problems_are_drawn_from_a_larger_pool(self):
        """The DSA pool will hold 4-5 active problems; each attempt gets 2.

        The draw must be a genuine subset selection (not the first two of the
        pool), and different per-attempt seeds must be able to yield different
        pairs — otherwise every candidate would receive the same problems.
        """
        pool_ids = {f"dsa-{i:02d}" for i in range(5)}
        draws = set()
        for seed in range(1, 12):
            req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
            req.coding_pool = coding_items(5, "dsa")
            req.seed = seed
            selected = plan_assessment(req).selected_coding_problem_ids
            assert len(selected) == 2
            assert len(set(selected)) == 2
            assert set(selected) <= pool_ids
            draws.add(tuple(selected))
        assert len(draws) > 1

    def test_a_seeded_coding_draw_is_reproducible(self):
        """Same seed + same inputs => the same frozen DSA pair, across calls."""

        def once():
            req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
            req.coding_pool = coding_items(5, "dsa")
            req.seed = 99
            return plan_assessment(req).selected_coding_problem_ids

        assert once() == once()


# ---------------------------------------------------------------------------
# 25-28. Determinism, fingerprint, purity, safety
# ---------------------------------------------------------------------------


class TestDeterminismAndSafety:
    def test_identical_inputs_produce_identical_plans(self):
        req = build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR], coding=2)
        first = plan_assessment(req)
        second = plan_assessment(req)
        assert first.model_dump() == second.model_dump()

    def test_seeded_selection_is_reproducible_per_seed(self):
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
        req.seed = 1234
        a = plan_assessment(req)
        b = plan_assessment(req)
        assert a.model_dump() == b.model_dump()

    def test_seed_changes_selection_but_not_configuration(self):
        base_req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
        base_req.seed = 1
        other_req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
        other_req.seed = 2
        one = plan_assessment(base_req)
        two = plan_assessment(other_req)

        assert one.config_fingerprint == two.config_fingerprint
        # same configuration, different draw (pool is large enough to differ)
        assert one.selected_mcq_ids != two.selected_mcq_ids

    def test_no_seed_is_stable_across_separate_requests(self):
        req_a = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        req_b = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        assert (
            plan_assessment(req_a).selected_mcq_ids
            == plan_assessment(req_b).selected_mcq_ids
        )

    def test_domain_order_is_independent_of_request_order(self):
        """Selection order follows (name, id), not the caller's list order."""
        forward = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR])
        )
        reverse = plan_assessment(
            build(PROGRAM_5, [WEB_ID, CYBER_ID], [CYBER_SENIOR, WEB_SENIOR])
        )
        assert forward.domain_ids == reverse.domain_ids == [CYBER_ID, WEB_ID]
        assert forward.model_dump() == reverse.model_dump()

    def test_fingerprint_changes_when_planning_config_changes(self):
        baseline = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], base=90)
        )
        changed_cases = {
            # program.mcq_total changed: use a different program.
            "mcq_total_changed": build(
                PROGRAM_3,
                [CYBER_ID],
                module_configs=[],
                base=90,
            ),
            "hands_on_enabled": build(
                PROGRAM_5,
                [CYBER_ID],
                [cfg(CYBER_ID, "senior", mcq=5, desc=2)],
                base=90,
            ),
            "hands_on_count": build(
                PROGRAM_5,
                [CYBER_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        mcq=5,
                        desc=2,
                        hands_on=True,
                        hands_on_count=2,
                        minutes=20,
                    )
                ],
                base=90,
            ),
            "additional_minutes": build(
                PROGRAM_5,
                [CYBER_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        mcq=5,
                        desc=2,
                        hands_on=True,
                        hands_on_count=1,
                        minutes=5,
                    )
                ],
                base=90,
            ),
            "base_duration": build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], base=120),
            "coding_count": build(
                PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=4, base=90
            ),
            "semester": build(
                PROGRAM_3,
                [CYBER_ID],
                [
                    cfg(
                        CYBER_ID,
                        "junior",
                        mcq=5,
                        desc=2,
                        hands_on=True,
                        hands_on_count=1,
                        minutes=20,
                    )
                ],
                base=90,
            ),
        }
        for label, request in changed_cases.items():
            assert (
                plan_assessment(request).config_fingerprint
                != baseline.config_fingerprint
            ), f"fingerprint did not change for {label}"

    def test_fingerprint_is_stable_for_the_same_configuration(self):
        a = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR])
        )
        b = plan_assessment(
            build(PROGRAM_5, [WEB_ID, CYBER_ID], [WEB_SENIOR, CYBER_SENIOR])
        )
        assert a.config_fingerprint == b.config_fingerprint

    def test_planner_does_not_mutate_its_inputs(self):
        req = build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR], coding=2)
        before = copy.deepcopy(req.model_dump())
        plan_assessment(req)
        assert req.model_dump() == before

    def test_plan_contains_no_sensitive_fields(self):
        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2))
        serialized = plan.model_dump_json().lower()
        for forbidden in (
            "correct_option",
            "explanation",
            "expected_flag",
            "is_correct",
            "admin_remark",
            "score",
            "is_public",
            "hidden",
        ):
            assert forbidden not in serialized, forbidden

    def test_sensitive_extra_fields_on_pool_rows_never_reach_the_plan(self):
        """Supabase rows are usually SELECT *, so extras must be dropped."""
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=1)
        # The technical rule needs the configured mcq_count per domain, so
        # the pool has to be big enough for the selection to succeed.
        req.mcq_pool = [
            MCQPoolItem(
                id=f"q{i}",
                domain_id=CYBER_ID,
                semester=5,
                correct_option="A",
                explanation="because",  # type: ignore
            )
            for i in range(40)
        ]
        req.descriptive_pool = [
            DescriptivePoolItem(
                id=f"d{i}",
                domain_ids=[CYBER_ID],
                answer_key="secret",  # type: ignore
            )
            for i in range(10)
        ]
        req.hands_on_pool = [
            HandsOnPoolItem(
                id=f"h{i}",
                domain_ids=[CYBER_ID],
                expected_flag="FLAG{secret}",  # type: ignore
            )
            for i in range(10)
        ]
        serialized = plan_assessment(req).model_dump_json().lower()
        for leaked in (
            "correct_option",
            "explanation",
            "expected_flag",
            "answer_key",
            "flag{secret}",
        ):
            assert leaked not in serialized, leaked

    def test_plan_is_frozen(self):
        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR]))
        with pytest.raises(ValidationError):
            plan.mcq_total = 999  # type: ignore

    def test_plan_is_json_serialisable(self):
        import json

        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2))
        round_tripped = json.loads(plan.model_dump_json())
        assert round_tripped["plan_version"] == 2
        assert round_tripped["config_source"] == "modular"
        assert round_tripped["coding_total"] == 2


# ---------------------------------------------------------------------------
# 30. Multi-domain aggregation + purity guarantees
# ---------------------------------------------------------------------------


class TestMultiDomainAggregation:
    def test_two_technical_domains_aggregate_everything(self):
        """Senior selects CyberSec + Web: the documented worked example."""
        cyber = cfg(
            CYBER_ID,
            "senior",
            mcq=5,
            desc=2,
            hands_on=True,
            hands_on_count=1,
            minutes=20,
        )
        web = cfg(WEB_ID, "senior", mcq=5, desc=1)
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [cyber, web], coding=2, base=90)
        )
        # Two senior domains: program.mcq_total=20 split 10+10.
        assert plan.mcq_total == 20
        assert [e.mcq_count for e in plan.domains] == [10, 10]
        # Descriptive is organizational-only, so neither domain contributes any.
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 1
        assert plan.coding_total == 2
        assert plan.additional_minutes == 20
        assert plan.duration_minutes == 110
        assert plan.domain_ids == [CYBER_ID, WEB_ID]

    def test_junior_two_domains_with_no_hands_on(self):
        """Junior CyberSec + Web: hands-on is senior-only, so it is absent."""
        plan = plan_assessment(
            build(
                PROGRAM_3,
                [CYBER_ID, WEB_ID],
                module_configs=[],
                coding=2,
                base=90,
            )
        )
        assert plan.mcq_total == 20  # PROGRAM_3.mcq_total=20, split 10+10
        assert [e.mcq_count for e in plan.domains] == [10, 10]
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 0
        assert plan.selected_hands_on_question_ids == []
        assert plan.practicals == []
        assert plan.additional_minutes == 0
        assert plan.duration_minutes == 90

    def test_per_domain_mcq_counts_sum_to_total(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], module_configs=[])
        )
        # 10 + 10 = 20 (program.mcq_total split evenly)
        assert sum(e.mcq_count for e in plan.domains) == plan.mcq_total
        assert plan.mcq_total == 20

    def test_per_domain_descriptive_counts_sum_to_total_after_dedup(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR])
        )
        assert sum(e.descriptive_count for e in plan.domains) == plan.descriptive_total


class TestExactAllocation:
    """The allocator must fail only when NO valid assignment exists.

    These tests pin the difference between "this particular ordering ran out of
    candidates" and "no allocation can satisfy the quotas".
    """

    def test_cascading_reallocation_solves_what_greedy_could_not(self):
        """Both domains want 2; Web can only use the two shared challenges.

        The shared ids sort before Cyber's exclusives, so a greedy pass would
        hand both shared challenges to Cyber and then fail Web. Feasibility
        requires Cyber to end up on its two exclusive challenges instead.

        (Expressed with hands-on: it is the only allocatable module that can
        span two domains now that descriptive is organizational-only.)
        """
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=(
                hands_items(["a1", "a2"], [CYBER_ID, WEB_ID])
                + hands_items(["z1", "z2"], [CYBER_ID])
            ),
        )
        plan = plan_assessment(req)
        assert plan.hands_on_total == 4
        assert sorted(plan.selected_hands_on_question_ids) == [
            "a1",
            "a2",
            "z1",
            "z2",
        ]
        assert [e.hands_on_count for e in plan.domains] == [2, 2]

    def test_hands_on_shared_challenge_is_reallocated(self):
        """The hands-on equivalent of the descriptive reallocation case.

        Cyber's module pool has the shared challenge plus its own exclusive
        one, so Cyber ends up on both and Web keeps its own module's
        challenge: 3 unique ids overall, with no cross-module borrowing.
        """
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(
                    CYBER_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=2,
                    hands_on_module="sql_injection_employee_portal",
                ),
                cfg(
                    WEB_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=1,
                    hands_on_module="web_module_x",
                ),
            ],
            hands_on_pool=[
                HandsOnPoolItem(
                    id="sql-a",
                    domain_ids=[CYBER_ID, WEB_ID],
                    hands_on_modules=["sql_injection_employee_portal"],
                ),
                HandsOnPoolItem(
                    id="sql-b",
                    domain_ids=[CYBER_ID],
                    hands_on_modules=["sql_injection_employee_portal"],
                ),
                HandsOnPoolItem(
                    id="web-a",
                    domain_ids=[WEB_ID],
                    hands_on_modules=["web_module_x"],
                ),
            ],
        )
        plan = plan_assessment(req)
        assert plan.hands_on_total == 3
        assert sorted(plan.selected_hands_on_question_ids) == [
            "sql-a",
            "sql-b",
            "web-a",
        ]

    def test_hands_on_cascading_reallocation(self):
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=(
                hands_items(["a1", "a2"], [CYBER_ID, WEB_ID])
                + hands_items(["z1", "z2"], [CYBER_ID])
            ),
        )
        plan = plan_assessment(req)
        assert plan.hands_on_total == 4
        assert sorted(plan.selected_hands_on_question_ids) == [
            "a1",
            "a2",
            "z1",
            "z2",
        ]

    def test_impossible_quota_set_still_fails(self):
        """A 2 + 2 quota over only 3 unique challenges is genuinely infeasible."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=hands_items(["s1", "s2", "s3"], [CYBER_ID, WEB_ID]),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_HANDS_ON_POOL
        assert "No valid allocation" in excinfo.value.detail

    def test_impossible_hands_on_quota_set_still_fails(self):
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=hands_items(["s1", "s2", "s3"], [CYBER_ID, WEB_ID]),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_HANDS_ON_POOL

    def test_partially_satisfiable_quotas_still_fail(self):
        """One domain could be filled but not both, so the plan must fail."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=1),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=5),
            ],
            hands_on_pool=hands_items(["s1", "s2"], [CYBER_ID, WEB_ID]),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_HANDS_ON_POOL


# ---------------------------------------------------------------------------
# Shared hands-on modules (cross-domain deduplication by challenge module)
# ---------------------------------------------------------------------------


SQL_MODULE = "sql_injection_employee_portal"
OTHER_MODULE = "web_module_x"


class TestSharedHandsOnModule:
    """One module installed on several domains is ONE requirement group.

    The production shape: DevOps and Web Development both run the SQL
    hands-on challenge (the only challenge that exists today, migration
    012). Each domain's module row asks for 1, but both requirements point
    at the SAME module, so the candidate performs exactly one challenge and
    it counts towards both domains' requirement. The previous behaviour
    summed the quotas (1 + 1 = 2), which made the combined selection fail
    on a single-question pool.
    """

    def _sql_pool(self, ids=("sql-1", "sql-2", "sql-3")):
        return hands_items(list(ids), [CYBER_ID, WEB_ID], module=SQL_MODULE)

    def _sql_rows(self, ids, domain_ids):
        """Pool rows carrying an explicit module registry."""
        return [
            HandsOnPoolItem(
                id=item_id,
                domain_ids=list(domain_ids),
                hands_on_modules=[SQL_MODULE],
            )
            for item_id in ids
        ]

    def test_first_domain_with_the_shared_module_draws_one(self):
        """DevOps alone -> exactly 1 SQL hands-on challenge."""
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    )
                ],
                hands_on_pool=self._sql_pool(),
            )
        )
        assert plan.hands_on_total == 1
        assert len(plan.selected_hands_on_question_ids) == 1

    def test_second_domain_with_the_shared_module_draws_one(self):
        """Web Development alone -> exactly 1 SQL hands-on challenge."""
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [WEB_ID],
                [
                    cfg(
                        WEB_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    )
                ],
                hands_on_pool=self._sql_pool(),
            )
        )
        assert plan.hands_on_total == 1
        assert len(plan.selected_hands_on_question_ids) == 1

    def test_both_domains_sharing_one_module_draw_exactly_one(self):
        """DevOps + Web Development: 1 + 1 requests -> ONE shared challenge.

        This is the exact production failure: a single-challenge SQL pool
        used to be refused with "they require 2 unique item(s) in total".
        """
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                    cfg(
                        WEB_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                ],
                # THE production pool shape: exactly one SQL challenge.
                hands_on_pool=self._sql_pool(("sql-1",)),
            )
        )
        assert plan.hands_on_total == 1
        assert plan.selected_hands_on_question_ids == ["sql-1"]
        # Both domains still report the module as enabled with its own count.
        assert [(e.hands_on_enabled, e.hands_on_count) for e in plan.domains] == [
            (True, 1),
            (True, 1),
        ]
        # The one practical arm carries the single shared challenge.
        assert plan.practicals[0].arms[0].question_ids == ["sql-1"]

    def test_higher_request_takes_the_max_not_the_sum(self):
        """Same module, 2 + 1 requests over a 2-challenge pool: 2, not 3."""
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=2,
                        hands_on_module=SQL_MODULE,
                    ),
                    cfg(
                        WEB_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                ],
                hands_on_pool=self._sql_pool(("sql-1", "sql-2")),
            )
        )
        assert plan.hands_on_total == 2
        assert sorted(plan.selected_hands_on_question_ids) == ["sql-1", "sql-2"]

    def test_shortfall_of_the_shared_module_pool_still_fails(self):
        """Dedup removes double counting, but a real shortage still fails."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(
                    CYBER_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=2,
                    hands_on_module=SQL_MODULE,
                ),
                cfg(
                    WEB_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=1,
                    hands_on_module=SQL_MODULE,
                ),
            ],
            hands_on_pool=self._sql_pool(("sql-1",)),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_HANDS_ON_POOL

    def test_module_identity_groups_even_when_domain_ids_differ(self):
        """Grouping keys on the MODULE, not on where rows advertise it.

        Cyber's pool holds the SQL rows (plus an exclusive module row) while
        Web's SQL rows were tagged differently: both selected domains still
        land in one SQL group because their configured module is identical.
        """
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                    cfg(
                        WEB_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                ],
                # Cyber sees the SQL rows AND an unrelated module; Web's SQL
                # row overlaps only WEB_ID. The SQL group must still merge.
                hands_on_pool=(
                    self._sql_rows(["sql-a"], [CYBER_ID])
                    + self._sql_rows(["sql-b"], [WEB_ID])
                    + [
                        HandsOnPoolItem(
                            id="other-1",
                            domain_ids=[CYBER_ID],
                            hands_on_modules=[OTHER_MODULE],
                        )
                    ]
                ),
            )
        )
        assert plan.hands_on_total == 1
        assert plan.selected_hands_on_question_ids == ["sql-a"]

    def test_three_domains_sharing_the_same_module_draw_exactly_one(self):
        """Extensibility: a third domain adopting SQL dedups automatically."""
        devops = DomainInput(
            id="d-devops",
            name="DevOps",
            slug="devops",
            assessment_scope="technical",
        )
        program = ProgramInput(
            semester=5,
            scope=Scope.TECHNICAL,
            tier="senior",
            max_domains=3,
            coding_enabled=True,
            mcq_total=30,
        )
        req = build(
            program,
            [CYBER_ID, WEB_ID, "d-devops"],
            [
                cfg(
                    CYBER_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=1,
                    hands_on_module=SQL_MODULE,
                ),
                cfg(
                    WEB_ID,
                    "senior",
                    hands_on=True,
                    hands_on_count=1,
                    hands_on_module=SQL_MODULE,
                ),
                cfg(
                    "d-devops",
                    "senior",
                    hands_on=True,
                    hands_on_count=1,
                    hands_on_module=SQL_MODULE,
                ),
            ],
            hands_on_pool=self._sql_pool(("sql-1",)),
        )
        # build() only knows the CATALOGUE domains; add DevOps explicitly.
        req.domains = [CYBER, WEB, devops]
        # big_pools() only seeds MCQs for CATALOGUE domains.
        req.mcq_pool = list(req.mcq_pool) + mcq_items(
            "d-devops", program.semester, 25, "q-devops"
        )
        plan = plan_assessment(req)
        assert plan.hands_on_total == 1
        assert plan.selected_hands_on_question_ids == ["sql-1"]
        assert [e.hands_on_enabled for e in plan.domains] == [True, True, True]
        assert all(e.hands_on_count == 1 for e in plan.domains)

    def test_two_domains_with_different_modules_draw_two(self):
        """Preserved: genuinely different modules stay distinct requirements."""
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                    cfg(
                        WEB_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=OTHER_MODULE,
                    ),
                ],
                hands_on_pool=(
                    self._sql_rows(["sql-1"], [CYBER_ID, WEB_ID])
                    + [
                        HandsOnPoolItem(
                            id="other-1",
                            domain_ids=[WEB_ID],
                            hands_on_modules=[OTHER_MODULE],
                        )
                    ]
                ),
            )
        )
        assert plan.hands_on_total == 2
        assert sorted(plan.selected_hands_on_question_ids) == ["other-1", "sql-1"]

    def test_shared_module_selection_varies_under_a_seed(self):
        """The seeded draw still varies WITHIN the shared module's pool."""
        drawn = set()

        for seed in range(1, 21):
            req = build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                    cfg(
                        WEB_ID,
                        "senior",
                        hands_on=True,
                        hands_on_count=1,
                        hands_on_module=SQL_MODULE,
                    ),
                ],
                hands_on_pool=self._sql_pool(
                    ("sql-1", "sql-2", "sql-3", "sql-4", "sql-5")
                ),
            )
            req.seed = seed
            plan = plan_assessment(req)
            assert plan.hands_on_total == 1
            drawn.update(plan.selected_hands_on_question_ids)

        assert len(drawn) > 1

    def test_selected_ids_are_globally_unique(self):
        """Heavy overlap: no id may appear twice anywhere in the plan."""
        shared = ["s1", "s2", "s3"]
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", desc=2, hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", desc=2, hands_on=True, hands_on_count=2),
            ],
            # A generous descriptive pool is supplied deliberately: technical
            # must ignore it entirely.
            descriptive_pool=(
                desc_items(shared, [CYBER_ID, WEB_ID])
                + desc_items(["c1", "c2"], [CYBER_ID])
                + desc_items(["w1", "w2"], [WEB_ID])
            ),
            hands_on_pool=(
                hands_items(shared, [CYBER_ID, WEB_ID])
                + hands_items(["hc1", "hc2"], [CYBER_ID])
                + hands_items(["hw1", "hw2"], [WEB_ID])
            ),
        )
        plan = plan_assessment(req)

        for selection in (
            plan.selected_mcq_ids,
            plan.selected_descriptive_question_ids,
            plan.selected_hands_on_question_ids,
            plan.selected_coding_problem_ids,
        ):
            assert len(selection) == len(set(selection))
        # Technical never takes descriptive, whatever the configured counts say.
        assert plan.descriptive_total == 0
        # Hands-on quotas are met exactly, never reduced.
        assert plan.hands_on_total == 4
        assert [e.descriptive_count for e in plan.domains] == [0, 0]
        assert [e.hands_on_count for e in plan.domains] == [2, 2]

    def test_allocation_is_deterministic_across_repeated_calls(self):
        request = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=(
                hands_items(["a1", "a2"], [CYBER_ID, WEB_ID])
                + hands_items(["z1", "z2"], [CYBER_ID])
            ),
        )
        dumps = [plan_assessment(request).model_dump() for _ in range(5)]
        assert all(dump == dumps[0] for dump in dumps)
        assert dumps[0]["hands_on_total"] == 4

    def test_allocation_is_deterministic_under_a_seed(self):
        def run():
            request = build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [
                    cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                    cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
                ],
                hands_on_pool=hands_items(
                    ["q1", "q2", "q3", "q4", "q5", "q6"], [CYBER_ID, WEB_ID]
                ),
            )
            request.seed = 7
            return plan_assessment(request).model_dump()

        first = run()
        assert first == run()
        assert first["hands_on_total"] == 4

    def test_allocation_still_meets_quotas_with_a_seed(self):
        request = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=hands_items(
                ["q1", "q2", "q3", "q4", "q5", "q6"], [CYBER_ID, WEB_ID]
            ),
        )
        request.seed = 99
        plan = plan_assessment(request)
        assert plan.hands_on_total == 4
        assert len(set(plan.selected_hands_on_question_ids)) == 4
        assert [e.hands_on_count for e in plan.domains] == [2, 2]

    def test_via_the_allocator_api_directly(self):
        """Unit-test the allocator on the raw structure, not via a request."""
        from services.assessment_planner import _allocate_quotas

        quotas = {"a": 1, "b": 1}
        eligible = {"a": ["shared", "a-only"], "b": ["shared"]}
        assert _allocate_quotas(["a", "b"], quotas, eligible) == {
            "a": ["a-only"],
            "b": ["shared"],
        }

    def test_allocator_returns_none_when_infeasible(self):
        from services.assessment_planner import _allocate_quotas

        assert (
            _allocate_quotas(
                ["a", "b"],
                {"a": 2, "b": 2},
                {"a": ["s1", "s2", "s3"], "b": ["s1", "s2", "s3"]},
            )
            is None
        )

    def test_allocator_handles_zero_quotas(self):
        from services.assessment_planner import _allocate_quotas

        assert _allocate_quotas(["a", "b"], {"a": 0, "b": 0}, {"a": [], "b": []}) == {
            "a": [],
            "b": [],
        }
        assert _allocate_quotas(
            ["a", "b"], {"a": 0, "b": 1}, {"a": ["x"], "b": ["x", "y"]}
        ) == {"a": [], "b": ["x"]}


class TestPurityGuarantees:
    def test_planner_imports_only_pure_standard_library_modules(self):
        source = Path(assessment_planner.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {"hashlib", "json", "random", "enum", "typing", "pydantic"}
        assert "core" not in imported
        assert "supabase" not in imported

    def test_importing_the_planner_pulls_in_no_supabase_client(self):
        backend_dir = Path(assessment_planner.__file__).resolve().parent.parent
        probe = (
            "import sys; import services.assessment_planner; "
            "print(','.join(sorted(m for m in sys.modules "
            "if 'supabase' in m.lower() or m.startswith('core'))))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == ""

    def test_duplicate_rows_in_a_pool_are_counted_once(self):
        """Pool ids are primary keys, so a repeated id is one question —
        a duplicated row must never satisfy two slots."""
        # Descriptive duplication is checked through the organizational scope,
        # the only one that selects descriptive questions now.
        dupes = desc_items(["d1", "d1"], [ORG_ID]) + desc_items(["d2"], [ORG_ID])
        req = build(
            PROGRAM_1,
            [ORG_ID],
            [cfg(ORG_ID, "organizational", mcq=10, desc=3)],
            descriptive_pool=dupes,
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        # Only 2 unique questions exist, so a 3 question quota must fail
        # rather than double-counting d1.
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL

    def test_duplicate_mcq_rows_are_counted_once(self):
        req = build(PROGRAM_5, [CYBER_ID], module_configs=[])
        # 20 unique ids, each supplied twice: program.mcq_total=20,
        # so only deduplication makes this satisfiable (pool > 20).
        req.mcq_pool = (
            mcq_items(CYBER_ID, 5, 20, "q") + mcq_items(CYBER_ID, 5, 20, "q")
        )
        plan = plan_assessment(req)
        assert plan.mcq_total == 20  # PROGRAM_5.mcq_total
        assert len(set(plan.selected_mcq_ids)) == 20

    def test_planner_never_raises_for_missing_pools_when_nothing_is_needed(self):
        """Organizational with zero counts still produces a valid plan."""
        org = cfg(ORG_ID, "organizational", mcq=0, desc=0)
        plan = plan_assessment(
            AssessmentPlanRequest(
                program=PROGRAM_1,
                requested_domain_ids=[ORG_ID],
                domains=CATALOGUE,
                module_configs=[org],
                base_duration_minutes=30,
            )
        )
        assert plan.mcq_total == 0
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 0
        assert plan.coding_total == 0
        assert plan.duration_minutes == 30


# ---------------------------------------------------------------------------
# MCQ ordering: the final list must be shuffled across domains when a
# seed is provided, and deterministic for identical inputs.
# ---------------------------------------------------------------------------


class TestMCQOrdering:
    """Verify that the planner's MCQ final-shuffle restores the pre-Phase-4

    behaviour where MCQs are interleaved across domains rather than grouped.
    The shuffle uses the same RNG as the rest of the planner, so it is
    deterministic per seed and reproducible across identical requests.
    """

    def test_same_seed_produces_same_mcq_order(self):
        """Two identical seeded requests must return the same MCQ list."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            module_configs=[],
        )
        req.seed = 42
        a = plan_assessment(req)
        b = plan_assessment(req)
        assert a.selected_mcq_ids == b.selected_mcq_ids

    def test_different_seeds_can_produce_different_mcq_order(self):
        """With enough MCQs in the pool, different seeds must shuffle

        differently (the two MCQ lists should differ in at least one
        position).
        """
        req_a = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            module_configs=[],
        )
        req_a.seed = 1
        req_b = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            module_configs=[],
        )
        req_b.seed = 2
        a = plan_assessment(req_a)
        b = plan_assessment(req_b)
        # Both have 20 MCQs (10 per domain from program.mcq_total=20).
        assert a.mcq_total == 20
        assert b.mcq_total == 20
        assert a.selected_mcq_ids != b.selected_mcq_ids

    def test_mcq_ids_are_not_grouped_by_domain(self):
        """With a seed, MCQs from different domains must be interleaved

        rather than appearing as domain-1-then-domain-2 blocks.

        With a pool of 25 per domain and 10 MCQs per domain, a seeded
        request should produce interleaving in at least some runs.
        """
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            module_configs=[],
        )
        req.seed = 7
        plan = plan_assessment(req)
        ids = plan.selected_mcq_ids
        # All IDs should be from the MCQ pool (domain-prefixed)
        assert len(ids) == 20  # 10 (cyber) + 10 (web)
        assert len(set(ids)) == 20
        # With a seed, the list should not be purely domain-grouped.
        # Check that at least one transition changes domain prefix.
        domain_prefixes = [qid.split("-")[1] if "-" in qid else "" for qid in ids]
        transitions = sum(
            1
            for i in range(1, len(domain_prefixes))
            if domain_prefixes[i] != domain_prefixes[i - 1]
        )
        # With 10 IDs from 2 domains, some interleaving is expected.
        assert transitions >= 1, (
            f"Expected interleaving across domains, got prefixes: " f"{domain_prefixes}"
        )

    def test_junior_technical_never_carries_a_practical(self):
        """Requirement: Junior = MCQs + 2 DSA/Coding, no practical of any kind.

        A junior module row that wrongly enables hands-on must not leak a
        challenge or its additional minutes into a junior assessment.
        """
        wrong = cfg(
            CYBER_ID, "junior", mcq=5, hands_on=True, hands_on_count=1, minutes=30
        )
        req = build(PROGRAM_3, [CYBER_ID], [wrong], base=90)
        req.hands_on_pool = hands_items(["h1"], [CYBER_ID])
        plan = plan_assessment(req)
        assert plan.hands_on_total == 0
        assert plan.selected_hands_on_question_ids == []
        assert plan.practicals == []
        assert plan.additional_minutes == 0
        assert plan.duration_minutes == 90

    def test_senior_technical_single_domain_carries_one_single_arm_module(self):
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        req.hands_on_pool = hands_items(["h1", "h2"], [CYBER_ID])
        plan = plan_assessment(req)
        assert len(plan.practicals) == 1
        module = plan.practicals[0]
        assert module.module_kind.value == "single"
        assert module.scoring.value == "single"
        assert len(module.arms) == 1
        assert module.arms[0].kind.value == "hands_on"
        assert len(module.arms[0].question_ids) == 1

    def test_no_seed_keeps_sorted_mcq_order(self):
        """Without a seed, MCQs remain in the deterministic sorted order."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            module_configs=[],
        )
        # seed=None (default)
        plan = plan_assessment(req)
        assert plan.selected_mcq_ids == sorted(plan.selected_mcq_ids)

    def test_shuffled_mcq_ids_still_all_belong_to_selected_domains(self):
        """Shuffling must not inject or drop IDs."""
        req = build(PROGRAM_5, [CYBER_ID], module_configs=[])
        req.seed = 99
        plan = plan_assessment(req)
        # Every MCQ must belong to Cyber Security (the only selected domain)
        for qid in plan.selected_mcq_ids:
            assert CYBER_ID in qid or qid.startswith("q" + CYBER_ID)
        assert len(plan.selected_mcq_ids) == 20  # PROGRAM_5.mcq_total
        assert len(set(plan.selected_mcq_ids)) == 20


class TestTechnicalDescriptiveNeverRequired:
    """Descriptive questions are strictly an Organizational Roles component.

    Technical assessments (Junior/Senior) must NEVER require, select,
    validate, or count descriptive questions — regardless of:
    - assessment_config.descriptive_question_count value
    - assessment_module_config.descriptive_count on a technical row
    - presence/absence of descriptive questions in the pool
    """

    def test_semester_3_technical_succeeds_with_zero_descriptive_pool(self):
        """Junior technical with no descriptive questions at all: no error."""
        plan = plan_assessment(
            build(PROGRAM_3, [CYBER_ID], module_configs=[], coding=2)
        )
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []
        assert plan.mcq_total == 20
        assert plan.coding_total == 2

    def test_semester_5_technical_succeeds_with_zero_descriptive_pool(self):
        """Senior technical with no descriptive questions: no error."""
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
        )
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []
        assert plan.mcq_total == 20
        assert plan.coding_total == 2

    def test_two_technical_domains_no_descriptive(self):
        """Two technical domains with zero descriptive: succeeds."""
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], module_configs=[], coding=2)
        )
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []
        assert plan.mcq_total == 20
        assert plan.coding_total == 2

    def test_technical_module_config_descriptive_ignored(self):
        """A technical module row with descriptive_count>0 is still ignored."""
        bad_config = cfg(CYBER_ID, "senior", mcq=5, desc=3)
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], [bad_config], coding=2)
        )
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []

    def test_technical_with_rich_descriptive_pool_still_gets_none(self):
        """Even with 50 descriptive questions in pool, technical gets zero."""
        req = build(PROGRAM_5, [CYBER_ID], module_configs=[], coding=2)
        req.descriptive_pool = desc_items(
            [f"d{i}" for i in range(50)], [CYBER_ID]
        )
        plan = plan_assessment(req)
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []

    def test_organizational_descriptive_still_validates_pool(self):
        """Organizational with descriptive=2 but only 1 question: FAILS."""
        req = build(
            PROGRAM_1,
            [ORG_ID],
            [cfg(ORG_ID, "organizational", mcq=5, desc=2)],
            descriptive_pool=desc_items(["d1"], [ORG_ID]),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL

    def test_organizational_descriptive_succeeds_with_sufficient_pool(self):
        """Organizational with desc=2 and 2 questions: succeeds."""
        plan = plan_assessment(
            build(
                PROGRAM_1,
                [ORG_ID],
                [cfg(ORG_ID, "organizational", mcq=5, desc=2)],
                descriptive_pool=desc_items(["d1", "d2"], [ORG_ID]),
            )
        )
        assert plan.mcq_total == 5
        assert plan.descriptive_total == 2
        assert plan.coding_total == 0


# ---------------------------------------------------------------------------
# Production-incident regression spec (September 2026)
# ---------------------------------------------------------------------------


def _program_with_mcq_total(program, total):
    """The same programme with a different master technical MCQ total."""
    return program.model_copy(update={"mcq_total": total})


class TestProductionRegressionSemesterComposition:
    """The ONE correct composition per semester, pinned against the incident.

    In the September 2026 production test, different Sem 3 candidates received
    different compositions (MCQ-only / coding-only / hands-on / mixed). These
    tests pin the intended rules:

        Sem 3 (junior technical): MCQs split evenly from the master technical
        MCQ total, 2 global coding problems, NO descriptive, NO hands-on —
        even if a mis-authored junior module row enables hands-on.

        Sem 5 (senior technical): MCQs + 2 global coding problems, NO
        descriptive, hands-on only per senior module configuration.

        Sem 1 (organizational): MCQ + descriptive from the module row, never
        coding.
    """

    # ---- Sem 3 / junior technical -----------------------------------------

    def test_sem3_one_domain_master_total_of_4_gives_4_mcqs(self):
        """The production example: total=4, one domain -> all 4 MCQs."""
        junior_4 = _program_with_mcq_total(PROGRAM_3, 4)
        plan = plan_assessment(
            build(junior_4, [CYBER_ID], module_configs=[], coding=2)
        )
        assert plan.mcq_total == 4
        assert [e.mcq_count for e in plan.domains] == [4]
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 0
        assert plan.coding_total == 2

    def test_sem3_two_domains_master_total_of_4_splits_two_and_two(self):
        """Selecting a second domain must NOT increase the MCQ total."""
        junior_4 = _program_with_mcq_total(PROGRAM_3, 4)
        one_domain = plan_assessment(
            build(junior_4, [CYBER_ID], module_configs=[], coding=2)
        )
        two_domains = plan_assessment(
            build(junior_4, [CYBER_ID, WEB_ID], module_configs=[], coding=2)
        )
        assert two_domains.mcq_total == one_domain.mcq_total == 4
        assert [e.mcq_count for e in two_domains.domains] == [2, 2]
        assert two_domains.descriptive_total == 0
        assert two_domains.hands_on_total == 0
        assert two_domains.coding_total == 2

    def test_sem3_master_total_of_20_gives_20_or_10_plus_10(self):
        """The full-scale example: 20 -> one domain, 10+10 -> two domains."""
        single = plan_assessment(
            build(PROGRAM_3, [CYBER_ID], module_configs=[], coding=2)
        )
        pair = plan_assessment(
            build(PROGRAM_3, [CYBER_ID, WEB_ID], module_configs=[], coding=2)
        )
        assert single.mcq_total == 20
        assert pair.mcq_total == 20
        assert [e.mcq_count for e in pair.domains] == [10, 10]
        assert single.descriptive_total == pair.descriptive_total == 0
        assert single.hands_on_total == pair.hands_on_total == 0
        assert single.coding_total == pair.coding_total == 2

    def test_sem3_odd_master_mcq_total_is_rejected(self):
        """The master technical MCQ total must be even (0-20, even)."""
        odd_program = _program_with_mcq_total(PROGRAM_3, 5)
        err = expect_failure(
            PlanningErrorKind.INVALID_PROGRAM,
            program=odd_program,
            domain_ids=[CYBER_ID],
            module_configs=[],
            coding=2,
        )
        assert "even" in err.detail

    def test_sem3_misconfigured_junior_hands_on_row_cannot_leak_challenges(self):
        """THE Sem-3 hands-on guard: a junior row enabling hands-on is inert.

        Hands-on is a SENIOR-only module. Even if a junior assessment_module_config
        row is mis-authored with hands_on_enabled=True and a nonzero count (and
        challenges exist in the pool), a junior candidate's plan must contain
        zero hands-on content and zero additional hands-on time.
        """
        bad_junior = cfg(
            CYBER_ID, "junior", mcq=5, desc=1,
            hands_on=True, hands_on_count=2, minutes=30,
        )
        req = build(PROGRAM_3, [CYBER_ID], [bad_junior], coding=2)
        req.hands_on_pool = hands_items(["h1", "h2"], [CYBER_ID])
        plan = plan_assessment(req)
        assert plan.hands_on_total == 0
        assert plan.selected_hands_on_question_ids == []
        assert plan.practicals == []
        assert plan.additional_minutes == 0
        assert plan.duration_minutes == 90  # base only — no hands-on time
        assert plan.domains[0].hands_on_enabled is False
        assert plan.descriptive_total == 0
        assert plan.coding_total == 2

    # ---- Sem 5 / senior technical ------------------------------------------

    def test_sem5_senior_no_descriptive_and_hands_on_follows_config(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)
        )
        assert plan.descriptive_total == 0
        assert plan.selected_descriptive_question_ids == []
        assert plan.hands_on_total == 1  # senior module row enables it
        assert plan.additional_minutes == 20
        assert plan.coding_total == 2

    def test_sem5_senior_without_hands_on_config_gets_none(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID], module_configs=[], coding=2)
        )
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 0
        assert plan.practicals == []
        assert plan.mcq_total == 20
        assert plan.coding_total == 2

    # ---- Sem 1 / organizational --------------------------------------------

    def test_sem1_descriptive_follows_organizational_configuration(self):
        plan = plan_assessment(
            build(
                PROGRAM_1,
                [ORG_ID],
                [cfg(ORG_ID, "organizational", mcq=10, desc=3)],
            )
        )
        assert plan.descriptive_total == 3
        assert plan.mcq_total == 10
        assert plan.hands_on_total == 0
        assert plan.coding_total == 0

    def test_sem1_descriptive_configurable_to_zero(self):
        plan = plan_assessment(
            build(
                PROGRAM_1,
                [ORG_ID],
                [cfg(ORG_ID, "organizational", mcq=10, desc=0)],
            )
        )
        assert plan.descriptive_total == 0
        assert plan.mcq_total == 10


# ---------------------------------------------------------------------------
# Optional network-integrity policy in the frozen plan
# ---------------------------------------------------------------------------


class TestNetworkIntegrityPolicyInPlan:
    """The optional proctoring policy is frozen INTO the plan.

    The policy has to travel with the attempt rather than being read live, so
    that an admin flipping the global toggle can never change the behaviour of
    an assessment that is already running. It must also be inert with respect to
    the plan's CONTENT: no selection, count or duration may move.
    """

    def _plans(self, **kwargs):
        return (
            plan_assessment(build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR], coding=2)),
            plan_assessment(
                build(
                    PROGRAM_5,
                    [CYBER_ID],
                    [CYBER_SENIOR],
                    coding=2,
                    **kwargs,
                )
            ),
        )

    def test_monitoring_is_disabled_by_default(self):
        assert self._plans()[0].network_integrity_monitoring is False

    def test_monitoring_travels_into_the_plan_when_requested(self):
        assert self._plans(network_integrity_monitoring=True)[1].network_integrity_monitoring is True

    def test_policy_changes_no_selection_count_or_duration(self):
        off, on = self._plans(network_integrity_monitoring=True)

        assert off.selected_mcq_ids == on.selected_mcq_ids
        assert off.selected_coding_problem_ids == on.selected_coding_problem_ids
        assert off.selected_descriptive_question_ids == on.selected_descriptive_question_ids
        assert off.selected_hands_on_question_ids == on.selected_hands_on_question_ids
        assert off.mcq_total == on.mcq_total
        assert off.coding_total == on.coding_total
        assert off.descriptive_total == on.descriptive_total
        assert off.hands_on_total == on.hands_on_total
        assert off.duration_minutes == on.duration_minutes

    def test_policy_does_not_move_the_config_fingerprint(self):
        """Monitoring is a proctoring policy, not assessment configuration."""
        off, on = self._plans(network_integrity_monitoring=True)

        assert off.config_fingerprint == on.config_fingerprint

    def test_policy_survives_serialisation_for_the_plan_snapshot(self):
        plan = self._plans(network_integrity_monitoring=True)[1]

        restored = assessment_planner.AssessmentPlan.model_validate(
            plan.model_dump(mode="json")
        )

        assert restored.network_integrity_monitoring is True
        assert restored.config_fingerprint == plan.config_fingerprint

    def test_a_plan_snapshot_without_the_key_reads_as_disabled(self):
        """Attempts created before this feature carry no key at all."""
        payload = self._plans()[0].model_dump(mode="json")
        payload.pop("network_integrity_monitoring")

        restored = assessment_planner.AssessmentPlan.model_validate(payload)

        assert restored.network_integrity_monitoring is False
