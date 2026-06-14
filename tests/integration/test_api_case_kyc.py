"""
Integration tests for Phase 2 KYCSubmission endpoints (case-scoped, versioned).

Cubre:
    POST /cases/{case_id}/kyc   — advisor/admin crea submission; advisor entity
                                  como submitted_by_advisor_id; status DRAFT →
                                  IN_PROGRESS; AuditEvent kyc_submitted; 409 si
                                  CLOSED; 404 si case no existe; 422 validaciones.
    GET  /cases/{case_id}/kyc   — listado ordenado por version asc.

Persistencia:
    - Migrations 0001 + 0002 corridas en DB temporal.
    - payload_hash = sha256(canonical JSON).
    - current_kyc_submission_id del case se actualiza al último.
    - FK enforcement: case inexistente → EntityNotFoundError en repo directo.

No usa OpenAI. No escribe en data/demo_api.db.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module
import risk_first_advisory.config_layer.advisor_tokens as _tokens_module
from risk_first_advisory.persistence_layer.entity_repository import (
    EntityNotFoundError,
    SQLiteAdvisoryCaseRepository,
    SQLiteEntityStore,
    SQLiteKYCSubmissionRepository,
)

# ─────────────────────────────────────────────────────────────────────────────
# migrate import
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
# Tokens
# ─────────────────────────────────────────────────────────────────────────────

_KYC_TEST_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-KYC-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-KYC-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-KYC-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-KYC-001
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
def _setup_kyc_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "kyc_tokens.yaml"
    tokens_yaml.write_text(_KYC_TEST_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def kyc_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "kyc_test.db"
    # Aplica 0001 + 0002 (incluye kyc_submissions).
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "KYC Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "display_name": "KYC Advisor",
        "email": "a@kyc.com",
        "roles": ["advisor"],
        **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "primary_advisor_id": advisor_id,
        "display_name": "KYC Client",
        **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "lead_advisor_id": advisor_id,
        "title": "KYC Case",
        **kw,
    }


def _kyc_body(**overrides) -> dict:
    """KYCDataRequest body válido."""
    base = {
        "age": 42,
        "risk_tolerance_score": 6,
        "risk_capacity_score": 7,
        "liquidity_need_score": 3,
        "investment_horizon_years": 10,
        "investment_experience": "moderada",
        "income_stability": "stable",
        "net_worth": 500_000.0,
        "liquid_net_worth": 150_000.0,
        "max_acceptable_drawdown_pct": 20.0,
        "jurisdiction": "AR",
        "preferred_currency": "USD",
        "investment_objective": "balanced",
    }
    base.update(overrides)
    return base


def _create_firm(c: TestClient, **kw: Any) -> dict:
    r = c.post("/firms", json=_firm_body(**kw), headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_advisor(c: TestClient, firm_id: str, **kw: Any) -> dict:
    r = c.post(
        "/advisors",
        json=_advisor_body(firm_id, **kw),
        headers={"Authorization": _ADMIN},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_client(c: TestClient, firm_id: str, advisor_id: str, **kw: Any) -> dict:
    r = c.post(
        "/clients",
        json=_client_body(firm_id, advisor_id, **kw),
        headers={"Authorization": _ADMIN},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_case(c: TestClient, firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    r = c.post(
        "/cases",
        json=_case_body(firm_id, client_id, advisor_id, **kw),
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _full_chain(c: TestClient) -> dict:
    """Crea firm + advisor (advisor_id=ADV-KYC-001 para que coincida con el token)
    + client + case y devuelve el case dict."""
    firm = _create_firm(c)
    adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-KYC-001")
    cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
    case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    return case


def _post_kyc(c: TestClient, case_id: str, **overrides) -> Any:
    return c.post(
        f"/cases/{case_id}/kyc",
        json=_kyc_body(**overrides),
        headers={"Authorization": _ADVISOR},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: create / list
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateAndList:
    def test_first_submission_returns_201(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        assert r.status_code == 201, r.text

    def test_submission_id_prefix(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        assert r.json()["kyc_submission_id"].startswith("kyc_submission_")

    def test_case_id_in_response(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        assert r.json()["case_id"] == case["case_id"]

    def test_first_submission_version_1(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        assert r.json()["version"] == 1

    def test_payload_round_trip_age(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"], age=65)
        assert r.json()["payload"]["age"] == 65

    def test_payload_round_trip_jurisdiction_currency(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = _post_kyc(
            client, case["case_id"], jurisdiction="US", preferred_currency="EUR"
        )
        body = r.json()
        assert body["payload"]["jurisdiction"] == "US"
        assert body["payload"]["preferred_currency"] == "EUR"

    def test_payload_hash_not_empty(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        assert r.json()["payload_hash"]
        assert len(r.json()["payload_hash"]) == 64  # sha256 hex

    def test_created_at_utc_not_empty(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        assert r.json()["created_at_utc"]
        assert r.json()["created_at_utc"].endswith("Z")

    def test_submitted_by_advisor_id_resolves_to_entity(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        # ADV-KYC-001 fue registrado como entity en _full_chain.
        assert r.json()["submitted_by_advisor_id"] == "ADV-KYC-001"

    def test_get_after_create_returns_one(self, client: TestClient) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])
        r = client.get(
            f"/cases/{case['case_id']}/kyc",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_second_submission_creates_version_2(self, client: TestClient) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])
        r = _post_kyc(client, case["case_id"], age=50)
        assert r.json()["version"] == 2

    def test_get_lists_versions_in_order(self, client: TestClient) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])
        _post_kyc(client, case["case_id"], age=45)
        _post_kyc(client, case["case_id"], age=50)
        r = client.get(
            f"/cases/{case['case_id']}/kyc",
            headers={"Authorization": _COMPLIANCE},
        )
        body = r.json()
        assert body["count"] == 3
        versions = [s["version"] for s in body["submissions"]]
        assert versions == [1, 2, 3]


# ─────────────────────────────────────────────────────────────────────────────
# Case state side-effects
# ─────────────────────────────────────────────────────────────────────────────


class TestCaseStateSideEffects:
    def test_current_kyc_submission_id_set_after_post(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        submission_id = r.json()["kyc_submission_id"]
        case_after = client.get(
            f"/cases/{case['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["current_kyc_submission_id"] == submission_id

    def test_current_kyc_points_to_latest_after_second(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])
        r2 = _post_kyc(client, case["case_id"], age=55)
        second_id = r2.json()["kyc_submission_id"]
        case_after = client.get(
            f"/cases/{case['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["current_kyc_submission_id"] == second_id

    def test_status_draft_transitions_to_in_progress(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        assert case["status"] == "DRAFT"
        _post_kyc(client, case["case_id"])
        case_after = client.get(
            f"/cases/{case['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["status"] == "IN_PROGRESS"

    def test_status_remains_in_progress_on_second_kyc(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])  # → IN_PROGRESS
        _post_kyc(client, case["case_id"], age=55)  # stays IN_PROGRESS
        case_after = client.get(
            f"/cases/{case['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["status"] == "IN_PROGRESS"

    def test_closed_case_rejects_kyc_with_409(self, client: TestClient) -> None:
        case = _full_chain(client)
        # Llevar a CLOSED: DRAFT → IN_PROGRESS → PORTFOLIO_SELECTED → CLOSED.
        client.patch(
            f"/cases/{case['case_id']}/status",
            json={"status": "IN_PROGRESS"},
            headers={"Authorization": _ADVISOR},
        )
        client.patch(
            f"/cases/{case['case_id']}/status",
            json={"status": "PORTFOLIO_SELECTED"},
            headers={"Authorization": _ADVISOR},
        )
        client.patch(
            f"/cases/{case['case_id']}/status",
            json={"status": "CLOSED"},
            headers={"Authorization": _ADVISOR},
        )
        r = _post_kyc(client, case["case_id"])
        assert r.status_code == 409
        assert "CLOSED" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# AuditEvent integration
# ─────────────────────────────────────────────────────────────────────────────


class TestAuditEventIntegration:
    def test_audit_chain_has_case_created_and_kyc_submitted(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])
        events = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        # case_created (Commit 6) + kyc_submitted (Commit 8). El PATCH de
        # status DRAFT→IN_PROGRESS NO genera audit todavía (item 8 del pending).
        assert "case_created" in types
        assert "kyc_submitted" in types

    def test_kyc_submitted_event_payload_has_metadata(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        sub = r.json()
        events = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        kyc_evt = next(e for e in events if e["event_type"] == "kyc_submitted")
        payload = kyc_evt["payload"]
        assert payload["case_id"] == case["case_id"]
        assert payload["kyc_submission_id"] == sub["kyc_submission_id"]
        assert payload["version"] == sub["version"]
        assert payload["payload_hash"] == sub["payload_hash"]

    def test_kyc_submitted_event_actor_advisor_id(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])
        events = client.get(
            f"/cases/{case['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        kyc_evt = next(e for e in events if e["event_type"] == "kyc_submitted")
        # ADV-KYC-001 está registrado como entity → debe propagarse.
        assert kyc_evt["actor_advisor_id"] == "ADV-KYC-001"
        assert kyc_evt["actor_role"] == "advisor"

    def test_audit_chain_still_intact_after_kyc(self, client: TestClient) -> None:
        case = _full_chain(client)
        _post_kyc(client, case["case_id"])
        _post_kyc(client, case["case_id"], age=45)
        r = client.get(
            f"/cases/{case['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200
        assert r.json()["is_intact"] is True


# ─────────────────────────────────────────────────────────────────────────────
# RBAC
# ─────────────────────────────────────────────────────────────────────────────


class TestRBACPost:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/kyc", json=_kyc_body()
        )
        assert r.status_code == 401

    def test_compliance_returns_403(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/kyc",
            json=_kyc_body(),
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403
        assert r.json()["detail"] == _RBAC_403_DETAIL

    def test_viewer_returns_403(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            f"/cases/{case['case_id']}/kyc",
            json=_kyc_body(),
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_returns_201(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"])
        assert r.status_code == 201

    def test_admin_returns_201(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"], advisor_id="ADV-KYC-001")
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        r = client.post(
            f"/cases/{case['case_id']}/kyc",
            json=_kyc_body(),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACGet:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(f"/cases/{case['case_id']}/kyc")
        assert r.status_code == 401

    def test_compliance_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/kyc",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_viewer_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/kyc",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200

    def test_advisor_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/kyc",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200

    def test_admin_returns_200(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/kyc",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_case_post_returns_404(self, client: TestClient) -> None:
        r = client.post(
            "/cases/case_nope/kyc",
            json=_kyc_body(),
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_missing_case_get_returns_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/kyc",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404

    def test_age_below_18_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"], age=10)
        assert r.status_code == 422

    def test_annual_income_negative_returns_422(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"], annual_income_usd=-100.0)
        assert r.status_code == 422

    def test_jurisdiction_empty_returns_422(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"], jurisdiction=" ")
        assert r.status_code == 422

    def test_preferred_currency_empty_returns_422(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"], preferred_currency=" ")
        assert r.status_code == 422

    def test_investment_objective_invalid_returns_422(
        self, client: TestClient
    ) -> None:
        case = _full_chain(client)
        r = _post_kyc(client, case["case_id"], investment_objective="not_valid")
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Persistence (repo direct + payload_hash determinism)
# ─────────────────────────────────────────────────────────────────────────────


class TestPersistence:
    def test_payload_hash_is_sha256_canonical(self, client: TestClient) -> None:
        case = _full_chain(client)
        body = _kyc_body(age=33)
        r = client.post(
            f"/cases/{case['case_id']}/kyc",
            json=body,
            headers={"Authorization": _ADVISOR},
        )
        sub = r.json()
        # El payload persistido es el model_dump() de KYCDataRequest, que
        # incluye defaults. Lo recuperamos del response para recomputar.
        canonical = json.dumps(
            sub["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert sub["payload_hash"] == expected

    def test_repo_direct_with_missing_case_raises(
        self, kyc_db: Path
    ) -> None:
        with SQLiteEntityStore(kyc_db) as store:
            repo = SQLiteKYCSubmissionRepository(store)
            with pytest.raises(EntityNotFoundError) as exc_info:
                repo.create(case_id="case_nope", payload={"k": "v"})
            assert "Case not found" in str(exc_info.value)

    def test_repo_direct_returns_dict_with_version(
        self, client: TestClient, kyc_db: Path
    ) -> None:
        # Crear case via API, luego usar repo directo.
        case = _full_chain(client)
        with SQLiteEntityStore(kyc_db) as store:
            repo = SQLiteKYCSubmissionRepository(store)
            data = repo.create(
                case_id=case["case_id"],
                payload={"some": "thing"},
            )
            assert data["version"] == 1
            assert data["kyc_submission_id"].startswith("kyc_submission_")

    def test_advisory_case_repo_update_current_kyc(
        self, client: TestClient, kyc_db: Path
    ) -> None:
        case = _full_chain(client)
        with SQLiteEntityStore(kyc_db) as store:
            case_repo = SQLiteAdvisoryCaseRepository(store)
            updated = case_repo.update_current_kyc_submission(
                case["case_id"], "kyc_submission_FAKE"
            )
            assert updated["current_kyc_submission_id"] == "kyc_submission_FAKE"


# ─────────────────────────────────────────────────────────────────────────────
# No regression
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRegression:
    def test_health_no_auth(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200

    def test_auth_me_works(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert r.status_code == 200
        assert r.json()["advisor_id"] == "ADV-KYC-001"

    def test_advisor_profile_approval_works(self, client: TestClient) -> None:
        r = client.post(
            "/advisor/profile-approval",
            json={
                "client_id": "C-X",
                "proposed_profile": "moderado",
                "decision": "approve",
                "rationale": "ok",
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code != 401
        assert r.status_code != 404
