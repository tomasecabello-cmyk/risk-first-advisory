"""
Integration tests for Phase 2 AdvisoryCase endpoints.

Cubre:
    POST /cases                       — advisor/admin crea caso; validaciones de negocio.
    GET  /cases                       — listado; cualquier token válido.
    GET  /cases/{case_id}             — detalle; 404.
    PATCH /cases/{case_id}/status     — transiciones de estado; 409 en transición inválida.
    GET  /clients/{client_id}/cases   — filtrado por cliente; 404 si cliente no existe.
    GET  /advisors/{advisor_id}/cases — filtrado por advisor; 404 si advisor no existe.
    GET  /firms/{firm_id}/cases       — filtrado por firma; 404 si firma no existe.

No usa OpenAI. No escribe en data/demo_api.db.
La migración 0001 se aplica a la DB temporal antes de cada test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module
import risk_first_advisory.config_layer.advisor_tokens as _tokens_module


# ─────────────────────────────────────────────────────────────────────────────
# Import migrate module (no package — importlib)
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _PROJECT_ROOT / "migrations"
_MIGRATE_PATH = _PROJECT_ROOT / "scripts" / "migrate.py"

_spec = importlib.util.spec_from_file_location("rfa_migrate", _MIGRATE_PATH)
_migrate_module = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules.setdefault("rfa_migrate", _migrate_module)
_spec.loader.exec_module(_migrate_module)  # type: ignore[union-attr]
migrate = _migrate_module


# ─────────────────────────────────────────────────────────────────────────────
# Test tokens — 4 roles
# ─────────────────────────────────────────────────────────────────────────────

_CASE_TEST_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-CASE-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-CASE-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-CASE-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-CASE-001
    display_name: Test Viewer
    firm_id: null
    roles:
      - viewer
"""

_ADMIN = "Bearer test-admin-token"
_ADVISOR = "Bearer test-advisor-token"
_COMPLIANCE = "Bearer test-compliance-token"
_VIEWER = "Bearer test-viewer-token"
_RBAC_403_DETAIL = "Advisor role is not authorized for this action."


# ─────────────────────────────────────────────────────────────────────────────
# Autouse fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_case_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "case_tokens.yaml"
    tokens_yaml.write_text(_CASE_TEST_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def case_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "case_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Payload builders
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "Test Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "display_name": "Test Advisor", "email": "a@f.com", "roles": ["advisor"], **kw}


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "primary_advisor_id": advisor_id, "display_name": "Test Client", **kw}


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "lead_advisor_id": advisor_id,
        "title": "Test Case",
        **kw,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — create full entity chain
# ─────────────────────────────────────────────────────────────────────────────


def _create_firm(client: TestClient, **kw: Any) -> dict:
    r = client.post("/firms", json=_firm_body(**kw), headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_advisor(client: TestClient, firm_id: str, **kw: Any) -> dict:
    r = client.post("/advisors", json=_advisor_body(firm_id, **kw), headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_client(client: TestClient, firm_id: str, advisor_id: str, **kw: Any) -> dict:
    r = client.post("/clients", json=_client_body(firm_id, advisor_id, **kw), headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_case(client: TestClient, firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    r = client.post(
        "/cases",
        json=_case_body(firm_id, client_id, advisor_id, **kw),
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _full_chain(client: TestClient) -> tuple[dict, dict, dict]:
    """Returns (firm, advisor, cli) with all three entities created."""
    firm = _create_firm(client)
    adv = _create_advisor(client, firm["firm_id"])
    cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
    return firm, adv, cli


# ─────────────────────────────────────────────────────────────────────────────
# POST /cases — RBAC
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateCaseRBAC:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post("/cases", json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"]))
        assert resp.status_code == 401

    def test_compliance_returns_403(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"]),
            headers={"Authorization": _COMPLIANCE},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_viewer_returns_403(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"]),
            headers={"Authorization": _VIEWER},
        )
        assert resp.status_code == 403

    def test_advisor_returns_201(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"]),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 201

    def test_admin_returns_201(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert resp.status_code == 201


# ─────────────────────────────────────────────────────────────────────────────
# POST /cases — shape and defaults
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateCaseShape:
    def test_response_has_expected_keys(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        assert set(case.keys()) == {
            "case_id", "firm_id", "client_id", "lead_advisor_id",
            "status", "title",
            "current_kyc_submission_id", "current_approved_profile_id",
            "current_portfolio_selection_id",
            "created_at_utc", "closed_at_utc",
        }

    def test_case_id_starts_with_case_prefix(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        assert case["case_id"].startswith("case_")

    def test_default_status_is_draft(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        assert case["status"] == "DRAFT"

    def test_current_fields_are_none(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        assert case["current_kyc_submission_id"] is None
        assert case["current_approved_profile_id"] is None
        assert case["current_portfolio_selection_id"] is None

    def test_closed_at_utc_is_none_on_create(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        assert case["closed_at_utc"] is None

    def test_created_at_utc_is_nonempty(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        assert case["created_at_utc"]

    def test_title_propagated(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"], title="My Advisory Case")
        assert case["title"] == "My Advisory Case"

    def test_explicit_status_in_progress_allowed(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"], status="IN_PROGRESS")
        assert case["status"] == "IN_PROGRESS"

    def test_explicit_case_id_is_stored(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"], case_id="case_CUSTOM")
        assert case["case_id"] == "case_CUSTOM"


# ─────────────────────────────────────────────────────────────────────────────
# POST /cases — business validations
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateCaseValidation:
    def test_title_empty_returns_422(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"], title=""),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_title_whitespace_returns_422(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"], title="   "),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_firm_not_found_returns_422(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body("firm_GHOST", cli["client_id"], adv["advisor_id"]),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_client_not_found_returns_422(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], "client_GHOST", adv["advisor_id"]),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_advisor_not_found_returns_422(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], "advisor_GHOST"),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_client_cross_firm_returns_422(self, client: TestClient) -> None:
        firm_a = _create_firm(client, display_name="Firm A")
        firm_b = _create_firm(client, display_name="Firm B")
        adv_a = _create_advisor(client, firm_a["firm_id"])
        adv_b = _create_advisor(client, firm_b["firm_id"], email="b@f.com")
        cli_b = _create_client(client, firm_b["firm_id"], adv_b["advisor_id"])
        # firm_a + client from firm_b → mismatch
        resp = client.post(
            "/cases",
            json=_case_body(firm_a["firm_id"], cli_b["client_id"], adv_a["advisor_id"]),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_advisor_cross_firm_returns_422(self, client: TestClient) -> None:
        firm_a = _create_firm(client, display_name="Firm A")
        firm_b = _create_firm(client, display_name="Firm B")
        adv_a = _create_advisor(client, firm_a["firm_id"])
        adv_b = _create_advisor(client, firm_b["firm_id"], email="b@f.com")
        cli_a = _create_client(client, firm_a["firm_id"], adv_a["advisor_id"])
        # firm_a + client from firm_a, but advisor from firm_b → mismatch
        resp = client.post(
            "/cases",
            json=_case_body(firm_a["firm_id"], cli_a["client_id"], adv_b["advisor_id"]),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_invalid_status_returns_422(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        resp = client.post(
            "/cases",
            json=_case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"], status="PENDING"),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 422

    def test_duplicate_case_id_returns_409(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        body = _case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"], case_id="case_DUPE")
        client.post("/cases", json=body, headers={"Authorization": _ADVISOR})
        resp = client.post("/cases", json=body, headers={"Authorization": _ADVISOR})
        assert resp.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# GET /cases, GET /cases/{case_id}
# ─────────────────────────────────────────────────────────────────────────────


class TestGetListCase:
    def test_list_cases_empty_initially(self, client: TestClient) -> None:
        resp = client.get("/cases", headers={"Authorization": _COMPLIANCE})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["cases"] == []

    def test_list_cases_includes_created(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = client.get("/cases", headers={"Authorization": _VIEWER})
        body = resp.json()
        assert body["count"] == 1
        assert body["cases"][0]["case_id"] == case["case_id"]

    def test_get_case_by_id_returns_200(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = client.get(f"/cases/{case['case_id']}", headers={"Authorization": _COMPLIANCE})
        assert resp.status_code == 200
        assert resp.json()["case_id"] == case["case_id"]

    def test_get_case_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/cases/case_GHOST", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_list_cases_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.get("/cases")
        assert resp.status_code == 401

    def test_get_client_cases_returns_case(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = client.get(
            f"/clients/{cli['client_id']}/cases", headers={"Authorization": _VIEWER}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["cases"][0]["case_id"] == case["case_id"]

    def test_get_client_cases_client_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/clients/client_GHOST/cases", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_get_advisor_cases_returns_case(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = client.get(
            f"/advisors/{adv['advisor_id']}/cases", headers={"Authorization": _COMPLIANCE}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["cases"][0]["case_id"] == case["case_id"]

    def test_get_advisor_cases_advisor_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/advisors/advisor_GHOST/cases", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_get_firm_cases_returns_case(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = client.get(
            f"/firms/{firm['firm_id']}/cases", headers={"Authorization": _ADVISOR}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["cases"][0]["case_id"] == case["case_id"]

    def test_get_firm_cases_firm_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/firms/firm_GHOST/cases", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_client_cases_filters_by_client(self, client: TestClient) -> None:
        """Two clients — GET /clients/{id}/cases returns only that client's cases."""
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        cli_1 = _create_client(client, firm["firm_id"], adv["advisor_id"], display_name="Cli 1")
        cli_2 = _create_client(client, firm["firm_id"], adv["advisor_id"], display_name="Cli 2")
        case_1 = _create_case(client, firm["firm_id"], cli_1["client_id"], adv["advisor_id"], title="Case 1")
        _create_case(client, firm["firm_id"], cli_2["client_id"], adv["advisor_id"], title="Case 2")

        resp = client.get(
            f"/clients/{cli_1['client_id']}/cases", headers={"Authorization": _ADVISOR}
        )
        body = resp.json()
        assert body["count"] == 1
        assert body["cases"][0]["case_id"] == case_1["case_id"]


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /cases/{case_id}/status — state transitions
# ─────────────────────────────────────────────────────────────────────────────


class TestPatchCaseStatus:
    def _patch(self, client: TestClient, case_id: str, status: str, token: str = _ADVISOR) -> Any:
        return client.patch(
            f"/cases/{case_id}/status",
            json={"status": status},
            headers={"Authorization": token},
        )

    def test_draft_to_in_progress_returns_200(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = self._patch(client, case["case_id"], "IN_PROGRESS")
        assert resp.status_code == 200
        assert resp.json()["status"] == "IN_PROGRESS"

    def test_in_progress_to_portfolio_selected_returns_200(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        self._patch(client, case["case_id"], "IN_PROGRESS")
        resp = self._patch(client, case["case_id"], "PORTFOLIO_SELECTED")
        assert resp.status_code == 200
        assert resp.json()["status"] == "PORTFOLIO_SELECTED"

    def test_portfolio_selected_to_closed_sets_closed_at_utc(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        self._patch(client, case["case_id"], "IN_PROGRESS")
        self._patch(client, case["case_id"], "PORTFOLIO_SELECTED")
        resp = self._patch(client, case["case_id"], "CLOSED")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "CLOSED"
        assert body["closed_at_utc"] is not None

    def test_closed_to_in_progress_returns_409(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        self._patch(client, case["case_id"], "IN_PROGRESS")
        self._patch(client, case["case_id"], "PORTFOLIO_SELECTED")
        self._patch(client, case["case_id"], "CLOSED")
        resp = self._patch(client, case["case_id"], "IN_PROGRESS")
        assert resp.status_code == 409

    def test_skip_transition_returns_409(self, client: TestClient) -> None:
        """DRAFT → PORTFOLIO_SELECTED is not a valid single step."""
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = self._patch(client, case["case_id"], "PORTFOLIO_SELECTED")
        assert resp.status_code == 409

    def test_invalid_status_value_returns_422(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = self._patch(client, case["case_id"], "PENDING")
        assert resp.status_code == 422

    def test_case_not_found_returns_404(self, client: TestClient) -> None:
        resp = self._patch(client, "case_GHOST", "IN_PROGRESS")
        assert resp.status_code == 404

    def test_compliance_token_returns_403(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = self._patch(client, case["case_id"], "IN_PROGRESS", token=_COMPLIANCE)
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_viewer_token_returns_403(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = self._patch(client, case["case_id"], "IN_PROGRESS", token=_VIEWER)
        assert resp.status_code == 403

    def test_admin_can_patch_status(self, client: TestClient) -> None:
        firm, adv, cli = _full_chain(client)
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        resp = self._patch(client, case["case_id"], "IN_PROGRESS", token=_ADMIN)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# No-regression: existing endpoints unaffected
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRegression:
    def test_health_still_works_without_token(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_auth_me_still_works_with_advisor_token(self, client: TestClient) -> None:
        resp = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert resp.status_code == 200
        assert "advisor" in resp.json()["roles"]

    def test_advisor_profile_approval_still_works(self, client: TestClient) -> None:
        """Legacy endpoint continues to work — uses advisor token from custom YAML."""
        body = {
            "client_id": "CLI-REG-001",
            "proposed_profile": "moderado",
            "decision": "approve",
            "rationale": "Perfil coherente con KYC.",
        }
        resp = client.post(
            "/advisor/profile-approval",
            json=body,
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 200

    def test_get_cases_with_compliance_token_returns_200(self, client: TestClient) -> None:
        resp = client.get("/cases", headers={"Authorization": _COMPLIANCE})
        assert resp.status_code == 200

    def test_get_cases_with_viewer_token_returns_200(self, client: TestClient) -> None:
        resp = client.get("/cases", headers={"Authorization": _VIEWER})
        assert resp.status_code == 200
