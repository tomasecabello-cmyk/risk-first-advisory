"""
Integration tests for POST /advisor/profile-approval — primer acto formal del
asesor en Fase 1.

Cubre:
    - Auth: requiere Bearer válido (advisor o compliance) → 401 en otro caso.
    - Validación cruzada de decision/approved_profile.
    - Persistencia en SQLite y retrieval por ID.
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


_URL = "/advisor/profile-approval"
_ADVISOR_TOKEN = "Bearer dev-advisor-token"
_COMPLIANCE_TOKEN = "Bearer dev-compliance-token"
_RBAC_403_DETAIL = "Advisor role is not authorized for this action."


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_advisor_tokens_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Aísla cada test del entorno local:
        - Elimina ADVISOR_TOKENS_FILE si está set.
        - Apunta DEFAULT_ADVISOR_TOKENS_PATH a una ruta inexistente.

    Garantiza que los tests del fallback usen el fallback dev-only y NO se
    contaminen si el dev tiene `config/advisor_tokens.yaml` localmente.
    Tests de RBAC con YAML custom re-setean el env var después de este fixture.
    """
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
    """Redirige DEFAULT_DB_PATH a tmp_path para todos los tests del archivo."""
    db_path = tmp_path / "advisor_profile_approval.db"
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


def _valid_approve_body(**overrides: Any) -> dict:
    base: dict = {
        "client_id":        "CLI-APP-001",
        "proposed_profile": "moderado",
        "decision":         "approve",
        "rationale":        "Perfil consistente con KYC del cliente.",
    }
    base.update(overrides)
    return base


def _valid_modify_body(**overrides: Any) -> dict:
    base: dict = {
        "client_id":        "CLI-APP-002",
        "proposed_profile": "moderado",
        "decision":         "modify",
        "approved_profile": "conservador",
        "rationale":        "Cliente expresa intolerancia a drawdowns mayores al 10%.",
    }
    base.update(overrides)
    return base


def _valid_reject_body(**overrides: Any) -> dict:
    base: dict = {
        "client_id":        "CLI-APP-003",
        "proposed_profile": "agresivo",
        "decision":         "reject",
        "rationale":        "KYC inconsistente: requerir nueva ronda.",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorProfileApprovalAuth:
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

    def test_malformed_header_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": "Basic dev-advisor-token"},
        )
        assert resp.status_code == 401

    def test_compliance_token_returns_403(self, client: TestClient) -> None:
        """RBAC: compliance no puede ejecutar actos formales del asesor."""
        resp = client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-CMP-OK"),
            headers={"Authorization": _COMPLIANCE_TOKEN},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_auth_failure_does_not_persist(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorProfileApprovalRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(_URL, json=_valid_approve_body())
        assert resp.status_code == 401

        # El record store no debe haber recibido nada — incluso si el archivo
        # .db no existe todavía (no se llegó a llamar a init_schema).
        if not _redirect_db_to_tmp.exists():
            return
        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            approvals = SQLiteAdvisorProfileApprovalRepository(store).list_approvals()
        assert approvals == []


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: approve
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorProfileApprovalApprove:
    def test_returns_200(self, client: TestClient) -> None:
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

    def test_approve_without_approved_profile_completes_with_proposed(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        data = resp.json()
        assert data["proposed_profile"] == "moderado"
        assert data["approved_profile"] == "moderado"

    def test_approve_with_matching_approved_profile_is_accepted(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(approved_profile="moderado"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["approved_profile"] == "moderado"

    def test_approve_with_different_approved_profile_returns_422(
        self, client: TestClient
    ) -> None:
        """approve significa "tal cual"; para cambiar debe ir como modify."""
        resp = client.post(
            _URL,
            json=_valid_approve_body(approved_profile="conservador"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

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


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: modify
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorProfileApprovalModify:
    def test_modify_with_valid_approved_profile_returns_200(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_modify_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200

    def test_modify_response_uses_approved_profile(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_modify_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        data = resp.json()
        assert data["proposed_profile"] == "moderado"
        assert data["approved_profile"] == "conservador"

    def test_modify_without_approved_profile_returns_422(
        self, client: TestClient
    ) -> None:
        body = _valid_modify_body()
        body.pop("approved_profile")
        resp = client.post(
            _URL,
            json=body,
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_modify_with_invalid_approved_profile_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_modify_body(approved_profile="ultra_agresivo_inventado"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_modify_to_same_profile_is_allowed(self, client: TestClient) -> None:
        """modify con approved == proposed no se bloquea (asesor declara explícitamente)."""
        resp = client.post(
            _URL,
            json=_valid_modify_body(approved_profile="moderado"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["approved_profile"] == "moderado"


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: reject
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorProfileApprovalReject:
    def test_reject_without_approved_profile_returns_200(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200

    def test_reject_response_approved_profile_is_none(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["approved_profile"] is None

    def test_reject_with_approved_profile_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_reject_body(approved_profile="moderado"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_reject_decision_propagated_in_response(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_reject_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["decision"] == "reject"


# ─────────────────────────────────────────────────────────────────────────────
# Validation errors
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorProfileApprovalValidation:
    def test_proposed_profile_invalid_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(proposed_profile="ultra_agresivo_inventado"),
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

    def test_rationale_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(rationale=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_rationale_whitespace_only_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(rationale="    "),
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

    def test_proposed_profile_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(proposed_profile=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# record_id and persistence
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorProfileApprovalPersistence:
    def test_record_id_prefix(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["record_id"].startswith("advisor_profile_approval_")

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
            SQLiteAdvisorProfileApprovalRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(
            _URL,
            json=_valid_modify_body(related_record_id="ai_filtered_portfolio_000001"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        data = resp.json()
        record_id = data["record_id"]

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            approval_repo = SQLiteAdvisorProfileApprovalRepository(store)
            record = approval_repo.get_approval(record_id)

        assert record.record_id == record_id
        assert record.record_type == "advisor_profile_approval"
        assert record.metadata["client_id"] == "CLI-APP-002"
        assert record.metadata["advisor_id"] == "ADV-001"
        assert record.metadata["decision"] == "modify"
        assert record.metadata["proposed_profile"] == "moderado"
        assert record.metadata["approved_profile"] == "conservador"
        assert record.metadata["endpoint"] == "/advisor/profile-approval"
        # Payload also contains the decision details.
        assert record.payload["rationale"].startswith("Cliente expresa")
        assert record.payload["related_record_id"] == "ai_filtered_portfolio_000001"

    def test_listing_filters_by_client_id(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorProfileApprovalRepository,
            SQLitePersistenceStore,
        )

        client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-LIST-A"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-LIST-B"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-LIST-A"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            repo = SQLiteAdvisorProfileApprovalRepository(store)
            all_records = repo.list_approvals()
            only_a = repo.list_approvals(client_id="CLI-LIST-A")
            only_b = repo.list_approvals(client_id="CLI-LIST-B")

        assert len(all_records) == 3
        assert len(only_a) == 2
        assert len(only_b) == 1
        assert {r.metadata["client_id"] for r in only_a} == {"CLI-LIST-A"}

    def test_persistence_failure_returns_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**_kwargs):
            raise RuntimeError("simulated SQLite failure")

        monkeypatch.setattr(
            _main_module,
            "_persist_advisor_profile_approval",
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
# Optional fields propagated correctly
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorProfileApprovalOptionalFields:
    def test_source_defaults_to_manual(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["source"] == "manual"

    def test_custom_source_is_propagated(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(source="ai_workflow"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["source"] == "ai_workflow"

    def test_related_record_id_defaults_to_none(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["related_record_id"] is None

    def test_related_record_id_propagated_in_response(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(related_record_id="ai_filtered_portfolio_000042"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["related_record_id"] == "ai_filtered_portfolio_000042"


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


class TestAdvisorProfileApprovalRBAC:
    """
    Verifica la frontera RBAC de /advisor/profile-approval:
        - compliance → 403 (ya cubierto en TestAdvisorProfileApprovalAuth,
          aquí se reitera para tener cobertura de detalle y leak).
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
            json=_valid_approve_body(client_id="CLI-VWR-PA"),
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
            json=_valid_approve_body(client_id="CLI-ADM-PA"),
            headers={"Authorization": "Bearer dev-admin-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["advisor_id"] == "ADM-001"

    def test_403_does_not_echo_token(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_approve_body(client_id="CLI-LEAK-PA"),
            headers={"Authorization": "Bearer dev-compliance-token"},
        )
        assert resp.status_code == 403
        assert "dev-compliance-token" not in resp.text
        for hv in resp.headers.values():
            assert "dev-compliance-token" not in hv

    def test_no_token_returns_401_not_403(self, client: TestClient) -> None:
        """authn precede a authz: sin token → 401, no 403."""
        resp = client.post(_URL, json=_valid_approve_body())
        assert resp.status_code == 401
