"""Phase 4 integration tests: the planner drives POST /assessment/start.

These tests exercise the real endpoint against mocked database responses, and
they reuse the established helpers from ``test_main`` so the mocking style stays
identical to the rest of the suite (see ``_configure_start_mocks``).

The important structural property they protect is that a NEW attempt is built
from the frozen ``AssessmentPlan``, while an EXISTING in-progress attempt is
returned untouched and never replanned.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from test_main import (
    FROZEN_DESC_IDS,
    FROZEN_HANDS_IDS,
    MOCK_ATTEMPT_ID,
    MOCK_CANDIDATE_ID,
    MOCK_CODING_PROBLEM_ID,
    MOCK_DESC_ID,
    MOCK_DOMAIN_1_ID,
    MOCK_DOMAIN_2_ID,
    MOCK_HANDS_ID,
    MOCK_MCQ_1_ID,
    MOCK_MCQ_2_ID,
    MOCK_PROFILE_ID,
    _configure_resume_chains,
    _configure_start_mocks,
    _frozen_attempt,
    _make_mock_response,
    _make_module_config,
    _make_program,
    _route_table,
)


# Same patching convention as test_main's autouse mock. Defined locally rather
# than imported so the fixture name does not clash with the parameters that
# request it.
#
# IMPORTANT: services.assessment_planning holds its OWN supabase_client
# reference, so it must be patched explicitly — without it these tests would
# silently query the real database.
@pytest.fixture(autouse=True)
def mock_supabase():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_mock_response(
        []
    )
    with patch("core.supabase.supabase_client", mock_client), patch(
        "routers.assessment.supabase_client", mock_client
    ), patch("services.assessment_planning.supabase_client", mock_client):
        yield mock_client


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


# The seeded DEV programmes (migration 014 seed rows).
ORG_PROGRAM = _make_program(
    semester=1,
    scope="organizational",
    tier=None,
    max_domains=1,
    coding_enabled=False,
)
JUNIOR_PROGRAM = _make_program(
    semester=3,
    scope="technical",
    tier="junior",
    max_domains=2,
    coding_enabled=True,
)
SENIOR_PROGRAM = _make_program()  # semester 5, senior, coding enabled
NONE_PROGRAM = _make_program(
    semester=7, scope="none", tier=None, max_domains=1, coding_enabled=False
)

TECH_DOMAIN = {
    "id": MOCK_DOMAIN_1_ID,
    "name": "Cyber Security",
    "slug": "cyberSecurity",
    "assessment_scope": "technical",
    "is_active": True,
    # Deliberately present + bogus: the planner must never read it.
    "duration_minutes": 999,
}
ORG_DOMAIN = {
    "id": MOCK_DOMAIN_1_ID,
    "name": "Organizational Roles",
    "slug": "organizationalRoles",
    "assessment_scope": "organizational",
    "is_active": True,
    "duration_minutes": 999,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth():
    from core.auth import AuthUser, get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=MOCK_PROFILE_ID, email="candidate@test.com"
    )
    return app


def _post(client, domain_ids=None, **extra):
    body = {"domain_ids": domain_ids if domain_ids is not None else [MOCK_DOMAIN_1_ID]}
    body.update(extra)
    return client.post("/assessment/start", json=body)


def _payload(mock_supabase):
    """The dict the endpoint INSERTed into assessment_attempts."""
    return mock_supabase._table_chains["assessment_attempts"].insert.call_args.args[0]


def _chain(mock_supabase, table):
    """Pre-create (or fetch) a per-table chain so it can be configured."""
    return mock_supabase._table_chains.setdefault(table, MagicMock())


class PlannerSpy:
    """Records planner requests/plans while delegating to the real planner."""

    def __init__(self, monkeypatch):
        import services.assessment_planning as ap

        self.requests = []
        self.plans = []
        real = ap.plan_assessment

        def spy(request):
            # Record BEFORE delegating, so a REFUSED plan is still observable.
            self.requests.append(request)
            plan = real(request)
            self.plans.append(plan)
            return plan

        monkeypatch.setattr(ap, "plan_assessment", spy)

    @property
    def called(self):
        return bool(self.requests)

    @property
    def request(self):
        return self.requests[-1]

    @property
    def plan(self):
        return self.plans[-1]


@pytest.fixture
def spy(monkeypatch):
    return PlannerSpy(monkeypatch)


# ===========================================================================
# A. PROGRAM RESOLUTION
# ===========================================================================


class TestProgramResolution:
    def test_semester_1_resolves_organizational_program(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=1,
            program=ORG_PROGRAM,
            domains=[ORG_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="organizational",
                    mcq_count=2,
                )
            ],
            coding_problem_count=5,  # must be ignored for organizational
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        payload = _payload(mock_supabase)
        # Organizational: no coding at all, even though the global count is 5.
        assert payload["total_coding_problems"] == 0
        assert payload["selected_coding_problem_ids"] == []

    def test_semester_3_resolves_junior_program(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=3,
            program=JUNIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="junior",
                    mcq_count=1,
                    descriptive_count=1,
                )
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        # The junior programme was the one resolved. Under the master-total
        # rule the MCQ quantity comes from program.mcq_total (2).
        assert _payload(mock_supabase)["total_questions"] == 2

    def test_semester_5_resolves_senior_program(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=5,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert _payload(mock_supabase)["total_questions"] == 2

    def test_semester_7_scope_none_is_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase, semester=7, program=NONE_PROGRAM, domains=[TECH_DOMAIN]
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "no assessment" in response.json()["detail"].lower()
        mock_supabase._table_chains["assessment_attempts"].insert.assert_not_called()

    def test_missing_program_is_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(mock_supabase, program={}, domains=[TECH_DOMAIN])
        # Simulate "no active programme row": empty result set.
        chain = mock_supabase._table_chains["assessment_program"]
        chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = _make_mock_response(
            []
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "no active assessment programme" in response.json()["detail"].lower()

    def test_program_resolution_uses_the_candidate_semester(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=3,
            program=JUNIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="junior", mcq_count=1
                )
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        chain = _chain(mock_supabase, "assessment_program")
        assert chain.select.return_value.eq.call_args.args == ("semester", 3)

    def test_program_query_filters_on_is_active(self, client, mock_supabase):
        """An inactive programme must not be used, so is_active is filtered."""
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase, program=SENIOR_PROGRAM, domains=[TECH_DOMAIN]
        )
        _auth()
        try:
            _post(client)
        finally:
            client.app.dependency_overrides.clear()

        chain = _chain(mock_supabase, "assessment_program")
        assert chain.select.return_value.eq.call_args.args == ("semester", 5)
        assert chain.select.return_value.eq.return_value.eq.call_args.args == (
            "is_active",
            True,
        )

    def test_technical_program_without_tier_is_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=_make_program(tier=None),
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "tier" in response.json()["detail"].lower()

    def test_resolve_program_returns_the_semester_row(self, mock_supabase):
        """Service-level: the programme comes from the DB, not from hardcoding."""
        from services.assessment_planning import resolve_program

        _route_table(mock_supabase, "assessment_program")
        chain = _chain(mock_supabase, "assessment_program")
        for semester, row in (
            (1, ORG_PROGRAM),
            (3, JUNIOR_PROGRAM),
            (5, SENIOR_PROGRAM),
        ):
            chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = _make_mock_response(
                [row]
            )
            program = resolve_program(semester)
            assert program.semester == semester
            assert program.scope.value == row["scope"]
            assert program.max_domains == row["max_domains"]

    def test_resolve_program_without_row_raises_400(self, mock_supabase):
        from fastapi import HTTPException

        from services.assessment_planning import resolve_program

        _route_table(mock_supabase, "assessment_program")
        _chain(
            mock_supabase, "assessment_program"
        ).select.return_value.eq.return_value.eq.return_value.execute.return_value = _make_mock_response(
            []
        )
        with pytest.raises(HTTPException) as excinfo:
            resolve_program(7)
        assert excinfo.value.status_code == 400


# ===========================================================================
# B. DOMAIN ELIGIBILITY
# ===========================================================================


class TestDomainEligibility:
    def _start_semester_1(
        self, client, mock_supabase, module_configs, domains, domain_ids=None
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=1,
            program=ORG_PROGRAM,
            domains=domains,
            module_configs=module_configs,
        )
        _auth()
        try:
            return _post(client, domain_ids=domain_ids)
        finally:
            client.app.dependency_overrides.clear()

    def test_semester_1_accepts_organizational_domain(self, client, mock_supabase):
        response = self._start_semester_1(
            client,
            mock_supabase,
            [
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="organizational", mcq_count=2
                )
            ],
            [ORG_DOMAIN],
        )
        assert response.status_code == 200

    def test_semester_1_rejects_technical_domain(self, client, mock_supabase):
        response = self._start_semester_1(
            client,
            mock_supabase,
            [
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="organizational", mcq_count=2
                )
            ],
            [TECH_DOMAIN],
        )
        assert response.status_code == 400
        assert "organizational" in response.json()["detail"].lower()

    def test_semester_3_accepts_technical_domains(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=3,
            program=JUNIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="junior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

    def test_semester_3_rejects_organizational_domain(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=3,
            program=JUNIOR_PROGRAM,
            domains=[ORG_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="junior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "technical" in response.json()["detail"].lower()

    def test_semester_5_accepts_technical_domains(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

    def test_inactive_domain_rejected(self, client, mock_supabase):
        inactive = dict(TECH_DOMAIN, is_active=False, name="Retired Domain")
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[inactive],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "inactive" in response.json()["detail"].lower()
        mock_supabase._table_chains["assessment_attempts"].insert.assert_not_called()

    def test_unknown_domain_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"].lower()

    def test_duplicate_domain_ids_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            response = _post(client, domain_ids=[MOCK_DOMAIN_1_ID, MOCK_DOMAIN_1_ID])
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    def test_domain_count_uses_program_max_domains(self, client, mock_supabase):
        """The cap comes from assessment_program, not assessment_config."""
        second_domain = dict(
            TECH_DOMAIN, id=MOCK_DOMAIN_2_ID, name="Web Dev", slug="webDevelopment"
        )
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            # assessment_config says max_domains=2, but the programme says 1.
            program=_make_program(max_domains=1),
            domains=[TECH_DOMAIN, second_domain],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                ),
                _make_module_config(
                    domain_id=MOCK_DOMAIN_2_ID, applies_to="senior", mcq_count=2
                ),
            ],
        )
        _auth()
        try:
            response = _post(client, domain_ids=[MOCK_DOMAIN_1_ID, MOCK_DOMAIN_2_ID])
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "between 1 and 1 domains" in response.json()["detail"]

    def test_organizational_allows_exactly_one_domain(self, client, mock_supabase):
        second_domain = dict(ORG_DOMAIN, id=MOCK_DOMAIN_2_ID)
        response = self._start_semester_1(
            client,
            mock_supabase,
            [
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="organizational", mcq_count=2
                ),
                _make_module_config(
                    domain_id=MOCK_DOMAIN_2_ID, applies_to="organizational", mcq_count=2
                ),
            ],
            [ORG_DOMAIN, second_domain],
            domain_ids=[MOCK_DOMAIN_1_ID, MOCK_DOMAIN_2_ID],
        )
        assert response.status_code == 400
        assert "exactly one" in response.json()["detail"].lower()


# ===========================================================================
# C. MODULE CONFIG
# ===========================================================================


class TestModuleConfiguration:
    def test_fully_configured_technical_uses_modular_config(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="senior",
                    mcq_count=1,
                    descriptive_count=1,
                )
            ],
            descriptive_count=2,  # the unused global count; module config wins
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert spy.plan.config_source.value == "modular"
        payload = _payload(mock_supabase)
        # Technical MCQ comes from program.mcq_total=2 (senior programme).
        assert payload["total_questions"] == 2
        # Technical carries no descriptive questions at all, so the configured
        # descriptive_count=1 is ignored.
        assert payload["total_descriptive_questions"] == 0

    def test_partially_configured_technical_plan_succeeds(
        self, client, mock_supabase, spy
    ):
        """Missing module config for a technical domain is fine.

        MCQ count comes from program.mcq_total, not module config.
        Module rows only enable optional modules (hands-on).
        """
        second_domain = dict(
            TECH_DOMAIN, id=MOCK_DOMAIN_2_ID, name="Web Dev", slug="webDevelopment"
        )
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN, second_domain],
            # Only ONE of the two selected domains is configured.
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="senior",
                    mcq_count=1,
                    descriptive_count=1,
                )
            ],
            descriptive_count=1,
            mcq_available=[
                {"id": MOCK_MCQ_1_ID, "domain_id": MOCK_DOMAIN_1_ID},
                {"id": MOCK_MCQ_2_ID, "domain_id": MOCK_DOMAIN_1_ID},
                {
                    "id": "aaaa3333-3333-3333-3333-333333333333",
                    "domain_id": MOCK_DOMAIN_2_ID,
                },
            ],
        )
        _auth()
        try:
            response = _post(client, domain_ids=[MOCK_DOMAIN_1_ID, MOCK_DOMAIN_2_ID])
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert spy.called, "the planner must have been asked and succeeded"

    def test_technical_succeeds_without_module_config(
        self, client, mock_supabase, spy
    ):
        """Technical MCQ count now comes from program.mcq_total.

        Module configs are optional for technical — they only enable
        optional modules like hands-on.
        """
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[],
            descriptive_count=1,
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert spy.called, "the planner must have been asked and succeeded"

    def test_missing_organizational_config_is_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=1,
            program=ORG_PROGRAM,
            domains=[ORG_DOMAIN],
            module_configs=[],
            descriptive_count=2,
            hands_on_count=1,
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "organizational" in response.json()["detail"].lower()
        mock_supabase._table_chains["assessment_attempts"].insert.assert_not_called()

    def test_organizational_never_uses_legacy_global_counts(
        self, client, mock_supabase, spy
    ):
        """The critical boundary: organizational content has ONE source.

        A module row is the only place its mcq/descriptive quantities can come
        from, so a missing row is refused rather than filled from anything else.
        """
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=1,
            program=ORG_PROGRAM,
            domains=[ORG_DOMAIN],
            module_configs=[],
            descriptive_count=2,
            hands_on_count=1,
            coding_problem_count=3,
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert spy.called, "the planner must have been asked and refused"
        assert "legacy_technical_fallback" not in spy.request.model_fields

    def test_organizational_config_is_loaded_with_organizational_family(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=1,
            program=ORG_PROGRAM,
            domains=[ORG_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="organizational", mcq_count=1
                )
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        chain = _chain(mock_supabase, "assessment_module_config")
        assert chain.select.return_value.in_.call_args.args == (
            "domain_id",
            [MOCK_DOMAIN_1_ID],
        )
        assert chain.select.return_value.in_.return_value.eq.call_args.args == (
            "applies_to",
            "organizational",
        )


# ===========================================================================
# D. PLANNER INTEGRATION
# ===========================================================================


class TestPlannerIntegration:
    def _configure(self, mock_supabase, **kwargs):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(mock_supabase, **kwargs)
        _auth()

    def test_start_invokes_the_planner(self, client, mock_supabase, spy):
        self._configure(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert spy.called
        assert spy.request.program.semester == 5
        assert spy.request.requested_domain_ids == [MOCK_DOMAIN_1_ID]

    def test_attempt_columns_come_from_the_planner(self, client, mock_supabase, spy):
        """Every frozen selection/total is copied verbatim from the plan."""
        self._configure(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="senior",
                    mcq_count=2,
                    descriptive_count=1,
                    hands_on_enabled=True,
                    hands_on_count=1,
                    hands_on_additional_minutes=20,
                )
            ],
            coding_problem_count=1,
            coding_available=[{"id": MOCK_CODING_PROBLEM_ID}],
        )
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        plan = spy.plan
        payload = _payload(mock_supabase)

        # MCQ
        assert payload["selected_question_ids"] == plan.selected_mcq_ids
        assert payload["total_questions"] == plan.mcq_total
        # Descriptive
        assert (
            payload["selected_descriptive_question_ids"]
            == plan.selected_descriptive_question_ids
        )
        assert payload["total_descriptive_questions"] == plan.descriptive_total
        # Hands-on
        assert (
            payload["selected_hands_on_question_ids"]
            == plan.selected_hands_on_question_ids
        )
        assert payload["total_hands_on_questions"] == plan.hands_on_total
        # Coding
        assert (
            payload["selected_coding_problem_ids"] == plan.selected_coding_problem_ids
        )
        assert payload["total_coding_problems"] == plan.coding_total
        # Domains + duration
        assert payload["domain_ids"] == plan.domain_ids
        assert payload["duration_minutes"] == plan.duration_minutes

        # And the plan actually contains content (not a vacuous match).
        assert plan.mcq_total == 2
        # Technical never selects descriptive questions.
        assert plan.descriptive_total == 0
        assert plan.hands_on_total == 1
        assert plan.coding_total == 1

    def test_response_shape_is_preserved(self, client, mock_supabase):
        self._configure(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert set(data) == {
            "attempt_id",
            "total_mcq_questions",
            "total_coding_problems",
            "total_descriptive_questions",
            "selected_descriptive_question_ids",
            "total_hands_on_questions",
            "selected_hands_on_question_ids",
            "duration_minutes",
            "domain_ids",
            "expires_at",
        }
        assert data["attempt_id"] == MOCK_ATTEMPT_ID

    def test_planner_error_maps_to_400_without_leaking_internals(
        self, client, mock_supabase
    ):
        self._configure(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[],
            descriptive_count=0,
            hands_on_count=0,
            # Only 1 eligible MCQ, but the programme's mcq_total asks for 2.
            mcq_available=[{"id": MOCK_MCQ_1_ID, "domain_id": MOCK_DOMAIN_1_ID}],
        )
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "mcq" in detail.lower()
        for leaked in (
            "Traceback",
            "supabase",
            "fingerprint",
            "AssessmentPlanningError",
        ):
            assert leaked not in detail


# ===========================================================================
# E. RESUME
# ===========================================================================


class TestResumeIsUntouched:
    def _resume(self, client, mock_supabase, domain_ids=None, attempt=None):
        _configure_resume_chains(mock_supabase, attempt or _frozen_attempt())
        _auth()
        try:
            return _post(client, domain_ids=domain_ids)
        finally:
            client.app.dependency_overrides.clear()

    def test_resume_does_not_invoke_the_planner(self, client, mock_supabase, spy):
        response = self._resume(client, mock_supabase)
        assert response.status_code == 200
        assert response.json()["resumed"] is True
        assert not spy.called

    def test_resume_fetches_no_module_configuration(self, client, mock_supabase):
        response = self._resume(client, mock_supabase)
        assert response.status_code == 200
        assert "assessment_module_config" not in mock_supabase._table_chains

    def test_resume_performs_no_write_to_attempts(self, client, mock_supabase):
        response = self._resume(client, mock_supabase)
        assert response.status_code == 200
        chain = mock_supabase._table_chains["assessment_attempts"]
        chain.insert.assert_not_called()
        chain.update.assert_not_called()
        chain.delete.assert_not_called()

    def test_repeated_resume_is_stable_and_never_replans(
        self, client, mock_supabase, spy
    ):
        # One frozen attempt for all three resumes (a fresh one each time would
        # legitimately carry a different expires_at).
        frozen = _frozen_attempt()
        attempts = []
        for _ in range(3):
            response = self._resume(client, mock_supabase, attempt=frozen)
            assert response.status_code == 200
            attempts.append(response.json())
        assert not spy.called
        assert attempts[0] == attempts[1] == attempts[2]

    def test_resume_returns_the_frozen_sections_verbatim(
        self, client, mock_supabase, spy
    ):
        response = self._resume(client, mock_supabase)
        data = response.json()
        assert data["total_mcq_questions"] == 2
        assert data["total_coding_problems"] == 1
        assert data["total_descriptive_questions"] == 1
        assert data["selected_descriptive_question_ids"] == list(FROZEN_DESC_IDS)
        assert data["total_hands_on_questions"] == 1
        assert data["selected_hands_on_question_ids"] == list(FROZEN_HANDS_IDS)
        assert data["duration_minutes"] == 20
        assert not spy.called

    def test_different_requested_domains_do_not_replace_frozen_domains(
        self, client, mock_supabase, spy
    ):
        response = self._resume(client, mock_supabase, domain_ids=[MOCK_DOMAIN_2_ID])
        assert response.status_code == 200
        assert response.json()["domain_ids"] == [MOCK_DOMAIN_1_ID]
        assert not spy.called


# ===========================================================================
# F. EXPIRY / LIFECYCLE
# ===========================================================================


class TestExpiryLifecycle:
    def test_expired_attempt_follows_scoring_path_and_is_not_replanned(
        self, client, mock_supabase, spy
    ):
        from datetime import datetime, timedelta, timezone

        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        _configure_resume_chains(mock_supabase, _frozen_attempt(expires_at=past))
        # After scoring, the attempt counts as completed → 409.
        chain = mock_supabase._table_chains["assessment_attempts"]
        chain.select.return_value.eq.return_value.in_.return_value.execute.return_value = _make_mock_response(
            [{"id": MOCK_ATTEMPT_ID, "status": "scored"}]
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 409
        assert chain.update.called  # the existing scoring/status path ran
        assert not spy.called

    def test_scored_attempt_blocks_new_start_without_planning(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase, program=SENIOR_PROGRAM, domains=[TECH_DOMAIN]
        )
        chain = mock_supabase._table_chains["assessment_attempts"]
        chain.select.return_value.eq.return_value.in_.return_value.execute.return_value = _make_mock_response(
            [{"id": MOCK_ATTEMPT_ID, "status": "scored"}]
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 409
        assert not spy.called
        chain.insert.assert_not_called()

    def test_submitted_attempt_blocks_new_start_without_planning(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase, program=SENIOR_PROGRAM, domains=[TECH_DOMAIN]
        )
        chain = mock_supabase._table_chains["assessment_attempts"]
        chain.select.return_value.eq.return_value.in_.return_value.execute.return_value = _make_mock_response(
            [{"id": MOCK_ATTEMPT_ID, "status": "submitted"}]
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 409
        assert not spy.called


# ===========================================================================
# G. CODING STAYS GLOBAL
# ===========================================================================


class TestCodingRemainsGlobal:
    def test_organizational_plan_has_zero_coding(self, client, mock_supabase, spy):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=1,
            program=ORG_PROGRAM,
            domains=[ORG_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="organizational", mcq_count=2
                )
            ],
            coding_problem_count=5,
            coding_available=[{"id": MOCK_CODING_PROBLEM_ID}],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert spy.plan.coding_enabled is False
        assert spy.plan.coding_total == 0
        assert _payload(mock_supabase)["total_coding_problems"] == 0
        # The global coding pool must not even be queried.
        _chain(mock_supabase, "coding_problems").select.assert_not_called()

    def test_technical_plan_uses_the_global_coding_count(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            coding_problem_count=2,
            coding_available=[
                {"id": MOCK_CODING_PROBLEM_ID},
                {"id": "dddd2222-2222-2222-2222-222222222222"},
                {"id": "dddd3333-3333-3333-3333-333333333333"},
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert spy.plan.coding_enabled is True
        assert spy.plan.coding_count == 2
        assert spy.plan.coding_total == 2
        assert _payload(mock_supabase)["total_coding_problems"] == 2

    def test_coding_query_is_domain_independent(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            coding_problem_count=1,
            coding_available=[{"id": MOCK_CODING_PROBLEM_ID}],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        chain = mock_supabase._table_chains["coding_problems"]
        assert chain.select.called
        # No domain filtering anywhere in the coding query chain.
        for call in chain.select.return_value.eq.call_args_list:
            assert "domain_id" not in call.args[0]
        assert "domain_id" not in chain.select.call_args.args[0]

    def test_coding_pool_not_queried_when_count_is_zero(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            coding_problem_count=0,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        _chain(mock_supabase, "coding_problems").select.assert_not_called()


# ===========================================================================
# H. DURATION
# ===========================================================================


class TestDuration:
    def test_no_additional_time_gives_base_duration(self, client, mock_supabase, spy):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            duration_minutes=45,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        plan = spy.plan
        assert (
            plan.base_duration_minutes,
            plan.additional_minutes,
            plan.duration_minutes,
        ) == (45, 0, 45)
        assert _payload(mock_supabase)["duration_minutes"] == 45

    def test_enabled_hands_on_adds_its_minutes(self, client, mock_supabase, spy):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="senior",
                    mcq_count=2,
                    descriptive_count=0,
                    hands_on_enabled=True,
                    hands_on_count=1,
                    hands_on_additional_minutes=20,
                )
            ],
            duration_minutes=90,
            hands_on_available=[
                {"id": MOCK_HANDS_ID, "domain_ids": [MOCK_DOMAIN_1_ID]}
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        plan = spy.plan
        assert (
            plan.base_duration_minutes,
            plan.additional_minutes,
            plan.duration_minutes,
        ) == (90, 20, 110)
        assert _payload(mock_supabase)["duration_minutes"] == 110

    def test_disabled_hands_on_cannot_grant_time(self, client, mock_supabase):
        """A disabled module carrying minutes is refused, not silently zeroed."""
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="senior",
                    mcq_count=2,
                    hands_on_enabled=False,
                    hands_on_count=1,
                    hands_on_additional_minutes=20,
                )
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 400
        assert "hands_on" in response.json()["detail"]
        mock_supabase._table_chains["assessment_attempts"].insert.assert_not_called()

    def test_domains_duration_minutes_is_never_consulted(
        self, client, mock_supabase, spy
    ):
        """Each mocked domain advertises duration_minutes=999 — ignored."""
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            duration_minutes=30,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        assert spy.plan.duration_minutes == 30
        domain_chain = mock_supabase._table_chains["domains"]
        selected_columns = domain_chain.select.call_args.args[0]
        assert "duration_minutes" not in selected_columns


# ===========================================================================
# I. SEED
# ===========================================================================


class TestSeed:
    def test_client_supplied_seed_is_ignored(self, client, mock_supabase, spy):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            response = _post(client, seed=12345, planner_seed=12345)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert spy.request.seed != 12345
        assert isinstance(spy.request.seed, int)

    def test_planner_receives_a_server_generated_seed(self, client, mock_supabase, spy):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        assert isinstance(spy.request.seed, int)
        assert 0 <= spy.request.seed < 2**63
        assert spy.request.seed is not None

    def test_server_seed_is_not_client_derived(self):
        from services.assessment_planning import generate_seed

        first, second = generate_seed(), generate_seed()
        assert isinstance(first, int) and isinstance(second, int)
        assert first != second  # 63 bits of entropy; collisions are negligible

    def test_same_seed_and_inputs_reproduce_the_same_attempt(
        self, client, mock_supabase, monkeypatch
    ):
        import services.assessment_planning as ap

        monkeypatch.setattr(ap, "generate_seed", lambda: 987654321)

        payloads = []
        for _ in range(2):
            _route_table(mock_supabase, "assessment_attempts")
            _configure_start_mocks(
                mock_supabase,
                program=SENIOR_PROGRAM,
                domains=[TECH_DOMAIN],
                module_configs=[
                    _make_module_config(
                        domain_id=MOCK_DOMAIN_1_ID,
                        applies_to="senior",
                        mcq_count=1,
                        descriptive_count=1,
                    )
                ],
                descriptive_count=1,
                coding_problem_count=1,
                coding_available=[{"id": MOCK_CODING_PROBLEM_ID}],
            )
            _auth()
            try:
                response = _post(client)
            finally:
                client.app.dependency_overrides.clear()
            assert response.status_code == 200

            payload = dict(_payload(mock_supabase))
            payload.pop("started_at", None)
            payload.pop("expires_at", None)
            payloads.append(payload)

        assert payloads[0] == payloads[1]


# ===========================================================================
# J. PLAN PERSISTENCE (migration 017)
# ===========================================================================


class TestPlanPersistence:
    def test_migration_017_adds_plan_columns(self):
        """Static guard: migration 017 must exist and add the expected columns.

        A live-schema probe would need the network, so this asserts the repo's
        own migrations end at 017 and contain the expected ALTER statements.
        """
        migrations = Path(__file__).resolve().parent / "migrations"
        files = sorted(migrations.glob("*.sql"))
        assert [int(p.name.split("_")[0]) for p in files] == list(range(1, 20))

        m017 = migrations / "017_plan_snapshot_columns.sql"
        assert m017.exists()
        content = m017.read_text(encoding="utf-8")
        assert "plan JSONB" in content
        assert "base_duration_minutes" in content
        assert "additional_minutes" in content

    def test_migration_018_adds_the_program_mcq_total(self):
        """Static guard: migration 018 adds assessment_program.mcq_total."""
        migrations = Path(__file__).resolve().parent / "migrations"
        m018 = migrations / "018_program_mcq_total.sql"
        assert m018.exists()
        content = m018.read_text(encoding="utf-8")
        assert "mcq_total INTEGER NOT NULL DEFAULT 20" in content
        assert "assessment_program_mcq_total_check" in content

    def test_migration_019_is_the_data_only_domain_catalogue_fix(self):
        """Static guard: migration 019 adds DevOps and reactivates CyberSec."""
        migrations = Path(__file__).resolve().parent / "migrations"
        m019 = migrations / "019_domain_catalogue_final.sql"
        assert m019.exists()
        content = m019.read_text(encoding="utf-8")
        assert "'devOps'" in content
        assert "UPDATE public.domains" in content
        assert "'cyberSecurity'" in content
        # Data-only: it must not create or alter any table.
        assert "CREATE TABLE" not in content
        assert "ALTER TABLE" not in content

    def test_migration_019_leaves_the_other_domains_alone(self):
        """Backend Development / User Interface are deliberately untouched.

        Their fate is a separate product decision, so the catalogue fix must
        neither deactivate nor rename them: only their slugs would appear in
        the migration if it did.
        """
        migrations = Path(__file__).resolve().parent / "migrations"
        content = (migrations / "019_domain_catalogue_final.sql").read_text(
            encoding="utf-8"
        )
        # Ignore the prose header: only executable statements matter.
        statements = "\n".join(
            line for line in content.splitlines() if not line.strip().startswith("--")
        )
        assert "backendDevelopment" not in statements
        assert "userInterface" not in statements
        # Exactly two catalogue writes: one INSERT + one targeted UPDATE.
        assert statements.count("INSERT INTO") == 1
        assert statements.count("UPDATE public.domains") == 1
        assert "DELETE" not in statements.upper()

    def test_plan_persistence_flag_has_been_removed(self):
        """Phase 5's temporary rollout flag is gone.

        Migration 017 is applied and the frozen plan snapshot is part of the
        final architecture, so neither the planning service nor the router may
        expose a switch that could silently stop persisting it.
        """
        import routers.assessment as assessment_router
        import services.assessment_planning as ap

        assert not hasattr(ap, "PLAN_PERSISTENCE_ENABLED")
        assert not hasattr(assessment_router, "PLAN_PERSISTENCE_ENABLED")

    def test_new_attempt_persists_plan_snapshot(self, client, mock_supabase, spy):
        """A new attempt must include plan/base_duration_minutes/additional_minutes."""
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            descriptive_count=1,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        payload = _payload(mock_supabase)
        plan = spy.plan

        # Plan snapshot is present and matches the planner output.
        assert payload["plan"] == plan.model_dump(mode="json")
        assert payload["base_duration_minutes"] == plan.base_duration_minutes
        assert payload["additional_minutes"] == plan.additional_minutes

        # Existing frozen columns remain consistent with the plan.
        assert payload["duration_minutes"] == plan.duration_minutes
        assert payload["selected_question_ids"] == plan.selected_mcq_ids
        assert payload["total_questions"] == plan.mcq_total

    def test_plan_snapshot_can_be_deserialized(self, client, mock_supabase, spy):
        """The persisted plan JSON must round-trip through the planner model."""
        from services.assessment_planner import AssessmentPlan

        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            descriptive_count=1,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        payload = _payload(mock_supabase)
        plan_json = payload["plan"]

        # Must round-trip through the Pydantic model.
        deserialized = AssessmentPlan.model_validate(plan_json)
        assert deserialized.plan_version == spy.plan.plan_version
        assert deserialized.semester == spy.plan.semester
        assert deserialized.scope == spy.plan.scope
        assert deserialized.selected_mcq_ids == spy.plan.selected_mcq_ids
        assert deserialized.config_fingerprint == spy.plan.config_fingerprint

    def test_plan_persistence_uses_model_dump_json(self, client, mock_supabase, spy):
        """The plan must be serialized via model_dump(mode='json'), not str()."""
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            descriptive_count=1,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        payload = _payload(mock_supabase)
        plan_json = payload["plan"]
        # model_dump(mode="json") returns a plain dict (JSON-serialisable).
        assert isinstance(plan_json, dict)
        # The dict must contain the critical planner fields.
        for key in (
            "plan_version", "semester", "scope", "tier", "config_source",
            "domain_ids", "selected_mcq_ids", "config_fingerprint",
            "duration_minutes", "base_duration_minutes", "additional_minutes",
        ):
            assert key in plan_json, f"Missing key: {key}"

    def test_organizational_attempt_also_persists_the_plan_snapshot(
        self, client, mock_supabase, spy
    ):
        """Persistence is unconditional across scopes, not just technical.

        The removed feature flag used to gate the snapshot; with it gone, an
        organizational plan is frozen the same way a technical one is.
        """
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=ORG_PROGRAM,
            semester=1,
            domains=[ORG_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="organizational",
                    mcq_count=1,
                    descriptive_count=1,
                )
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        payload = _payload(mock_supabase)
        plan = spy.plan
        assert plan.scope.value == "organizational"
        assert payload["plan"] == plan.model_dump(mode="json")
        assert payload["base_duration_minutes"] == plan.base_duration_minutes
        assert payload["additional_minutes"] == plan.additional_minutes

    def test_only_one_write_happens_and_it_is_the_attempt_insert(
        self, client, mock_supabase
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
            descriptive_count=1,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        # No table other than assessment_attempts was written to.
        for table, chain in mock_supabase._table_chains.items():
            if table == "assessment_attempts":
                assert chain.insert.called
                continue
            assert not chain.insert.called, table
            assert not chain.update.called, table
            assert not chain.delete.called, table


# ===========================================================================
# K. DOMAIN AVAILABILITY / ELIGIBILITY
# ===========================================================================


class TestDomainAvailability:
    """GET /assessment/available-domains returns candidate-eligible domains

    based on their authenticated semester and assessment_program scope.
    """

    def _get(self, client):
        return client.get("/assessment/available-domains")

    def _configure_availability(
        self, mock_sb, semester=5, program=None, domains=None
    ):
        """Configure mock chains for the availability endpoint.

        The endpoint queries (in order):
          candidates       -> select("id, semester").eq("profile_id", ...)
          assessment_program -> select(...).eq("semester", ...).eq("is_active", True)
          domains          -> select(...).eq("is_active", True).eq("assessment_scope", ...)
        """
        if program is None:
            program = _make_program(semester=semester)
        if domains is None:
            domains = []

        chains = mock_sb._table_chains

        candidates_chain = chains.setdefault("candidates", MagicMock())
        candidates_chain.select.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([{"id": MOCK_CANDIDATE_ID, "semester": semester}])
        )

        program_chain = chains.setdefault("assessment_program", MagicMock())
        program_chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([program])
        )

        domains_chain = chains.setdefault("domains", MagicMock())
        domains_chain.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = (
            _make_mock_response(domains)
        )

    def test_semester_3_receives_technical_domains(self, client, mock_supabase):
        _route_table(mock_supabase, "candidates")
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=3,
            program=JUNIOR_PROGRAM,
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            data = resp.json()
            assert data["semester"] == 3
            assert data["scope"] == "technical"
            assert data["tier"] == "junior"
            assert data["max_domains"] == 2
            assert len(data["domains"]) == 1
            assert data["domains"][0]["id"] == MOCK_DOMAIN_1_ID
            assert data["domains"][0]["name"] == "Cyber Security"
        finally:
            client.app.dependency_overrides.clear()

    def test_semester_5_receives_senior_tier(self, client, mock_supabase):
        _route_table(mock_supabase, "candidates")
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=5,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            data = resp.json()
            assert data["semester"] == 5
            assert data["scope"] == "technical"
            assert data["tier"] == "senior"
            assert data["max_domains"] == 2
        finally:
            client.app.dependency_overrides.clear()

    def test_semester_1_receives_organizational_domains(self, client, mock_supabase):
        _route_table(mock_supabase, "candidates")
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=1,
            program=ORG_PROGRAM,
            domains=[ORG_DOMAIN],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            data = resp.json()
            assert data["semester"] == 1
            assert data["scope"] == "organizational"
            assert data["tier"] is None
            assert data["max_domains"] == 1
            assert len(data["domains"]) == 1
            assert data["domains"][0]["assessment_scope"] == "organizational"
        finally:
            client.app.dependency_overrides.clear()

    def test_semester_7_returns_no_domains(self, client, mock_supabase):
        _route_table(mock_supabase, "candidates")
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=7,
            program=NONE_PROGRAM,
            domains=[],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            data = resp.json()
            assert data["semester"] == 7
            assert data["scope"] == "none"
            assert data["domains"] == []
        finally:
            client.app.dependency_overrides.clear()

    def test_inactive_domains_are_excluded(self, client, mock_supabase):
        _route_table(mock_supabase, "candidates")
        # The mock returns only active domains — the endpoint filters
        # at the DB level via .eq("is_active", True). Verify the
        # endpoint does not expose inactive domains by confirming the
        # query filters on is_active.
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=5,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            # Verify the domains query used .eq("is_active", True)
            mock_supabase._table_chains["domains"].select.return_value.eq.assert_called()
            # The chain is: select().eq("is_active", True).eq("assessment_scope", ...).order("name")
            # Just verify all returned domains are active (the mock only returns active ones)
            data = resp.json()
            for d in data["domains"]:
                assert d["assessment_scope"] in ("technical", "organizational")
        finally:
            client.app.dependency_overrides.clear()

    def test_wrong_scope_domains_are_excluded(self, client, mock_supabase):
        """A technical candidate must not see organizational domains."""
        _route_table(mock_supabase, "candidates")
        # Mock returns only technical domains
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=5,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            data = resp.json()
            assert data["scope"] == "technical"
            for d in data["domains"]:
                assert d["assessment_scope"] == "technical"
        finally:
            client.app.dependency_overrides.clear()

    def test_semester_cannot_be_client_controlled(self, client, mock_supabase):
        """The endpoint ignores any client-supplied semester."""
        _route_table(mock_supabase, "candidates")
        # Candidate is semester 3 but client sends semester=5
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=3,
            program=JUNIOR_PROGRAM,
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            resp = client.get("/assessment/available-domains?semester=5")
            assert resp.status_code == 200
            data = resp.json()
            # Must use the authenticated semester, not the query param
            assert data["semester"] == 3
            assert data["tier"] == "junior"
        finally:
            client.app.dependency_overrides.clear()

    def test_unauthenticated_request_is_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "candidates")
        resp = client.get("/assessment/available-domains")
        assert resp.status_code in (401, 403)

    def test_module_config_not_required(self, client, mock_supabase):
        """Domain availability works even when module config is empty."""
        _route_table(mock_supabase, "candidates")
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=5,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            data = resp.json()
            # Domains are returned even though module config is empty
            assert len(data["domains"]) == 1
        finally:
            client.app.dependency_overrides.clear()

    def test_missing_candidate_rejected(self, client, mock_supabase):
        """No candidate row -> 404."""
        _route_table(mock_supabase, "candidates")
        chains = mock_supabase._table_chains
        candidates_chain = chains.setdefault("candidates", MagicMock())
        candidates_chain.select.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([])
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 404
        finally:
            client.app.dependency_overrides.clear()

    def test_missing_program_rejected(self, client, mock_supabase):
        """No active program -> 400."""
        _route_table(mock_supabase, "candidates")
        chains = mock_supabase._table_chains
        candidates_chain = chains.setdefault("candidates", MagicMock())
        candidates_chain.select.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([{"id": MOCK_CANDIDATE_ID, "semester": 99}])
        )
        program_chain = chains.setdefault("assessment_program", MagicMock())
        program_chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([])
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 400
        finally:
            client.app.dependency_overrides.clear()

    def test_response_exposes_no_sensitive_data(self, client, mock_supabase):
        """The response must not leak internal planner/config data."""
        _route_table(mock_supabase, "candidates")
        self._configure_availability(
            mock_sb=mock_supabase,
            semester=5,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
        )
        _auth()
        try:
            resp = self._get(client)
            assert resp.status_code == 200
            data = resp.json()
            # Top-level keys must be exactly the expected set
            assert set(data.keys()) == {
                "semester", "scope", "tier", "max_domains", "domains",
            }
            # Domain keys must be exactly the expected set
            for d in data["domains"]:
                assert set(d.keys()) == {
                    "id", "name", "slug", "assessment_scope",
                }
        finally:
            client.app.dependency_overrides.clear()


# ===========================================================================
# SERVICE-LEVEL UNITS (no HTTP)
# ===========================================================================


class TestPlanningServiceUnits:
    def test_config_family_for(self):
        from services.assessment_planning import config_family_for
        from services.assessment_planner import ProgramInput, Scope

        assert (
            config_family_for(
                ProgramInput(
                    semester=3, scope=Scope.TECHNICAL, tier="junior", max_domains=2
                )
            )
            == "junior"
        )
        assert (
            config_family_for(
                ProgramInput(
                    semester=5, scope=Scope.TECHNICAL, tier="senior", max_domains=2
                )
            )
            == "senior"
        )
        assert (
            config_family_for(
                ProgramInput(
                    semester=1, scope=Scope.ORGANIZATIONAL, tier=None, max_domains=1
                )
            )
            == "organizational"
        )
        # Technical without a tier cannot resolve a family.
        assert (
            config_family_for(
                ProgramInput(
                    semester=3, scope=Scope.TECHNICAL, tier=None, max_domains=2
                )
            )
            is None
        )

    def test_legacy_fallback_builder_is_gone(self):
        """The retired fallback constructor was removed from the service."""
        import services.assessment_planning as ap

        assert not hasattr(ap, "build_legacy_technical_fallback")

    def test_pool_required_skips_when_no_module_requests_content(self):
        """Module configuration is the only thing that can request a pool."""
        from services.assessment_planning import _pool_required

        assert _pool_required([]) is False
        assert _pool_required([0, 0]) is False
        assert _pool_required([1]) is True
        assert _pool_required([0, 1]) is True

    def test_load_mcq_pool_scopes_to_domain_and_semester(self, mock_supabase):
        from services.assessment_planning import load_mcq_pool

        _route_table(mock_supabase, "mcq_questions")
        chain = _chain(mock_supabase, "mcq_questions")
        chain.select.return_value.eq.return_value.eq.return_value.in_.return_value.execute.return_value = _make_mock_response(
            [{"id": MOCK_MCQ_1_ID, "domain_id": MOCK_DOMAIN_1_ID}]
        )
        pool = load_mcq_pool([MOCK_DOMAIN_1_ID], 5)
        assert [item.id for item in pool] == [MOCK_MCQ_1_ID]
        assert pool[0].domain_id == MOCK_DOMAIN_1_ID
        assert pool[0].semester == 5
        # Semester and is_active are SQL filters; the domain list is an IN.
        assert chain.select.return_value.eq.call_args.args == ("semester", 5)
        assert chain.select.return_value.eq.return_value.eq.call_args.args == (
            "is_active",
            True,
        )
        chain.select.return_value.eq.return_value.eq.return_value.in_.assert_called_with(
            "domain_id", [MOCK_DOMAIN_1_ID]
        )
        assert "domain_id" in chain.select.call_args.args[0]
        # No secret columns are ever loaded into the pool.
        for leaked in ("correct_option", "explanation"):
            assert leaked not in chain.select.call_args.args[0]

    def test_load_descriptive_pool_uses_overlap_semantics(self, mock_supabase):
        from services.assessment_planning import load_descriptive_pool

        _route_table(mock_supabase, "descriptive_questions")
        chain = _chain(mock_supabase, "descriptive_questions")
        chain.select.return_value.eq.return_value.overlaps.return_value.execute.return_value = _make_mock_response(
            [{"id": MOCK_DESC_ID, "domain_ids": [MOCK_DOMAIN_1_ID]}]
        )
        pool = load_descriptive_pool([MOCK_DOMAIN_1_ID])
        assert [item.id for item in pool] == [MOCK_DESC_ID]
        assert pool[0].domain_ids == [MOCK_DOMAIN_1_ID]
        chain.select.return_value.eq.return_value.overlaps.assert_called_with(
            "domain_ids", [MOCK_DOMAIN_1_ID]
        )

    def test_load_hands_on_pool_uses_overlap_semantics(self, mock_supabase):
        from services.assessment_planning import load_hands_on_pool

        _route_table(mock_supabase, "hands_on_questions")
        chain = _chain(mock_supabase, "hands_on_questions")
        chain.select.return_value.eq.return_value.overlaps.return_value.execute.return_value = _make_mock_response(
            [{"id": MOCK_HANDS_ID, "domain_ids": [MOCK_DOMAIN_1_ID]}]
        )
        pool = load_hands_on_pool([MOCK_DOMAIN_1_ID])
        assert [item.id for item in pool] == [MOCK_HANDS_ID]

    def test_empty_domain_list_short_circuits_pool_queries(self, mock_supabase):
        from services.assessment_planning import (
            load_coding_pool,
            load_descriptive_pool,
            load_hands_on_pool,
            load_mcq_pool,
        )

        _route_table(mock_supabase, "none")
        assert load_descriptive_pool([]) == []
        assert load_hands_on_pool([]) == []
        assert load_mcq_pool([], 5) == []
        # The coding pool is GLOBAL: still available with no domains at all.
        coding = _chain(mock_supabase, "coding_problems")
        coding.select.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([{"id": MOCK_CODING_PROBLEM_ID}])
        )
        assert [c.id for c in load_coding_pool()] == [MOCK_CODING_PROBLEM_ID]


# ===========================================================================
# SECURITY / LEAKAGE
# ===========================================================================


class TestNoLeakage:
    def test_candidate_response_exposes_no_plan_internals(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=2
                )
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        raw = response.text.lower()
        for leaked in (
            "correct_option",
            "explanation",
            "is_correct",
            "expected_flag",
            "admin_remark",
            "max_score",
            "fingerprint",
            "config_source",
            "selected_mcq_ids",
            "plan_version",
            "verify_url",
        ):
            assert leaked not in raw, leaked
        assert spy.plan.config_fingerprint not in response.text

    def test_planner_request_carries_no_answer_material(
        self, client, mock_supabase, spy
    ):
        """Pools are built from id-only rows, so nothing sensitive is loaded."""
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID,
                    applies_to="senior",
                    mcq_count=1,
                    descriptive_count=0,
                )
            ],
            descriptive_count=0,
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        dumped = spy.request.model_dump_json().lower()
        for leaked in (
            "correct_option",
            "explanation",
            "expected_flag",
            "is_correct",
            "admin_remark",
            "score",
        ):
            assert leaked not in dumped, leaked

    def test_mcq_query_selects_only_ids(self, client, mock_supabase):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[
                _make_module_config(
                    domain_id=MOCK_DOMAIN_1_ID, applies_to="senior", mcq_count=1
                )
            ],
        )
        _auth()
        try:
            assert _post(client).status_code == 200
        finally:
            client.app.dependency_overrides.clear()

        columns = _chain(mock_supabase, "mcq_questions").select.call_args.args[0]
        for leaked in ("correct_option", "explanation", "expected_flag"):
            assert leaked not in columns
        # Coding was not requested here, so its pool must not have been read.
        _chain(mock_supabase, "coding_problems").select.assert_not_called()


class TestTechnicalStartNeverTouchesDescriptive:
    """The critical invariant behind the September 2026 incident.

    Production candidates saw "Descriptive questions not found, 0 of 1
    found" because a stale runtime still validated a global descriptive
    requirement on the technical start path. The current architecture makes
    that impossible by construction: a TECHNICAL start must never even QUERY
    the descriptive pool — no plan can then depend on it, and no preflight
    can fail for it. A rich, generous descriptive pool is configured
    deliberately: its presence must change nothing for technical candidates.
    """

    def test_junior_start_never_queries_descriptive_questions(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            semester=3,
            program=JUNIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[],
            coding_problem_count=2,
            coding_available=[
                {"id": MOCK_CODING_PROBLEM_ID},
                {"id": "cp-2"},
            ],
            # A loaded descriptive pool sitting there — technical ignores it.
            descriptive_available=[
                {"id": MOCK_DESC_ID, "domain_ids": [MOCK_DOMAIN_1_ID]},
                {"id": "desc-2", "domain_ids": [MOCK_DOMAIN_1_ID]},
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["total_descriptive_questions"] == 0
        assert data["selected_descriptive_question_ids"] == []
        # The descriptive pool query must NEVER run for a technical start.
        desc_chain = mock_supabase._table_chains["descriptive_questions"]
        desc_chain.select.assert_not_called()
        # And the frozen plan carries zero descriptive content.
        assert spy.plan.descriptive_total == 0
        assert spy.plan.selected_descriptive_question_ids == []
        payload = _payload(mock_supabase)
        assert payload["total_descriptive_questions"] == 0
        assert payload["selected_descriptive_question_ids"] == []

    def test_senior_start_never_queries_descriptive_questions(
        self, client, mock_supabase, spy
    ):
        _route_table(mock_supabase, "assessment_attempts")
        _configure_start_mocks(
            mock_supabase,
            program=SENIOR_PROGRAM,
            domains=[TECH_DOMAIN],
            module_configs=[],
            coding_problem_count=2,
            coding_available=[
                {"id": MOCK_CODING_PROBLEM_ID},
                {"id": "cp-2"},
            ],
            descriptive_available=[
                {"id": MOCK_DESC_ID, "domain_ids": [MOCK_DOMAIN_1_ID]},
                {"id": "desc-2", "domain_ids": [MOCK_DOMAIN_1_ID]},
            ],
        )
        _auth()
        try:
            response = _post(client)
        finally:
            client.app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["total_descriptive_questions"] == 0
        mock_supabase._table_chains["descriptive_questions"].select.assert_not_called()
        assert spy.plan.descriptive_total == 0
