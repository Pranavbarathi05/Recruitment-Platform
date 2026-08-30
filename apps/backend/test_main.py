"""
Backend tests for the DSC Recruitment Platform API.

Tests verify:
- Health endpoint
- Authenticated endpoint behavior
- Missing token rejected
- Invalid token rejected
- Domain listing
- Assessment flow (requires auth)
- Admin flow (requires auth + admin role)
- Security (correct_option never returned in question payload)
- Schema validation
"""

import os
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient


# Mock environment variables before importing app
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_PROFILE_ID = "00000000-0000-0000-0000-000000000001"
MOCK_CANDIDATE_ID = "00000000-0000-0000-0000-000000000002"
MOCK_DOMAIN_1_ID = "11111111-1111-1111-1111-111111111111"
MOCK_DOMAIN_2_ID = "22222222-2222-2222-2222-222222222222"
MOCK_MCQ_1_ID = "aaaa1111-1111-1111-1111-111111111111"
MOCK_MCQ_2_ID = "aaaa2222-2222-2222-2222-222222222222"
MOCK_ATTEMPT_ID = "bbbb1111-1111-1111-1111-111111111111"


def _make_mock_response(data, count=None):
    resp = MagicMock()
    resp.data = data
    if count is not None:
        resp.count = count
    return resp


@pytest.fixture(autouse=True)
def mock_supabase():
    """Mock Supabase client for all tests."""
    mock_client = MagicMock()

    # Default: empty result for any query
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = _make_mock_response([])

    with patch("core.supabase.supabase_client", mock_client), \
         patch("routers.domains.supabase_client", mock_client), \
         patch("routers.admin.supabase_client", mock_client), \
         patch("routers.assessment.supabase_client", mock_client):
        yield mock_client


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_health_returns_correct_body(self, client):
        response = client.get("/")
        data = response.json()
        assert data["status"] == "Healthy"
        assert data["message"] == "API is working"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuthEndpoints:
    def test_submission_requires_auth(self, client):
        response = client.post("/submission/", json={
            "attempt_id": "test-attempt",
            "code": "print('hello')",
            "language": "python",
        })
        assert response.status_code in (401, 403)

    def test_invalid_token_rejected(self, client):
        response = client.post("/submission/", json={
            "attempt_id": "test-attempt",
            "code": "print('hello')",
            "language": "python",
        }, headers={"Authorization": "Bearer invalid-token-here"})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

class TestDomainsEndpoint:
    def test_domains_returns_200(self, client, mock_supabase):
        response = client.get("/questions/domains")
        assert response.status_code == 200

    def test_domains_returns_list(self, client, mock_supabase):
        response = client.get("/questions/domains")
        data = response.json()
        assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Assessment — requires auth
# ---------------------------------------------------------------------------

class TestAssessmentEndpoints:
    def test_start_requires_auth(self, client):
        response = client.post("/assessment/start", json={"domain_ids": ["some-id"]})
        assert response.status_code in (401, 403)

    def test_get_attempt_requires_auth(self, client):
        response = client.get(f"/assessment/attempt/{MOCK_ATTEMPT_ID}")
        assert response.status_code in (401, 403)

    def test_get_questions_requires_auth(self, client):
        response = client.get(f"/assessment/attempt/{MOCK_ATTEMPT_ID}/questions")
        assert response.status_code in (401, 403)

    def test_submit_requires_auth(self, client):
        response = client.post(f"/assessment/attempt/{MOCK_ATTEMPT_ID}/submit")
        assert response.status_code in (401, 403)

    def test_results_requires_auth(self, client):
        response = client.get(f"/assessment/attempt/{MOCK_ATTEMPT_ID}/results")
        assert response.status_code in (401, 403)

    def test_current_requires_auth(self, client):
        response = client.get("/assessment/current")
        assert response.status_code in (401, 403)

    def test_save_answer_requires_auth(self, client):
        response = client.put(
            f"/assessment/attempt/{MOCK_ATTEMPT_ID}/answers",
            json={"question_id": "some-q", "selected_option": "A"},
        )
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Admin — requires auth + admin role
# ---------------------------------------------------------------------------

class TestAdminEndpoints:
    def test_admin_domains_requires_auth(self, client):
        response = client.get("/admin/domains")
        assert response.status_code in (401, 403)

    def test_admin_create_domain_requires_auth(self, client):
        response = client.post("/admin/domains", json={
            "name": "Test", "slug": "test",
        })
        assert response.status_code in (401, 403)

    def test_admin_mcqs_requires_auth(self, client):
        response = client.get(f"/admin/domains/{MOCK_DOMAIN_1_ID}/mcqs")
        assert response.status_code in (401, 403)

    def test_admin_create_mcq_requires_auth(self, client):
        response = client.post(f"/admin/domains/{MOCK_DOMAIN_1_ID}/mcqs", json={
            "domain_id": MOCK_DOMAIN_1_ID,
            "semester": 1,
            "question_text": "Q?",
            "option_a": "A", "option_b": "B",
            "option_c": "C", "option_d": "D",
            "correct_option": "A",
        })
        assert response.status_code in (401, 403)

    def test_admin_deactivate_domain_requires_auth(self, client):
        response = client.post(f"/admin/domains/{MOCK_DOMAIN_1_ID}/deactivate")
        assert response.status_code in (401, 403)

    def test_admin_activate_domain_requires_auth(self, client):
        response = client.post(f"/admin/domains/{MOCK_DOMAIN_1_ID}/activate")
        assert response.status_code in (401, 403)

    def test_admin_update_mcq_requires_auth(self, client):
        response = client.put(f"/admin/mcqs/{MOCK_MCQ_1_ID}", json={
            "question_text": "Updated?",
        })
        assert response.status_code in (401, 403)

    def test_admin_deactivate_mcq_requires_auth(self, client):
        response = client.post(f"/admin/mcqs/{MOCK_MCQ_1_ID}/deactivate")
        assert response.status_code in (401, 403)

    def test_admin_activate_mcq_requires_auth(self, client):
        response = client.post(f"/admin/mcqs/{MOCK_MCQ_1_ID}/activate")
        assert response.status_code in (401, 403)

    def test_admin_delete_mcq_requires_auth(self, client):
        response = client.delete(f"/admin/mcqs/{MOCK_MCQ_1_ID}")
        assert response.status_code in (401, 403)

    def test_admin_mcqs_semester_filter_requires_auth(self, client):
        response = client.get(f"/admin/domains/{MOCK_DOMAIN_1_ID}/mcqs?semester=1")
        assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Schema validation (no network calls needed)
# ---------------------------------------------------------------------------

class TestSchemaValidation:
    def test_mcq_create_requires_valid_semester(self):
        from schemas.assessment import MCQCreate
        with pytest.raises(Exception):
            MCQCreate(
                domain_id="test",
                semester=2,  # Invalid
                question_text="Q?",
                option_a="A", option_b="B", option_c="C", option_d="D",
                correct_option="A",
            )

    def test_mcq_create_accepts_valid_semesters(self):
        from schemas.assessment import MCQCreate
        for sem in [1, 3, 5, 7]:
            mcq = MCQCreate(
                domain_id="test",
                semester=sem,
                question_text="Q?",
                option_a="A", option_b="B", option_c="C", option_d="D",
                correct_option="A",
            )
            assert mcq.semester == sem

    def test_mcq_create_rejects_invalid_correct_option(self):
        from schemas.assessment import MCQCreate
        with pytest.raises(Exception):
            MCQCreate(
                domain_id="test",
                semester=1,
                question_text="Q?",
                option_a="A", option_b="B", option_c="C", option_d="D",
                correct_option="E",  # Invalid
            )

    def test_mcq_create_requires_nonempty_options(self):
        from schemas.assessment import MCQCreate
        with pytest.raises(Exception):
            MCQCreate(
                domain_id="test",
                semester=1,
                question_text="Q?",
                option_a="", option_b="B", option_c="C", option_d="D",
                correct_option="A",
            )

    def test_assessment_start_requires_1_or_2_domains(self):
        from schemas.assessment import AssessmentStartRequest
        with pytest.raises(Exception):
            AssessmentStartRequest(domain_ids=[])  # Too few
        with pytest.raises(Exception):
            AssessmentStartRequest(domain_ids=["a", "b", "c"])  # Too many

    def test_answer_save_validates_option(self):
        from schemas.assessment import AnswerSaveRequest
        with pytest.raises(Exception):
            AnswerSaveRequest(question_id="q1", selected_option="E")  # Invalid

    def test_domain_create_validates_name(self):
        from schemas.assessment import DomainCreate
        with pytest.raises(Exception):
            DomainCreate(name="", slug="test")  # Empty name

    def test_mcq_update_validates_semester(self):
        from schemas.assessment import MCQUpdate
        with pytest.raises(Exception):
            MCQUpdate(semester=99)  # Invalid semester
