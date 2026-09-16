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
    LegacyTechnicalFallback,
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
PROGRAM_3 = ProgramInput(
    semester=3,
    scope=Scope.TECHNICAL,
    tier="junior",
    max_domains=2,
    coding_enabled=True,
)
PROGRAM_5 = ProgramInput(
    semester=5,
    scope=Scope.TECHNICAL,
    tier="senior",
    max_domains=2,
    coding_enabled=True,
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


def hands_items(ids, domain_ids, active=True):
    return [
        HandsOnPoolItem(id=i, domain_ids=list(domain_ids), is_active=active)
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
        assert plan.plan_version == 1
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
        assert plan.mcq_total == 5
        assert plan.descriptive_total == 1
        assert plan.hands_on_total == 0
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
        assert plan.mcq_total == 5
        assert plan.descriptive_total == 2
        assert plan.hands_on_total == 1
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
        """Semester 1 allows exactly one domain — enforced explicitly."""
        err = expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=PROGRAM_1,
            domain_ids=[ORG_ID, ORG_ID + "-x"],
        )
        assert "exactly one" in err.detail

    def test_organizational_one_domain_allowed_even_if_max_domains_wrong(self):
        """The one-domain rule holds even if a program row says max_domains=2."""
        misconfigured = ProgramInput(
            semester=1,
            scope=Scope.ORGANIZATIONAL,
            tier=None,
            max_domains=2,
            coding_enabled=False,
        )
        err = expect_failure(
            PlanningErrorKind.INVALID_DOMAIN_SELECTION,
            program=misconfigured,
            domain_ids=[ORG_ID, ORG_ID + "-x"],
        )
        assert "exactly one" in err.detail

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

    def test_technical_assessment_rejects_organizational_domain(self):
        err = expect_failure(
            PlanningErrorKind.WRONG_DOMAIN_SCOPE,
            program=PROGRAM_5,
            domain_ids=[ORG_ID],
            module_configs=[ORG_COMMON],
        )
        assert "organizational" in err.detail

    def test_organizational_assessment_rejects_technical_domain(self):
        err = expect_failure(
            PlanningErrorKind.WRONG_DOMAIN_SCOPE,
            program=PROGRAM_1,
            domain_ids=[CYBER_ID],
            module_configs=[CYBER_SENIOR],
        )
        assert "technical" in err.detail


# ---------------------------------------------------------------------------
# 9-10, 29. Module configuration + the legacy fallback boundary
# ---------------------------------------------------------------------------


class TestModuleConfiguration:
    def test_missing_module_config_fails_in_modular_mode(self):
        err = expect_failure(
            PlanningErrorKind.MISSING_MODULE_CONFIG,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID],
        )
        assert "no technical legacy fallback was supplied" in err.detail

    def test_missing_organizational_config_fails(self):
        err = expect_failure(
            PlanningErrorKind.MISSING_MODULE_CONFIG,
            program=PROGRAM_1,
            domain_ids=[ORG_ID],
        )
        assert "no legacy fallback" in err.detail

    def test_organizational_missing_config_never_falls_back_to_legacy(self):
        """The critical boundary: organizational has NO legacy fallback.

        The fallback is supplied and the pools would satisfy it — the planner
        must still refuse rather than silently inherit global counts (which
        would wrongly grant hands-on and coding time).
        """
        err = expect_failure(
            PlanningErrorKind.MISSING_MODULE_CONFIG,
            program=PROGRAM_1,
            domain_ids=[ORG_ID],
            legacy_technical_fallback=LegacyTechnicalFallback(
                total_questions=10,
                descriptive_question_count=2,
                hands_on_question_count=1,
            ),
        )
        assert "organizational assessment has no legacy fallback" in err.detail

    def test_partial_technical_config_does_not_mix_with_legacy(self):
        """All-or-nothing: one missing row must not produce a hybrid plan."""
        erg = expect_failure(
            PlanningErrorKind.MISSING_MODULE_CONFIG,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID, WEB_ID],
            module_configs=[CYBER_SENIOR],  # WEB_SENIOR deliberately absent
        )
        assert "Web Development" in erg.detail

    def test_technical_legacy_fallback_is_explicit_and_works(self):
        """Legacy technical behaviour is representable via explicit opt-in."""
        fallback = LegacyTechnicalFallback(
            total_questions=10,
            descriptive_question_count=2,
            hands_on_question_count=1,
        )
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                coding=2,
                legacy_technical_fallback=fallback,
            )
        )
        assert plan.config_source is ConfigSource.LEGACY_TECHNICAL_FALLBACK
        # 10 global MCQs split 5/5 across the two domains.
        assert plan.mcq_total == 10
        assert [e.mcq_count for e in plan.domains] == [5, 5]
        # Global descriptive/hands-on counts applied once, not per domain.
        assert plan.descriptive_total == 2
        assert plan.hands_on_total == 1
        # Legacy has no additional-time concept.
        assert plan.additional_minutes == 0
        assert plan.duration_minutes == 90

    def test_legacy_odd_total_rejected_for_two_domains(self):
        fallback = LegacyTechnicalFallback(total_questions=9)
        expect_failure(
            PlanningErrorKind.INVALID_MODULE_CONFIG,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID, WEB_ID],
            legacy_technical_fallback=fallback,
        )

    def test_legacy_odd_total_allowed_for_one_domain(self):
        fallback = LegacyTechnicalFallback(total_questions=9)
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID],
                legacy_technical_fallback=fallback,
            )
        )
        assert plan.mcq_total == 9

    def test_legacy_fallback_ignored_when_modular_config_complete(self):
        """Complete modular config wins; the fallback is not consulted."""
        plan = plan_assessment(
            build(
                PROGRAM_5,
                [CYBER_ID],
                [CYBER_SENIOR],
                legacy_technical_fallback=LegacyTechnicalFallback(total_questions=99),
            )
        )
        assert plan.config_source is ConfigSource.MODULAR
        assert plan.mcq_total == 5

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

    def test_config_for_wrong_tier_is_not_used(self):
        """A junior row cannot satisfy a senior program."""
        expect_failure(
            PlanningErrorKind.MISSING_MODULE_CONFIG,
            program=PROGRAM_5,
            domain_ids=[CYBER_ID],
            module_configs=[CYBER_JUNIOR],
        )


# ---------------------------------------------------------------------------
# 11-13. MCQ
# ---------------------------------------------------------------------------


class TestMCQSelection:
    def test_per_domain_mcq_counts(self):
        plan = plan_assessment(
            build(PROGRAM_3, [CYBER_ID, WEB_ID], [CYBER_JUNIOR, WEB_JUNIOR])
        )
        assert [e.mcq_count for e in plan.domains] == [5, 4]
        assert plan.mcq_total == 9

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
        req.mcq_pool = mcq_items(CYBER_ID, 5, 4, "q")  # needs 5
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_MCQ_POOL
        assert "only 4 active MCQ questions, need 5" in excinfo.value.detail

    def test_mcq_does_not_top_up_from_another_domain(self):
        """Web has plenty; Cyber is short. The plan must still fail."""
        req = build(PROGRAM_3, [CYBER_ID, WEB_ID], [CYBER_JUNIOR, WEB_JUNIOR])
        req.mcq_pool = mcq_items(CYBER_ID, 3, 1, "cyber") + mcq_items(
            WEB_ID, 3, 40, "web"
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_MCQ_POOL

    def test_inactive_mcq_questions_are_excluded(self):
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        req.mcq_pool = [
            MCQPoolItem(id=f"q{i}", domain_id=CYBER_ID, semester=5, is_active=i < 3)
            for i in range(10)
        ]
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_MCQ_POOL
        assert "only 3 active" in excinfo.value.detail


# ---------------------------------------------------------------------------
# 14-16. Descriptive
# ---------------------------------------------------------------------------


class TestDescriptiveSelection:
    def test_per_domain_descriptive_counts(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR])
        )
        assert [e.descriptive_count for e in plan.domains] == [2, 1]
        assert plan.descriptive_total == 3

    def test_descriptive_cross_domain_deduplication(self):
        """Domain A needs 2, Domain B needs 2, with overlapping candidates."""
        shared = desc_items(["s1", "s2"], [CYBER_ID, WEB_ID])
        cyber_only = desc_items(["c1", "c2"], [CYBER_ID])
        web_only = desc_items(["w1", "w2"], [WEB_ID])
        both_two = [
            cfg(CYBER_ID, "senior", desc=2),
            cfg(WEB_ID, "senior", desc=2),
        ]
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            both_two,
            descriptive_pool=shared + cyber_only + web_only,
        )
        plan = plan_assessment(req)

        # 6 unique questions are available for a 4 question quota, so the
        # quota is met with exactly 4 DISTINCT questions.
        assert plan.descriptive_total == 4
        assert len(set(plan.selected_descriptive_question_ids)) == 4
        assert [e.descriptive_count for e in plan.domains] == [2, 2]
        # Cyber Security sorts first, so it takes its own exclusive questions
        # and the shared ones fall to Web.
        assert plan.selected_descriptive_question_ids == ["c1", "c2", "s1", "s2"]

    def test_descriptive_dedup_when_both_domains_want_the_same_shared_pool(self):
        """Two domains each needing 2 from a pool they entirely share."""
        shared = desc_items(["s1", "s2", "s3", "s4"], [CYBER_ID, WEB_ID])
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [cfg(CYBER_ID, "senior", desc=2), cfg(WEB_ID, "senior", desc=2)],
            descriptive_pool=shared,
        )
        plan = plan_assessment(req)
        assert plan.descriptive_total == 4
        assert sorted(plan.selected_descriptive_question_ids) == [
            "s1",
            "s2",
            "s3",
            "s4",
        ]

    def test_descriptive_overlap_quota_shortfall_fails(self):
        """2 + 2 quota but only 3 unique overlapping questions exist."""
        shared = desc_items(["s1", "s2", "s3"], [CYBER_ID, WEB_ID])
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [cfg(CYBER_ID, "senior", desc=2), cfg(WEB_ID, "senior", desc=2)],
            descriptive_pool=shared,
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL
        assert "cross-domain deduplication" in excinfo.value.detail

    def test_descriptive_does_not_reduce_the_requested_count(self):
        req = build(
            PROGRAM_5,
            [CYBER_ID],
            [CYBER_SENIOR],
            descriptive_pool=desc_items(["d1"], [CYBER_ID]),  # needs 2
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL

    def test_shared_question_is_reallocated_so_both_domains_are_satisfied(self):
        """The case a greedy pass in domain order used to get WRONG.

        Web's only eligible question is the one shared with Cyber, and it sorts
        before Cyber's exclusive question. Taking the lowest-sorted id per
        domain therefore starves Web unless the allocator can move Cyber onto
        its exclusive question instead. The plan must succeed.
        """
        pool = desc_items(["a-shared"], [CYBER_ID, WEB_ID]) + desc_items(
            ["b-cyber-only"], [CYBER_ID]
        )
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [cfg(CYBER_ID, "senior", desc=1), cfg(WEB_ID, "senior", desc=1)],
            descriptive_pool=pool,
        )
        plan = plan_assessment(req)

        assert plan.descriptive_total == 2
        assert sorted(plan.selected_descriptive_question_ids) == [
            "a-shared",
            "b-cyber-only",
        ]
        assert [e.descriptive_count for e in plan.domains] == [1, 1]

    def test_inactive_descriptive_questions_excluded(self):
        req = build(
            PROGRAM_5,
            [CYBER_ID],
            [CYBER_SENIOR],
            descriptive_pool=desc_items(
                ["d1", "d2", "d3", "d4"], [CYBER_ID], active=False
            ),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL


# ---------------------------------------------------------------------------
# 17-20. Hands-on
# ---------------------------------------------------------------------------


class TestHandsOnSelection:
    def test_per_domain_hands_on_counts(self):
        cyber = cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=1, minutes=20)
        web = cfg(WEB_ID, "senior", hands_on=True, hands_on_count=1, minutes=10)
        plan = plan_assessment(build(PROGRAM_5, [CYBER_ID, WEB_ID], [cyber, web]))
        assert plan.hands_on_total == 2
        assert len(set(plan.selected_hands_on_question_ids)) == 2
        assert [(e.hands_on_enabled, e.hands_on_count) for e in plan.domains] == [
            (True, 1),
            (True, 1),
        ]

    def test_hands_on_cross_domain_deduplication(self):
        """Two domains each needing 2, pool entirely shared: 4 unique."""
        shared = hands_items(["h1", "h2", "h3", "h4"], [CYBER_ID, WEB_ID])
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=2),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=2),
            ],
            hands_on_pool=shared,
        )
        plan = plan_assessment(req)
        assert plan.hands_on_total == 4
        assert sorted(plan.selected_hands_on_question_ids) == [
            "h1",
            "h2",
            "h3",
            "h4",
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
            "mcq_count": build(
                PROGRAM_5,
                [CYBER_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        mcq=6,
                        desc=2,
                        hands_on=True,
                        hands_on_count=1,
                        minutes=20,
                    )
                ],
                base=90,
            ),
            "descriptive_count": build(
                PROGRAM_5,
                [CYBER_ID],
                [
                    cfg(
                        CYBER_ID,
                        "senior",
                        mcq=5,
                        desc=3,
                        hands_on=True,
                        hands_on_count=1,
                        minutes=20,
                    )
                ],
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
        req.mcq_pool = [
            MCQPoolItem(
                id=f"q{i}",
                domain_id=CYBER_ID,
                semester=5,
                correct_option="A",
                explanation="because",  # type: ignore
            )
            for i in range(10)
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
        assert round_tripped["plan_version"] == 1
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
        assert plan.mcq_total == 10
        assert plan.descriptive_total == 3
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
                [CYBER_JUNIOR, WEB_JUNIOR],
                coding=2,
                base=90,
            )
        )
        assert plan.mcq_total == 9
        assert plan.descriptive_total == 2
        assert plan.hands_on_total == 0
        assert plan.selected_hands_on_question_ids == []
        assert plan.additional_minutes == 0
        assert plan.duration_minutes == 90

    def test_per_domain_mcq_counts_sum_to_total(self):
        plan = plan_assessment(
            build(PROGRAM_5, [CYBER_ID, WEB_ID], [CYBER_SENIOR, WEB_SENIOR])
        )
        assert sum(e.mcq_count for e in plan.domains) == plan.mcq_total

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
        """Both domains want 2; Web can only use the two shared questions.

        The shared ids sort before Cyber's exclusives, so a greedy pass would
        hand both shared questions to Cyber and then fail Web. Feasibility
        requires Cyber to end up on its two exclusive questions instead.
        """
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [cfg(CYBER_ID, "senior", desc=2), cfg(WEB_ID, "senior", desc=2)],
            descriptive_pool=(
                desc_items(["a1", "a2"], [CYBER_ID, WEB_ID])
                + desc_items(["z1", "z2"], [CYBER_ID])
            ),
        )
        plan = plan_assessment(req)
        assert plan.descriptive_total == 4
        assert sorted(plan.selected_descriptive_question_ids) == [
            "a1",
            "a2",
            "z1",
            "z2",
        ]
        assert [e.descriptive_count for e in plan.domains] == [2, 2]

    def test_hands_on_shared_challenge_is_reallocated(self):
        """The hands-on equivalent of the descriptive reallocation case."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [
                cfg(CYBER_ID, "senior", hands_on=True, hands_on_count=1),
                cfg(WEB_ID, "senior", hands_on=True, hands_on_count=1),
            ],
            hands_on_pool=(
                hands_items(["a-shared"], [CYBER_ID, WEB_ID])
                + hands_items(["b-cyber-only"], [CYBER_ID])
            ),
        )
        plan = plan_assessment(req)
        assert plan.hands_on_total == 2
        assert sorted(plan.selected_hands_on_question_ids) == [
            "a-shared",
            "b-cyber-only",
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
        """A 2 + 2 quota over only 3 unique questions is genuinely infeasible."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [cfg(CYBER_ID, "senior", desc=2), cfg(WEB_ID, "senior", desc=2)],
            descriptive_pool=desc_items(["s1", "s2", "s3"], [CYBER_ID, WEB_ID]),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL
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
            [cfg(CYBER_ID, "senior", desc=1), cfg(WEB_ID, "senior", desc=5)],
            descriptive_pool=desc_items(["s1", "s2"], [CYBER_ID, WEB_ID]),
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL

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
        # Quotas are met exactly, never reduced.
        assert plan.descriptive_total == 4
        assert plan.hands_on_total == 4
        assert [e.descriptive_count for e in plan.domains] == [2, 2]
        assert [e.hands_on_count for e in plan.domains] == [2, 2]

    def test_allocation_is_deterministic_across_repeated_calls(self):
        request = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [cfg(CYBER_ID, "senior", desc=2), cfg(WEB_ID, "senior", desc=2)],
            descriptive_pool=(
                desc_items(["a1", "a2"], [CYBER_ID, WEB_ID])
                + desc_items(["z1", "z2"], [CYBER_ID])
            ),
        )
        dumps = [plan_assessment(request).model_dump() for _ in range(5)]
        assert all(dump == dumps[0] for dump in dumps)

    def test_allocation_is_deterministic_under_a_seed(self):
        def run():
            request = build(
                PROGRAM_5,
                [CYBER_ID, WEB_ID],
                [cfg(CYBER_ID, "senior", desc=2), cfg(WEB_ID, "senior", desc=2)],
                descriptive_pool=desc_items(
                    ["q1", "q2", "q3", "q4", "q5"], [CYBER_ID, WEB_ID]
                ),
            )
            request.seed = 7
            return plan_assessment(request).model_dump()

        assert run() == run()

    def test_allocation_still_meets_quotas_with_a_seed(self):
        request = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [cfg(CYBER_ID, "senior", desc=2), cfg(WEB_ID, "senior", desc=2)],
            descriptive_pool=desc_items(
                ["q1", "q2", "q3", "q4", "q5", "q6"], [CYBER_ID, WEB_ID]
            ),
        )
        request.seed = 99
        plan = plan_assessment(request)
        assert plan.descriptive_total == 4
        assert len(set(plan.selected_descriptive_question_ids)) == 4
        assert [e.descriptive_count for e in plan.domains] == [2, 2]

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
        dupes = desc_items(["d1", "d1"], [CYBER_ID]) + desc_items(["d2"], [CYBER_ID])
        req = build(
            PROGRAM_5,
            [CYBER_ID],
            [cfg(CYBER_ID, "senior", desc=3)],
            descriptive_pool=dupes,
        )
        with pytest.raises(AssessmentPlanningError) as excinfo:
            plan_assessment(req)
        # Only 2 unique questions exist, so a 3 question quota must fail
        # rather than double-counting d1.
        assert excinfo.value.kind is PlanningErrorKind.INSUFFICIENT_DESCRIPTIVE_POOL

    def test_duplicate_mcq_rows_are_counted_once(self):
        req = build(PROGRAM_5, [CYBER_ID], [CYBER_SENIOR])
        req.mcq_pool = mcq_items(CYBER_ID, 5, 5, "q") + mcq_items(CYBER_ID, 5, 5, "q")
        plan = plan_assessment(req)
        assert plan.mcq_total == 5
        assert len(set(plan.selected_mcq_ids)) == 5

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
            [CYBER_SENIOR, WEB_SENIOR],
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
            [CYBER_SENIOR, WEB_SENIOR],
        )
        req_a.seed = 1
        req_b = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [CYBER_SENIOR, WEB_SENIOR],
        )
        req_b.seed = 2
        a = plan_assessment(req_a)
        b = plan_assessment(req_b)
        # Both have 10 MCQs (5 per domain), so a different seed should
        # produce a different final order.
        assert a.mcq_total == 10
        assert b.mcq_total == 10
        assert a.selected_mcq_ids != b.selected_mcq_ids

    def test_mcq_ids_are_not_grouped_by_domain(self):
        """With a seed, MCQs from different domains must be interleaved

        rather than appearing as domain-1-then-domain-2 blocks.
        With a pool of 25 per domain and 5 MCQs per domain, a seeded
        request should produce interleaving in at least some runs.
        """
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [CYBER_SENIOR, WEB_SENIOR],
        )
        req.seed = 7
        plan = plan_assessment(req)
        ids = plan.selected_mcq_ids
        # All IDs should be from the MCQ pool (domain-prefixed)
        assert len(ids) == 10
        assert len(set(ids)) == 10
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

    def test_no_seed_keeps_sorted_mcq_order(self):
        """Without a seed, MCQs remain in the deterministic sorted order."""
        req = build(
            PROGRAM_5,
            [CYBER_ID, WEB_ID],
            [CYBER_SENIOR, WEB_SENIOR],
        )
        # seed=None (default)
        plan = plan_assessment(req)
        assert plan.selected_mcq_ids == sorted(plan.selected_mcq_ids)

    def test_shuffled_mcq_ids_still_all_belong_to_selected_domains(self):
        """Shuffling must not inject or drop IDs."""
        req = build(
            PROGRAM_5,
            [CYBER_ID],
            [CYBER_SENIOR],
        )
        req.seed = 99
        plan = plan_assessment(req)
        # Every MCQ must belong to Cyber Security (the only selected domain)
        for qid in plan.selected_mcq_ids:
            assert CYBER_ID in qid or qid.startswith("q" + CYBER_ID)
        assert len(plan.selected_mcq_ids) == 5
        assert len(set(plan.selected_mcq_ids)) == 5
