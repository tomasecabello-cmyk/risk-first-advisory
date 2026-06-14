"""
Integration tests for POST /advisor/override-approval — segundo acto formal
del asesor en Fase 1.

Cubre:
    - Auth: requiere Bearer válido (advisor o compliance) → 401 en otro caso.
    - Validación de candidate_variant, decision, rationale.
    - Validación de items vacíos en reason_codes / exceeded_constraints.
    - approve y reject ambos preservan reason_codes y exceeded_constraints.
    - Persistencia en SQLite y retrieval por ID.
    - Listado por client_id.
    - Manejo de fallo de persistencia → 500.
    - No regresión de /auth/me y /health.

No usa OpenAI. No escribe en data/demo_api.db (autouse fixture redirige
DEFAULT_DB_PATH a tmp_path).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module
import risk_first_advisory.config_layer.advisor_tokens as _advisor_tokens_module

_URL = "/advisor/override-approval"
_ADVISOR_TOKEN = "Bearer dev-advisor-token"
_COMPLIANCE_TOKEN = "Bearer dev-compliance-token"
_RBAC_403_DETAIL = "Advisor role is not authorized for this action."

_GROWTH_REASON_CODE = "PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_advisor_tokens_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Aísla tokens del entorno local; garantiza que los tests usen el fallback dev-only."""
    monkeypatch.delenv(_advisor_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _advisor_tokens_module,
        "DEFAULT_ADVISOR_TOKENS_PATH",
        tmp_path / "absent_default.yaml",
    )


@pytest.fixture(autouse=True)
def _redirect_db_to_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    db_path = tmp_path / "advisor_override_approval.db"
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


def _valid_approve_body(**overrides: Any) -> dict:
    """approve GROWTH con exceeded_constraints y reason_codes típicos."""
    base: dict = {
        "client_id":            "CLI-OVR-001",
        "related_record_id":    "ai_filtered_portfolio_000001",
        "candidate_variant":    "GROWTH",
        "decision":             "approve",
        "reason_codes":         [_GROWTH_REASON_CODE],
        "exceeded_constraints": ["max_volatility"],
        "rationale":            "Cliente acepta exceder vol max para alcanzar retorno objetivo.",
    }
    base.update(overrides)
    return base


def _valid_reject_body(**overrides: Any) -> dict:
    base: dict = {
        "client_id":            "CLI-OVR-002",
        "related_record_id":    "ai_filtered_portfolio_000002",
        "candidate_variant":    "GROWTH",
        "decision":             "reject",
        "reason_codes":         [_GROWTH_REASON_CODE],
        "exceeded_constraints": ["max_volatility"],
        "rationale":            "Cliente prefiere mantenerse dentro del RiskBudget aprobado.",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverrideApprovalAuth:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.post(_URL, json=_valid_approve_body())
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_malformed_auth_header_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": "Basic dev-advisor-token"},
        )
        assert resp.status_code == 401

    def test_bearer_without_token_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": "Bearer"},
        )
        assert resp.status_code == 401

    def test_compliance_token_returns_403(self, client: TestClient) -> None:
        """RBAC: compliance no puede ejecutar actos formales del asesor."""
        resp = client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-CMP-OVR"),
            headers={"Authorization": _COMPLIANCE_TOKEN},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_auth_failure_does_not_persist(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorOverrideApprovalRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(_URL, json=_valid_approve_body())
        assert resp.status_code == 401

        if not _redirect_db_to_tmp.exists():
            return
        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            approvals = SQLiteAdvisorOverrideApprovalRepository(store).list_approvals()
        assert approvals == []


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: approve GROWTH
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverrideApprovalApprove:
    def test_approve_growth_returns_200(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200

    def test_response_contains_advisor_id_ADV_001(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["advisor_id"] == "ADV-001"

    def test_response_contains_candidate_variant_growth(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["candidate_variant"] == "GROWTH"

    def test_response_contains_decision_approve(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["decision"] == "approve"

    def test_response_contains_exceeded_constraints_max_volatility(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["exceeded_constraints"] == ["max_volatility"]

    def test_response_contains_reason_codes(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["reason_codes"] == [_GROWTH_REASON_CODE]

    def test_response_status_recorded(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["status"] == "recorded"

    def test_response_contains_advisor_display_name(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["advisor_display_name"] == "Demo Advisor"

    def test_response_contains_created_at_utc(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        created = resp.json()["created_at_utc"]
        assert isinstance(created, str)
        assert created.endswith("Z")
        assert "T" in created

    def test_approve_growth_with_empty_lists_is_accepted(
        self, client: TestClient
    ) -> None:
        """Aceptamos approve sin reason_codes ni exceeded_constraints
        (decisión: menor complejidad, sin warning especial)."""
        resp = client.post(
            _URL,
            json=_valid_approve_body(reason_codes=[], exceeded_constraints=[]),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reason_codes"] == []
        assert data["exceeded_constraints"] == []

    def test_approve_balanced_variant_is_accepted(
        self, client: TestClient
    ) -> None:
        """BALANCED y DEFENSIVE normalmente no exceden budget, pero el endpoint
        no rechaza la combinación — registra la decisión declarada."""
        resp = client.post(
            _URL,
            json=_valid_approve_body(
                candidate_variant="BALANCED",
                reason_codes=[],
                exceeded_constraints=[],
            ),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["candidate_variant"] == "BALANCED"


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: reject
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverrideApprovalReject:
    def test_reject_growth_returns_200(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200

    def test_reject_preserves_reason_codes(self, client: TestClient) -> None:
        """reject NO borra reason_codes — se preservan para trazabilidad."""
        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["reason_codes"] == [_GROWTH_REASON_CODE]

    def test_reject_preserves_exceeded_constraints(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["exceeded_constraints"] == ["max_volatility"]

    def test_reject_decision_propagated(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["decision"] == "reject"


# ─────────────────────────────────────────────────────────────────────────────
# Validation errors
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverrideApprovalValidation:
    def test_candidate_variant_invalid_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(candidate_variant="ULTRA_GROWTH"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_candidate_variant_lowercase_returns_422(
        self, client: TestClient
    ) -> None:
        """Las variantes son MAYUSCULAS estrictas — no se normaliza."""
        resp = client.post(
            _URL,
            json=_valid_approve_body(candidate_variant="growth"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_candidate_variant_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(candidate_variant=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_decision_invalid_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(decision="approve_with_modifications"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_decision_modify_returns_422(self, client: TestClient) -> None:
        """Solo approve/reject — no existe modify para override."""
        resp = client.post(
            _URL,
            json=_valid_approve_body(decision="modify"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_rationale_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(rationale=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_rationale_whitespace_only_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(rationale="    "),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_reason_codes_with_empty_item_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(reason_codes=[_GROWTH_REASON_CODE, ""]),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_reason_codes_with_whitespace_item_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(reason_codes=["   "]),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_exceeded_constraints_with_empty_item_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(exceeded_constraints=["max_volatility", ""]),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_exceeded_constraints_with_whitespace_item_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(exceeded_constraints=["    "]),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_client_id_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(client_id=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverrideApprovalPersistence:
    def test_record_id_prefix(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["record_id"].startswith("advisor_override_approval_")

    def test_record_id_is_json_serializable(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        serialised = json.dumps(resp.json())
        reloaded = json.loads(serialised)
        assert reloaded["record_id"] == resp.json()["record_id"]

    def test_persisted_record_retrievable(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorOverrideApprovalRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        record_id = resp.json()["record_id"]

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            repo = SQLiteAdvisorOverrideApprovalRepository(store)
            record = repo.get_approval(record_id)

        assert record.record_id == record_id
        assert record.record_type == "advisor_override_approval"
        assert record.metadata["client_id"] == "CLI-OVR-001"
        assert record.metadata["advisor_id"] == "ADV-001"
        assert record.metadata["decision"] == "approve"
        assert record.metadata["candidate_variant"] == "GROWTH"
        assert record.metadata["related_record_id"] == "ai_filtered_portfolio_000001"
        assert record.metadata["endpoint"] == "/advisor/override-approval"
        # Payload also contains decision details.
        assert record.payload["rationale"].startswith("Cliente acepta")
        assert record.payload["reason_codes"] == [_GROWTH_REASON_CODE]
        assert record.payload["exceeded_constraints"] == ["max_volatility"]

    def test_listing_filters_by_client_id(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorOverrideApprovalRepository,
            SQLitePersistenceStore,
        )

        client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-LIST-X"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        client.post(
            _URL,
            json=_valid_reject_body(client_id="CLI-LIST-X"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-LIST-Y"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            repo = SQLiteAdvisorOverrideApprovalRepository(store)
            all_records = repo.list_approvals()
            only_x = repo.list_approvals(client_id="CLI-LIST-X")
            only_y = repo.list_approvals(client_id="CLI-LIST-Y")

        assert len(all_records) == 3
        assert len(only_x) == 2
        assert len(only_y) == 1
        # CLI-LIST-X has both approve and reject in insertion order.
        decisions_x = [r.metadata["decision"] for r in only_x]
        assert decisions_x == ["approve", "reject"]

    def test_reject_persists_reason_codes_in_payload(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorOverrideApprovalRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        record_id = resp.json()["record_id"]

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            record = SQLiteAdvisorOverrideApprovalRepository(store).get_approval(
                record_id
            )
        assert record.payload["decision"] == "reject"
        # reject MUST preserve why the override was raised in the first place.
        assert record.payload["reason_codes"] == [_GROWTH_REASON_CODE]
        assert record.payload["exceeded_constraints"] == ["max_volatility"]

    def test_persistence_failure_returns_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**_kwargs):
            raise RuntimeError("simulated SQLite failure")

        monkeypatch.setattr(
            _main_module,
            "_persist_advisor_override_approval",
            _boom,
        )

        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 500
        assert "persistence" in resp.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Optional fields
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverrideApprovalOptionalFields:
    def test_source_defaults_to_manual(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["source"] == "manual"

    def test_custom_source_propagated(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(source="frontend_button"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["source"] == "frontend_button"

    def test_related_record_id_can_be_null(self, client: TestClient) -> None:
        body = _valid_approve_body()
        body["related_record_id"] = None
        resp = client.post(
            _URL,
            json=body,
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["related_record_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# No regresión: /auth/me y /health siguen funcionando
# ─────────────────────────────────────────────────────────────────────────────


class TestExistingEndpointsUnaffected:
    def test_auth_me_still_works(self, client: TestClient) -> None:
        resp = client.get(
            "/auth/me",
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["advisor_id"] == "ADV-001"

    def test_health_still_works_without_token(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# RBAC — roles y roles insuficientes
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorOverrideApprovalRBAC:
    """
    Verifica la frontera RBAC de /advisor/override-approval:
        - compliance → 403 (también cubierto en TestAdvisorOverrideApprovalAuth).
        - viewer (vía YAML custom) → 403.
        - admin (vía YAML custom) → 200.
        - sin token → 401, no 403.
    """

    def test_viewer_token_returns_403(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        client: TestClient,
    ) -> None:
        viewer_yaml = tmp_path / "viewer_tokens.yaml"
        viewer_yaml.write_text(
            "tokens:\n"
            "  dev-viewer-token:\n"
            "    advisor_id: VWR-001\n"
            "    display_name: Dev Viewer\n"
            "    firm_id: null\n"
            "    roles:\n"
            "      - viewer\n",
            encoding="utf-8",
        )
        monkeypatch.setenv(
            _advisor_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(viewer_yaml)
        )
        resp = client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-VWR-OVR"),
            headers={"Authorization": "Bearer dev-viewer-token"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_admin_token_returns_200(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        client: TestClient,
    ) -> None:
        admin_yaml = tmp_path / "admin_tokens.yaml"
        admin_yaml.write_text(
            "tokens:\n"
            "  dev-admin-token:\n"
            "    advisor_id: ADM-001\n"
            "    display_name: Dev Admin\n"
            "    firm_id: null\n"
            "    roles:\n"
            "      - admin\n",
            encoding="utf-8",
        )
        monkeypatch.setenv(
            _advisor_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(admin_yaml)
        )
        resp = client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-ADM-OVR"),
            headers={"Authorization": "Bearer dev-admin-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["advisor_id"] == "ADM-001"

    def test_403_does_not_echo_token(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-LEAK-OVR"),
            headers={"Authorization": "Bearer dev-compliance-token"},
        )
        assert resp.status_code == 403
        assert "dev-compliance-token" not in resp.text
        for hv in resp.headers.values():
            assert "dev-compliance-token" not in hv

    def test_no_token_returns_401_not_403(self, client: TestClient) -> None:
        resp = client.post(_URL, json=_valid_approve_body())
        assert resp.status_code == 401
