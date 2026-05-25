"""
Integration tests for POST /advisor/portfolio-selection — tercer acto formal
del asesor en Fase 1.

Cubre:
    - Auth: requiere Bearer válido (advisor o compliance) → 401 en otro caso.
    - Validación de selected_variant, rationale, client_id.
    - Warning: GROWTH sin override_approval_record_id genera warning;
      con override no genera warning; DEFENSIVE/BALANCED con override no
      genera warning.
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


_URL = "/advisor/portfolio-selection"
_ADVISOR_TOKEN = "Bearer dev-advisor-token"
_COMPLIANCE_TOKEN = "Bearer dev-compliance-token"
_RBAC_403_DETAIL = "Advisor role is not authorized for this action."

_GROWTH_WARNING = "GROWTH selected without linked override approval record."


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
    db_path = tmp_path / "advisor_portfolio_selection.db"
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


def _valid_balanced_body(**overrides: Any) -> dict:
    base: dict = {
        "client_id":         "CLI-SEL-001",
        "related_record_id": "ai_filtered_portfolio_000001",
        "selected_variant":  "BALANCED",
        "rationale":         "BALANCED respeta el RiskBudget aprobado para perfil moderado.",
    }
    base.update(overrides)
    return base


def _valid_growth_body_with_override(**overrides: Any) -> dict:
    base: dict = {
        "client_id":                   "CLI-SEL-002",
        "related_record_id":           "ai_filtered_portfolio_000002",
        "selected_variant":            "GROWTH",
        "rationale":                   "Cliente acepta perfil más agresivo tras revisión.",
        "override_approval_record_id": "advisor_override_approval_000001",
    }
    base.update(overrides)
    return base


def _valid_growth_body_without_override(**overrides: Any) -> dict:
    base: dict = {
        "client_id":         "CLI-SEL-003",
        "related_record_id": "ai_filtered_portfolio_000003",
        "selected_variant":  "GROWTH",
        "rationale":         "Selección preliminar de GROWTH — override pendiente.",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorPortfolioSelectionAuth:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.post(_URL, json=_valid_balanced_body())
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401

    def test_malformed_auth_header_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": "Basic dev-advisor-token"},
        )
        assert resp.status_code == 401

    def test_compliance_token_returns_403(self, client: TestClient) -> None:
        """RBAC: compliance no puede ejecutar actos formales del asesor."""
        resp = client.post(
            _URL,
            json=_valid_balanced_body(client_id="CLI-CMP-SEL"),
            headers={"Authorization": _COMPLIANCE_TOKEN},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_auth_failure_does_not_persist(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorPortfolioSelectionRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(_URL, json=_valid_balanced_body())
        assert resp.status_code == 401

        if not _redirect_db_to_tmp.exists():
            return
        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            selections = SQLiteAdvisorPortfolioSelectionRepository(store).list_selections()
        assert selections == []


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: BALANCED
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorPortfolioSelectionBalanced:
    def test_select_balanced_returns_200(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200

    def test_response_contains_advisor_id_ADV_001(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["advisor_id"] == "ADV-001"

    def test_response_contains_selected_variant_balanced(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["selected_variant"] == "BALANCED"

    def test_response_status_recorded(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["status"] == "recorded"

    def test_response_contains_advisor_display_name(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["advisor_display_name"] == "Demo Advisor"

    def test_response_contains_created_at_utc(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        created = resp.json()["created_at_utc"]
        assert isinstance(created, str)
        assert created.endswith("Z")
        assert "T" in created

    def test_balanced_does_not_warn(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["warnings"] == []

    def test_balanced_with_override_record_id_is_accepted_without_warning(
        self, client: TestClient
    ) -> None:
        """DEFENSIVE/BALANCED + override_approval_record_id se acepta sin warning."""
        resp = client.post(
            _URL,
            json=_valid_balanced_body(
                override_approval_record_id="advisor_override_approval_000007"
            ),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["warnings"] == []
        assert resp.json()["override_approval_record_id"] == "advisor_override_approval_000007"

    def test_defensive_variant_is_accepted(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(selected_variant="DEFENSIVE"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["selected_variant"] == "DEFENSIVE"
        assert resp.json()["warnings"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: GROWTH
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorPortfolioSelectionGrowth:
    def test_select_growth_with_override_returns_200(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_growth_body_with_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200

    def test_growth_with_override_no_warning(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_growth_body_with_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        warnings = resp.json()["warnings"]
        assert _GROWTH_WARNING not in warnings
        # In fact, no warnings at all in this happy path.
        assert warnings == []

    def test_growth_with_override_propagates_record_id(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_growth_body_with_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert (
            resp.json()["override_approval_record_id"]
            == "advisor_override_approval_000001"
        )

    def test_select_growth_without_override_returns_200(
        self, client: TestClient
    ) -> None:
        """No bloquea — el endpoint solo agrega un warning para que
        compliance pueda revisar."""
        resp = client.post(
            _URL,
            json=_valid_growth_body_without_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200

    def test_growth_without_override_returns_warning(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_growth_body_without_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        warnings = resp.json()["warnings"]
        assert _GROWTH_WARNING in warnings

    def test_growth_without_override_response_has_none_for_record_id(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_growth_body_without_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["override_approval_record_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Validation errors
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorPortfolioSelectionValidation:
    def test_selected_variant_invalid_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(selected_variant="ULTRA_GROWTH"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_selected_variant_lowercase_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(selected_variant="balanced"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_selected_variant_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(selected_variant=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_rationale_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(rationale=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_rationale_whitespace_only_returns_422(
        self, client: TestClient
    ) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(rationale="    "),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_client_id_empty_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(client_id=""),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422

    def test_missing_required_fields_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json={"client_id": "CLI-X"},
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorPortfolioSelectionPersistence:
    def test_record_id_prefix(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["record_id"].startswith("advisor_portfolio_selection_")

    def test_record_id_is_json_serializable(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        serialised = json.dumps(resp.json())
        reloaded = json.loads(serialised)
        assert reloaded["record_id"] == resp.json()["record_id"]

    def test_persisted_record_retrievable(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorPortfolioSelectionRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(
            _URL,
            json=_valid_growth_body_with_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 200
        record_id = resp.json()["record_id"]

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            repo = SQLiteAdvisorPortfolioSelectionRepository(store)
            record = repo.get_selection(record_id)

        assert record.record_id == record_id
        assert record.record_type == "advisor_portfolio_selection"
        assert record.metadata["client_id"] == "CLI-SEL-002"
        assert record.metadata["advisor_id"] == "ADV-001"
        assert record.metadata["selected_variant"] == "GROWTH"
        assert record.metadata["related_record_id"] == "ai_filtered_portfolio_000002"
        assert (
            record.metadata["override_approval_record_id"]
            == "advisor_override_approval_000001"
        )
        assert record.metadata["endpoint"] == "/advisor/portfolio-selection"
        # Payload also contains the decision details (and any warnings emitted).
        assert record.payload["rationale"].startswith("Cliente acepta")
        assert record.payload["warnings"] == []  # GROWTH + override → no warning

    def test_growth_without_override_persists_warning_in_payload(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorPortfolioSelectionRepository,
            SQLitePersistenceStore,
        )

        resp = client.post(
            _URL,
            json=_valid_growth_body_without_override(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        record_id = resp.json()["record_id"]

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            record = SQLiteAdvisorPortfolioSelectionRepository(store).get_selection(
                record_id
            )
        # The warning must be persisted, so compliance can flag this selection
        # later without re-deriving the rule.
        assert _GROWTH_WARNING in record.payload["warnings"]
        # And the metadata flags the absence of the override link.
        assert record.metadata["override_approval_record_id"] is None

    def test_listing_filters_by_client_id(
        self, client: TestClient, _redirect_db_to_tmp: Path
    ) -> None:
        from risk_first_advisory.persistence_layer.sqlite_repository import (
            SQLiteAdvisorPortfolioSelectionRepository,
            SQLitePersistenceStore,
        )

        client.post(
            _URL,
            json=_valid_balanced_body(client_id="CLI-LIST-S"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        client.post(
            _URL,
            json=_valid_growth_body_with_override(client_id="CLI-LIST-S"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        client.post(
            _URL,
            json=_valid_balanced_body(client_id="CLI-LIST-T"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )

        with SQLitePersistenceStore(_redirect_db_to_tmp) as store:
            store.init_schema()
            repo = SQLiteAdvisorPortfolioSelectionRepository(store)
            all_records = repo.list_selections()
            only_s = repo.list_selections(client_id="CLI-LIST-S")
            only_t = repo.list_selections(client_id="CLI-LIST-T")

        assert len(all_records) == 3
        assert len(only_s) == 2
        assert len(only_t) == 1
        variants_s = [r.metadata["selected_variant"] for r in only_s]
        assert variants_s == ["BALANCED", "GROWTH"]

    def test_persistence_failure_returns_500(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**_kwargs):
            raise RuntimeError("simulated SQLite failure")

        monkeypatch.setattr(
            _main_module,
            "_persist_advisor_portfolio_selection",
            _boom,
        )

        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.status_code == 500
        assert "persistence" in resp.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# Optional fields
# ─────────────────────────────────────────────────────────────────────────────


class TestAdvisorPortfolioSelectionOptionalFields:
    def test_source_defaults_to_manual(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["source"] == "manual"

    def test_custom_source_propagated(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(source="frontend_button"),
            headers={"Authorization": _ADVISOR_TOKEN},
        )
        assert resp.json()["source"] == "frontend_button"

    def test_related_record_id_can_be_null(self, client: TestClient) -> None:
        body = _valid_balanced_body()
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


class TestAdvisorPortfolioSelectionRBAC:
    """
    Verifica la frontera RBAC de /advisor/portfolio-selection:
        - compliance → 403 (también cubierto en TestAdvisorPortfolioSelectionAuth).
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
            json=_valid_balanced_body(client_id="CLI-VWR-SEL"),
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
            json=_valid_balanced_body(client_id="CLI-ADM-SEL"),
            headers={"Authorization": "Bearer dev-admin-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["advisor_id"] == "ADM-001"

    def test_403_does_not_echo_token(self, client: TestClient) -> None:
        resp = client.post(
            _URL,
            json=_valid_balanced_body(client_id="CLI-LEAK-SEL"),
            headers={"Authorization": "Bearer dev-compliance-token"},
        )
        assert resp.status_code == 403
        assert "dev-compliance-token" not in resp.text
        for hv in resp.headers.values():
            assert "dev-compliance-token" not in hv

    def test_no_token_returns_401_not_403(self, client: TestClient) -> None:
        resp = client.post(_URL, json=_valid_balanced_body())
        assert resp.status_code == 401
