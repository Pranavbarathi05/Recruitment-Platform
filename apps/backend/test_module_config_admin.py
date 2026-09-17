"""Phase 7A integration tests: admin module configuration API.

Tests exercise GET /admin/assessment/modules, GET .../{domain_id}, and
PUT .../{domain_id} against mocked database responses.  The real
assessment_module_config table remains EMPTY throughout.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from test_main import (
    MOCK_DOMAIN_1_ID,
    MOCK_DOMAIN_2_ID,
    _make_mock_response,
    _route_table,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_ADMIN_ID = "admin-0000-0000-000000000001"
MOCK_CANDIDATE_ID = "cand-0000-0000-000000000001"

TECH_DOMAIN = {
    "id": MOCK_DOMAIN_1_ID,
    "name": "Machine Learning",
    "slug": "machineLearning",
    "assessment_scope": "technical",
    "is_active": True,
}

ORG_DOMAIN = {
    "id": MOCK_DOMAIN_2_ID,
    "name": "Organizational Roles",
    "slug": "organizationalRoles",
    "assessment_scope": "organizational",
    "is_active": True,
}

INACTIVE_DOMAIN = {
    "id": "inactive-domain-id",
    "name": "Inactive Domain",
    "slug": "inactiveDomain",
    "assessment_scope": "technical",
    "is_active": False,
}


@pytest.fixture(autouse=True)
def mock_supabase():
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        _make_mock_response([])
    )
    with patch("core.supabase.supabase_client", mock_client), patch(
        "routers.module_config_admin.supabase_client", mock_client
    ), patch("routers.admin.supabase_client", mock_client):
        yield mock_client


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _admin_auth():
    from core.auth import get_current_user, require_admin
    from main import app

    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        id=MOCK_ADMIN_ID, email="admin@test.com"
    )
    app.dependency_overrides[require_admin] = lambda: MagicMock(
        id=MOCK_ADMIN_ID, email="admin@test.com"
    )
    return app


def _candidate_auth():
    from core.auth import get_current_user, require_admin
    from main import app

    app.dependency_overrides[get_current_user] = lambda: MagicMock(
        id=MOCK_CANDIDATE_ID, email="candidate@test.com"
    )
    # require_admin will raise 403 for non-admin

    def _reject_admin():
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[require_admin] = _reject_admin
    return app


def _clear_auth():
    from core.auth import get_current_user, require_admin
    from main import app

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_admin, None)


def _configure_domains(mock_sb, domains=None):
    """Set up the domains table mock to return the given domains."""
    if domains is None:
        domains = [TECH_DOMAIN]
    chains = mock_sb._table_chains

    domains_chain = chains.setdefault("domains", MagicMock())
    # For .select().order() — list all
    domains_chain.select.return_value.order.return_value.execute.return_value = (
        _make_mock_response(domains)
    )
    # For .select().eq() — single domain
    domains_chain.select.return_value.eq.return_value.execute.return_value = (
        _make_mock_response(domains[:1] if domains else [])
    )


def _configure_module_config(mock_sb, configs=None):
    """Set up the assessment_module_config table mock."""
    if configs is None:
        configs = []
    chains = mock_sb._table_chains

    config_chain = chains.setdefault("assessment_module_config", MagicMock())
    # For .select("*") — list all
    config_chain.select.return_value.execute.return_value = _make_mock_response(
        configs
    )
    # For .select("*").eq("domain_id", ...) — per domain
    config_chain.select.return_value.eq.return_value.execute.return_value = (
        _make_mock_response(configs)
    )
    # For .select("id").eq("domain_id", ...).eq("applies_to", ...) — upsert check
    config_chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
        _make_mock_response([])
    )
    # For .insert() — create
    config_chain.insert.return_value.execute.return_value = _make_mock_response(
        configs[:1] if configs else []
    )
    # For .update() — update
    config_chain.update.return_value.eq.return_value.execute.return_value = (
        _make_mock_response(configs[:1] if configs else [])
    )


def _assert_no_config_writes(mock_sb):
    """Assert the module-config table received no INSERT and no UPDATE."""
    chain = mock_sb._table_chains.get("assessment_module_config")
    if chain is not None:
        chain.insert.assert_not_called()
        chain.update.assert_not_called()


def _configure_preflight_pools(
    mock_sb, mcq_count=0, desc_count=0, hands_count=0, shared=False
):
    """Set up question pool mocks for preflight validation.

    ``shared=True`` makes each descriptive/hands-on row belong to a SECOND
    domain as well, which is precisely what the cross-domain advisory warning
    detects.
    """
    chains = mock_sb._table_chains

    mcq_chain = chains.setdefault("mcq_questions", MagicMock())
    mcq_chain.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        _make_mock_response([{"id": f"mcq-{i}"} for i in range(mcq_count)])
    )

    desc_domains = [MOCK_DOMAIN_1_ID, MOCK_DOMAIN_2_ID] if shared else [MOCK_DOMAIN_1_ID]
    desc_chain = chains.setdefault("descriptive_questions", MagicMock())
    desc_chain.select.return_value.eq.return_value.contains.return_value.execute.return_value = (
        _make_mock_response(
            [
                {"id": f"desc-{i}", "domain_ids": desc_domains}
                for i in range(desc_count)
            ]
        )
    )

    hands_domains = [MOCK_DOMAIN_1_ID, MOCK_DOMAIN_2_ID] if shared else [MOCK_DOMAIN_1_ID]
    hands_chain = chains.setdefault("hands_on_questions", MagicMock())
    hands_chain.select.return_value.eq.return_value.contains.return_value.execute.return_value = (
        _make_mock_response(
            [
                {"id": f"hands-{i}", "domain_ids": hands_domains}
                for i in range(hands_count)
            ]
        )
    )


# ===========================================================================
# AUTH TESTS
# ===========================================================================


class TestAuth:
    def test_unauthenticated_list_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase)
        resp = client.get("/admin/assessment/modules")
        assert resp.status_code in (401, 403)

    def test_non_admin_list_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase)
        _candidate_auth()
        try:
            resp = client.get("/admin/assessment/modules")
            assert resp.status_code in (401, 403)
        finally:
            _clear_auth()

    def test_admin_list_accepted(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _admin_auth()
        try:
            resp = client.get("/admin/assessment/modules")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)
        finally:
            _clear_auth()


# ===========================================================================
# READ TESTS
# ===========================================================================


class TestReadConfigs:
    def test_empty_config_returns_empty_collection(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN, ORG_DOMAIN])
        _configure_module_config(mock_supabase, configs=[])
        _admin_auth()
        try:
            resp = client.get("/admin/assessment/modules")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            # Each domain should have empty configs
            for entry in data:
                assert entry["configs"] == []
        finally:
            _clear_auth()

    def test_specific_domain_no_config(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase, configs=[])
        _admin_auth()
        try:
            resp = client.get(f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["domain"]["name"] == "Machine Learning"
            assert data["configs"] == []
        finally:
            _clear_auth()

    def test_nonexistent_domain_returns_404(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        # Empty domain response
        chains = mock_supabase._table_chains
        domains_chain = chains.setdefault("domains", MagicMock())
        domains_chain.select.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([])
        )
        _admin_auth()
        try:
            resp = client.get("/admin/assessment/modules/nonexistent-id")
            assert resp.status_code == 404
        finally:
            _clear_auth()

    def test_inactive_domain_handled(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [INACTIVE_DOMAIN])
        _configure_module_config(mock_supabase, configs=[])
        _admin_auth()
        try:
            resp = client.get(f"/admin/assessment/modules/{INACTIVE_DOMAIN['id']}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["domain"]["is_active"] is False
            assert data["configs"] == []
        finally:
            _clear_auth()


# ===========================================================================
# SCOPE VALIDATION TESTS
# ===========================================================================


class TestScopeValidation:
    def _put_config(self, client, domain_id, applies_to, **overrides):
        body = {
            "applies_to": applies_to,
            "mcq_count": 5,
            "descriptive_count": 0,
            "hands_on_enabled": False,
            "hands_on_count": 0,
            "hands_on_additional_minutes": 0,
        }
        body.update(overrides)
        return client.put(f"/admin/assessment/modules/{domain_id}", json=body)

    def test_technical_plus_junior_accepted(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)
        _admin_auth()
        try:
            resp = self._put_config(client, MOCK_DOMAIN_1_ID, "junior")
            assert resp.status_code == 200
            assert resp.json()["config"]["applies_to"] == "junior"
        finally:
            _clear_auth()

    def test_technical_plus_senior_accepted(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)
        _admin_auth()
        try:
            resp = self._put_config(client, MOCK_DOMAIN_1_ID, "senior")
            assert resp.status_code == 200
            assert resp.json()["config"]["applies_to"] == "senior"
        finally:
            _clear_auth()

    def test_technical_plus_organizational_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _admin_auth()
        try:
            resp = self._put_config(client, MOCK_DOMAIN_1_ID, "organizational")
            assert resp.status_code == 400
            assert "organizational" in resp.json()["detail"].lower()
        finally:
            _clear_auth()

    def test_organizational_plus_organizational_accepted(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [ORG_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)
        _admin_auth()
        try:
            resp = self._put_config(client, MOCK_DOMAIN_2_ID, "organizational")
            assert resp.status_code == 200
            assert resp.json()["config"]["applies_to"] == "organizational"
        finally:
            _clear_auth()

    def test_organizational_plus_junior_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [ORG_DOMAIN])
        _configure_module_config(mock_supabase)
        _admin_auth()
        try:
            resp = self._put_config(client, MOCK_DOMAIN_2_ID, "junior")
            assert resp.status_code == 400
            assert "junior" in resp.json()["detail"].lower()
        finally:
            _clear_auth()

    def test_organizational_plus_senior_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [ORG_DOMAIN])
        _configure_module_config(mock_supabase)
        _admin_auth()
        try:
            resp = self._put_config(client, MOCK_DOMAIN_2_ID, "senior")
            assert resp.status_code == 400
            assert "senior" in resp.json()["detail"].lower()
        finally:
            _clear_auth()

    def test_technical_descriptive_count_rejected(self, client, mock_supabase):
        """Descriptive belongs to the organizational assessment only.

        A technical row configuring descriptive questions would be silently
        inert at runtime, so it is refused rather than stored.
        """
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=9)
        _admin_auth()
        try:
            resp = self._put_config(
                client, MOCK_DOMAIN_1_ID, "senior", descriptive_count=3
            )
            assert resp.status_code == 400
            assert "descriptive" in resp.json()["detail"].lower()
            _assert_no_config_writes(mock_supabase)
        finally:
            _clear_auth()

    def test_organizational_descriptive_count_accepted(self, client, mock_supabase):
        """Organizational Roles keeps a genuinely configurable descriptive mix."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [ORG_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=20, desc_count=8)
        _admin_auth()
        try:
            resp = self._put_config(
                client,
                MOCK_DOMAIN_2_ID,
                "organizational",
                mcq_count=15,
                descriptive_count=3,
            )
            assert resp.status_code == 200
            config = resp.json()["config"]
            assert config["mcq_count"] == 15
            assert config["descriptive_count"] == 3
        finally:
            _clear_auth()


# ===========================================================================
# HANDS-ON COUPLING TESTS
# ===========================================================================


class TestHandsOnCoupling:
    def _put_config(self, client, domain_id, **overrides):
        body = {
            "applies_to": "junior",
            "mcq_count": 5,
            "descriptive_count": 0,
            "hands_on_enabled": False,
            "hands_on_count": 0,
            "hands_on_additional_minutes": 0,
        }
        body.update(overrides)
        return client.put(f"/admin/assessment/modules/{domain_id}", json=body)

    def test_disabled_plus_nonzero_count_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _admin_auth()
        try:
            resp = self._put_config(
                client, MOCK_DOMAIN_1_ID, hands_on_count=2
            )
            assert resp.status_code in (400, 422)
        finally:
            _clear_auth()

    def test_disabled_plus_nonzero_minutes_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _admin_auth()
        try:
            resp = self._put_config(
                client, MOCK_DOMAIN_1_ID, hands_on_additional_minutes=10
            )
            assert resp.status_code in (400, 422)
        finally:
            _clear_auth()

    def test_disabled_plus_zero_zero_accepted(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)
        _admin_auth()
        try:
            resp = self._put_config(
                client,
                MOCK_DOMAIN_1_ID,
                hands_on_enabled=False,
                hands_on_count=0,
                hands_on_additional_minutes=0,
            )
            assert resp.status_code == 200
        finally:
            _clear_auth()

    def test_enabled_plus_valid_values_accepted(self, client, mock_supabase):
        """The hands-on practical is a SENIOR module."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(
            mock_supabase, mcq_count=10, desc_count=5, hands_count=3
        )
        _admin_auth()
        try:
            resp = self._put_config(
                client,
                MOCK_DOMAIN_1_ID,
                applies_to="senior",
                hands_on_enabled=True,
                hands_on_count=1,
                hands_on_additional_minutes=10,
            )
            assert resp.status_code == 200
            config = resp.json()["config"]
            assert config["hands_on_enabled"] is True
            assert config["hands_on_count"] == 1
            assert config["hands_on_additional_minutes"] == 10
        finally:
            _clear_auth()

    def test_junior_hands_on_enabled_rejected(self, client, mock_supabase):
        """Junior has no practical, so enabling hands-on must not be stored.

        The planner ignores hands-on for a junior programme, so accepting this
        row would create configuration that looks meaningful but is inert.
        """
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(
            mock_supabase, mcq_count=10, desc_count=5, hands_count=3
        )
        _admin_auth()
        try:
            resp = self._put_config(
                client,
                MOCK_DOMAIN_1_ID,
                applies_to="junior",
                hands_on_enabled=True,
                hands_on_count=1,
                hands_on_additional_minutes=10,
            )
            assert resp.status_code == 400
            assert "hands-on" in resp.json()["detail"].lower()
            _assert_no_config_writes(mock_supabase)
        finally:
            _clear_auth()


# ===========================================================================
# COUNT VALIDATION TESTS
# ===========================================================================


class TestCountValidation:
    def test_negative_mcq_count_rejected(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "junior",
                    "mcq_count": -1,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 422
        finally:
            _clear_auth()

    def test_excessive_organizational_mcq_count_is_hard_error(
        self, client, mock_supabase
    ):
        """ORGANIZATIONAL mcq_count is authoritative -> shortage is a hard 400.

        The organizational assessment has no fixed total, so the configured MCQ
        count is exactly what the planner must draw. A pool that cannot satisfy
        it can never be planned, so the configuration must not be saved.
        """
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [ORG_DOMAIN])
        _configure_module_config(mock_supabase)
        # Pool has only 3 MCQs
        _configure_preflight_pools(mock_supabase, mcq_count=3, desc_count=5)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_2_ID}",
                json={
                    "applies_to": "organizational",
                    "mcq_count": 10,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 400
            assert "mcq" in resp.json()["detail"].lower()
            _assert_no_config_writes(mock_supabase)
        finally:
            _clear_auth()

    def test_technical_mcq_count_is_not_pool_validated(
        self, client, mock_supabase
    ):
        """Technical mcq_count is NOT pool-validated.

        MCQ quantity for technical comes from program.mcq_total, not from
        module config, so the module-config mcq_count is stored but NOT
        validated against the pool.
        """
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(
            mock_supabase, mcq_count=3, desc_count=5, hands_count=1
        )
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "senior",
                    "mcq_count": 999,
                    "descriptive_count": 0,
                    "hands_on_enabled": True,
                    "hands_on_count": 1,
                    "hands_on_additional_minutes": 10,
                },
            )
            assert resp.status_code == 200
        finally:
            _clear_auth()

    def test_excessive_organizational_descriptive_is_hard_error(
        self, client, mock_supabase
    ):
        """Descriptive shortage -> 4xx and ZERO writes.

        Assessed on the organizational domain, which is the only scope where
        descriptive_count is configurable.
        """
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [ORG_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=1)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_2_ID}",
                json={
                    "applies_to": "organizational",
                    "mcq_count": 5,
                    "descriptive_count": 5,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 400
            assert "descriptive" in resp.json()["detail"].lower()
            _assert_no_config_writes(mock_supabase)
        finally:
            _clear_auth()

    def test_excessive_hands_on_count_is_hard_error(self, client, mock_supabase):
        """Hands-on shortage -> 4xx and ZERO writes."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(
            mock_supabase, mcq_count=10, desc_count=5, hands_count=1
        )
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "senior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": True,
                    "hands_on_count": 5,
                    "hands_on_additional_minutes": 10,
                },
            )
            assert resp.status_code == 400
            assert "hands_on" in resp.json()["detail"].lower()
            _assert_no_config_writes(mock_supabase)
        finally:
            _clear_auth()

    def test_exact_pool_size_is_accepted(self, client, mock_supabase):
        """Requesting exactly the available count is not a shortage."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(
            mock_supabase, mcq_count=5, desc_count=2, hands_count=1
        )
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "senior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": True,
                    "hands_on_count": 1,
                    "hands_on_additional_minutes": 10,
                },
            )
            assert resp.status_code == 200
            assert resp.json()["preflight"]["hard_errors"] == []
        finally:
            _clear_auth()

    def test_disabled_module_ignores_hands_on_pool(
        self, client, mock_supabase
    ):
        """A disabled hands-on module is never a shortage, even with an empty pool."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=5, desc_count=2, hands_count=0)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "senior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 200
        finally:
            _clear_auth()


# ===========================================================================
# PREFLIGHT TESTS
# ===========================================================================


class TestPreflight:
    def test_preflight_reports_available_counts(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(
            mock_supabase, mcq_count=20, desc_count=8, hands_count=3
        )
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "senior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": True,
                    "hands_on_count": 1,
                    "hands_on_additional_minutes": 10,
                },
            )
            assert resp.status_code == 200
            preflight = resp.json()["preflight"]
            assert preflight["mcq_available"] == 20
            assert preflight["descriptive_available"] == 8
            assert preflight["hands_on_available"] == 3
            assert preflight["hard_errors"] == []
        finally:
            _clear_auth()

    def test_preflight_works_without_existing_config(self, client, mock_supabase):
        """Module config does not need to exist for preflight to work."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase, configs=[])
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "junior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 200
            preflight = resp.json()["preflight"]
            assert "mcq_available" in preflight
        finally:
            _clear_auth()

    def test_cross_domain_sharing_is_advisory_not_an_error(
        self, client, mock_supabase
    ):
        """Shared pools that still satisfy the per-domain quota are a WARNING.

        The single-domain preflight cannot prove multi-domain feasibility, so
        it must not reject the configuration — it flags the uncertainty.
        """
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(
            mock_supabase,
            mcq_count=10,
            desc_count=5,
            hands_count=3,
            shared=True,
        )
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "senior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": True,
                    "hands_on_count": 1,
                    "hands_on_additional_minutes": 10,
                },
            )
            assert resp.status_code == 200
            preflight = resp.json()["preflight"]
            assert preflight["hard_errors"] == []
            assert len(preflight["warnings"]) >= 1
        finally:
            _clear_auth()


# ===========================================================================
# WRITE SAFETY TESTS
# ===========================================================================


class TestWriteSafety:
    def test_invalid_config_causes_zero_writes(self, client, mock_supabase):
        """Scope mismatch must reject before any write."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "organizational",  # wrong for technical
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 400
            # Verify no insert/update was attempted on the config table
            config_chain = mock_supabase._table_chains.get(
                "assessment_module_config"
            )
            if config_chain:
                config_chain.insert.assert_not_called()
                config_chain.update.assert_not_called()
        finally:
            _clear_auth()

    def test_valid_config_performs_one_write(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "junior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 200
            # Exactly one write (insert) on the config table
            config_chain = mock_supabase._table_chains.get(
                "assessment_module_config"
            )
            if config_chain:
                write_count = (
                    config_chain.insert.call_count + config_chain.update.call_count
                )
                assert write_count == 1
        finally:
            _clear_auth()

    def test_existing_config_can_be_updated(self, client, mock_supabase):
        existing = {
            "id": "cfg-001",
            "domain_id": MOCK_DOMAIN_1_ID,
            "applies_to": "junior",
            "mcq_count": 3,
            "descriptive_count": 0,
            "hands_on_enabled": False,
            "hands_on_count": 0,
            "hands_on_additional_minutes": 0,
            "notes": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        }
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase, configs=[existing])
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)

        # Override the upsert-check chain to return the existing row
        config_chain = mock_supabase._table_chains["assessment_module_config"]
        config_chain.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
            _make_mock_response([{"id": "cfg-001"}])
        )

        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "junior",
                    "mcq_count": 8,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 200
            # Should have called update, not insert
            config_chain.update.assert_called()
        finally:
            _clear_auth()

    def test_unrelated_domains_not_modified(self, client, mock_supabase):
        """Writing config for domain A must not touch domain B."""
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN, ORG_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=10, desc_count=5)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "junior",
                    "mcq_count": 5,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 200
            # Verify the insert payload targets only domain 1
            config_chain = mock_supabase._table_chains["assessment_module_config"]
            if config_chain.insert.call_args:
                payload = config_chain.insert.call_args.args[0]
                assert payload["domain_id"] == MOCK_DOMAIN_1_ID
        finally:
            _clear_auth()


# ===========================================================================
# SECURITY TEST
# ===========================================================================


class TestSecurity:
    def test_response_exposes_no_question_content(self, client, mock_supabase):
        _route_table(mock_supabase, "domains")
        _configure_domains(mock_supabase, [TECH_DOMAIN])
        _configure_module_config(mock_supabase)
        _configure_preflight_pools(mock_supabase, mcq_count=5, desc_count=2)
        _admin_auth()
        try:
            resp = client.put(
                f"/admin/assessment/modules/{MOCK_DOMAIN_1_ID}",
                json={
                    "applies_to": "junior",
                    "mcq_count": 3,
                    "descriptive_count": 0,
                    "hands_on_enabled": False,
                    "hands_on_count": 0,
                    "hands_on_additional_minutes": 0,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            # Response should contain domain, config, preflight
            assert "domain" in data
            assert "config" in data
            assert "preflight" in data
            # Config must not contain sensitive fields
            config = data["config"]
            for sensitive in (
                "correct_option",
                "explanation",
                "expected_flag",
                "score",
                "is_correct",
                "verified",
            ):
                assert sensitive not in config
            # Preflight must not contain question IDs
            preflight = data["preflight"]
            for key in ("mcq_available", "descriptive_available", "hands_on_available"):
                assert isinstance(preflight[key], int)
        finally:
            _clear_auth()
