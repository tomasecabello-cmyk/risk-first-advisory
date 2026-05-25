"""
Integration tests for Phase 2 entity endpoints: Firm, Advisor, Client.

Cubre:
    POST /firms               — admin crea firma; 401/403 según rol; 409 en duplicado.
    GET  /firms               — listado público (cualquier token válido).
    GET  /firms/{firm_id}     — detalle; 404 cuando no existe.

    POST /advisors            — admin crea advisor; 422 FK violation; 409 duplicado.
    GET  /advisors            — listado.
    GET  /advisors/{id}       — detalle; 404.
    GET  /firms/{id}/advisors — filtrado por firma; 404 si firma no existe.

    POST /clients             — admin o advisor; validación cross-firm; 422/409.
    GET  /clients             — listado.
    GET  /clients/{id}        — detalle; 404.
    GET  /firms/{id}/clients  — filtrado; 404 si firma no existe.
    GET  /advisors/{id}/clients — filtrado; 404 si advisor no existe.

No usa OpenAI. No escribe en data/demo_api.db (monkeypatch de DEFAULT_DB_PATH
a tmp_path). La migración se aplica a la DB de test antes de cada test.
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
# Import migrate module (no package — use importlib)
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
# Tokens YAML — cubre los 4 roles del sistema.
# firm_id: null es obligatorio en todos los entries.
# ─────────────────────────────────────────────────────────────────────────────

_ENTITY_TEST_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-ENT-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-ENT-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-ENT-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-ENT-001
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
def _setup_entity_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """
    Aísla tokens de entorno local y activa los tokens de test.
    Se ejecuta en todos los tests del módulo.
    """
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "entity_tokens.yaml"
    tokens_yaml.write_text(_ENTITY_TEST_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def entity_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """
    Crea la DB de test con las tablas de entidades (via migración), y redirige
    DEFAULT_DB_PATH para que los endpoints usen esa DB temporal.
    """
    db_path = tmp_path / "entity_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Payloads de prueba
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**overrides: Any) -> dict:
    base: dict = {"display_name": "Acme Advisors", "country": "AR"}
    base.update(overrides)
    return base


def _advisor_body(firm_id: str, **overrides: Any) -> dict:
    base: dict = {
        "firm_id": firm_id,
        "display_name": "Jane Doe",
        "email": "jane@acme.com",
        "roles": ["advisor"],
    }
    base.update(overrides)
    return base


def _client_body(firm_id: str, primary_advisor_id: str, **overrides: Any) -> dict:
    base: dict = {
        "firm_id": firm_id,
        "primary_advisor_id": primary_advisor_id,
        "display_name": "Client Alpha",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Helper: crea la cadena firm → advisor → client para tests que la necesitan
# ─────────────────────────────────────────────────────────────────────────────


def _create_firm(client: TestClient, **overrides: Any) -> dict:
    resp = client.post(
        "/firms",
        json=_firm_body(**overrides),
        headers={"Authorization": _ADMIN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_advisor(client: TestClient, firm_id: str, **overrides: Any) -> dict:
    resp = client.post(
        "/advisors",
        json=_advisor_body(firm_id, **overrides),
        headers={"Authorization": _ADMIN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_client(
    client: TestClient, firm_id: str, primary_advisor_id: str, **overrides: Any
) -> dict:
    resp = client.post(
        "/clients",
        json=_client_body(firm_id, primary_advisor_id, **overrides),
        headers={"Authorization": _ADMIN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Firma — POST /firms
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateFirm:
    def test_admin_creates_firm_returns_201(self, client: TestClient) -> None:
        resp = client.post(
            "/firms", json=_firm_body(), headers={"Authorization": _ADMIN}
        )
        assert resp.status_code == 201

    def test_response_has_expected_shape(self, client: TestClient) -> None:
        resp = client.post(
            "/firms", json=_firm_body(), headers={"Authorization": _ADMIN}
        )
        body = resp.json()
        assert set(body.keys()) == {
            "firm_id", "display_name", "country", "is_active", "created_at_utc"
        }

    def test_auto_generated_firm_id_has_prefix(self, client: TestClient) -> None:
        resp = client.post(
            "/firms", json=_firm_body(), headers={"Authorization": _ADMIN}
        )
        assert resp.json()["firm_id"].startswith("firm_")

    def test_explicit_firm_id_is_stored(self, client: TestClient) -> None:
        body = _firm_body(firm_id="firm_CUSTOM01")
        resp = client.post("/firms", json=body, headers={"Authorization": _ADMIN})
        assert resp.json()["firm_id"] == "firm_CUSTOM01"

    def test_display_name_and_country_echo(self, client: TestClient) -> None:
        resp = client.post(
            "/firms",
            json=_firm_body(display_name="Beta Wealth", country="UY"),
            headers={"Authorization": _ADMIN},
        )
        body = resp.json()
        assert body["display_name"] == "Beta Wealth"
        assert body["country"] == "UY"
        assert body["is_active"] is True

    def test_duplicate_firm_id_returns_409(self, client: TestClient) -> None:
        body = _firm_body(firm_id="firm_DUPE")
        client.post("/firms", json=body, headers={"Authorization": _ADMIN})
        resp = client.post("/firms", json=body, headers={"Authorization": _ADMIN})
        assert resp.status_code == 409

    def test_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.post("/firms", json=_firm_body())
        assert resp.status_code == 401

    def test_advisor_token_returns_403(self, client: TestClient) -> None:
        resp = client.post(
            "/firms", json=_firm_body(), headers={"Authorization": _ADVISOR}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_viewer_token_returns_403(self, client: TestClient) -> None:
        resp = client.post(
            "/firms", json=_firm_body(), headers={"Authorization": _VIEWER}
        )
        assert resp.status_code == 403

    def test_compliance_token_returns_403(self, client: TestClient) -> None:
        resp = client.post(
            "/firms", json=_firm_body(), headers={"Authorization": _COMPLIANCE}
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Firma — GET /firms  y  GET /firms/{firm_id}
# ─────────────────────────────────────────────────────────────────────────────


class TestListGetFirm:
    def test_list_firms_returns_empty_initially(self, client: TestClient) -> None:
        resp = client.get("/firms", headers={"Authorization": _ADVISOR})
        assert resp.status_code == 200
        body = resp.json()
        assert body["firms"] == []
        assert body["count"] == 0

    def test_list_firms_includes_created_firm(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.get("/firms", headers={"Authorization": _COMPLIANCE})
        body = resp.json()
        assert body["count"] == 1
        assert body["firms"][0]["firm_id"] == firm["firm_id"]

    def test_list_firms_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.get("/firms")
        assert resp.status_code == 401

    def test_get_firm_by_id_returns_200(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.get(f"/firms/{firm['firm_id']}", headers={"Authorization": _VIEWER})
        assert resp.status_code == 200
        assert resp.json()["firm_id"] == firm["firm_id"]

    def test_get_firm_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/firms/firm_GHOST", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_get_firm_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.get("/firms/firm_GHOST")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Advisor — POST /advisors
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateAdvisor:
    def test_admin_creates_advisor_returns_201(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post(
            "/advisors",
            json=_advisor_body(firm["firm_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert resp.status_code == 201

    def test_response_has_expected_shape(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post(
            "/advisors",
            json=_advisor_body(firm["firm_id"]),
            headers={"Authorization": _ADMIN},
        )
        body = resp.json()
        assert set(body.keys()) == {
            "advisor_id", "firm_id", "display_name", "email",
            "roles", "is_active", "created_at_utc",
        }

    def test_auto_generated_advisor_id_has_prefix(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post(
            "/advisors",
            json=_advisor_body(firm["firm_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert resp.json()["advisor_id"].startswith("advisor_")

    def test_advisor_data_echoed_correctly(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post(
            "/advisors",
            json=_advisor_body(firm["firm_id"], email="jd@test.com", roles=["advisor", "compliance"]),
            headers={"Authorization": _ADMIN},
        )
        body = resp.json()
        assert body["firm_id"] == firm["firm_id"]
        assert body["email"] == "jd@test.com"
        assert set(body["roles"]) == {"advisor", "compliance"}

    def test_fk_violation_firm_not_found_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/advisors",
            json=_advisor_body("firm_NONEXISTENT"),
            headers={"Authorization": _ADMIN},
        )
        assert resp.status_code == 422

    def test_duplicate_advisor_id_returns_409(self, client: TestClient) -> None:
        firm = _create_firm(client)
        body = _advisor_body(firm["firm_id"], advisor_id="advisor_DUPE")
        client.post("/advisors", json=body, headers={"Authorization": _ADMIN})
        resp = client.post("/advisors", json=body, headers={"Authorization": _ADMIN})
        assert resp.status_code == 409

    def test_no_token_returns_401(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post("/advisors", json=_advisor_body(firm["firm_id"]))
        assert resp.status_code == 401

    def test_advisor_token_returns_403(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post(
            "/advisors",
            json=_advisor_body(firm["firm_id"]),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_viewer_token_returns_403(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post(
            "/advisors",
            json=_advisor_body(firm["firm_id"]),
            headers={"Authorization": _VIEWER},
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Advisor — GET /advisors, GET /advisors/{id}, GET /firms/{id}/advisors
# ─────────────────────────────────────────────────────────────────────────────


class TestListGetAdvisor:
    def test_list_advisors_empty_initially(self, client: TestClient) -> None:
        resp = client.get("/advisors", headers={"Authorization": _ADMIN})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_advisors_includes_created(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.get("/advisors", headers={"Authorization": _VIEWER})
        body = resp.json()
        assert body["count"] == 1
        assert body["advisors"][0]["advisor_id"] == adv["advisor_id"]

    def test_get_advisor_by_id_returns_200(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.get(f"/advisors/{adv['advisor_id']}", headers={"Authorization": _COMPLIANCE})
        assert resp.status_code == 200
        assert resp.json()["advisor_id"] == adv["advisor_id"]

    def test_get_advisor_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/advisors/advisor_GHOST", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_list_firm_advisors_returns_only_firm_advisors(self, client: TestClient) -> None:
        firm_a = _create_firm(client, display_name="Firm A")
        firm_b = _create_firm(client, display_name="Firm B")
        _create_advisor(client, firm_a["firm_id"], display_name="Adv A")
        _create_advisor(client, firm_b["firm_id"], display_name="Adv B")

        resp = client.get(
            f"/firms/{firm_a['firm_id']}/advisors",
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["advisors"][0]["firm_id"] == firm_a["firm_id"]

    def test_list_firm_advisors_firm_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/firms/firm_GHOST/advisors", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_list_advisors_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.get("/advisors")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Client — POST /clients
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateClient:
    def test_admin_creates_client_returns_201(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], adv["advisor_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert resp.status_code == 201

    def test_advisor_creates_client_returns_201(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], adv["advisor_id"]),
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 201

    def test_response_has_expected_shape(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], adv["advisor_id"]),
            headers={"Authorization": _ADMIN},
        )
        body = resp.json()
        assert set(body.keys()) == {
            "client_id", "firm_id", "primary_advisor_id", "display_name",
            "external_ref", "jurisdiction", "preferred_currency",
            "is_active", "created_at_utc",
        }

    def test_client_data_defaults_and_echo(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], adv["advisor_id"]),
            headers={"Authorization": _ADMIN},
        )
        body = resp.json()
        assert body["jurisdiction"] == "AR"
        assert body["preferred_currency"] == "USD"
        assert body["is_active"] is True
        assert body["external_ref"] is None

    def test_client_id_auto_generated_has_prefix(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], adv["advisor_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert resp.json()["client_id"].startswith("client_")

    def test_cross_firm_violation_returns_422(self, client: TestClient) -> None:
        firm_a = _create_firm(client, display_name="Firm A")
        firm_b = _create_firm(client, display_name="Firm B")
        adv_b = _create_advisor(client, firm_b["firm_id"])
        # Advisor belongs to firm_b, but we're creating client under firm_a
        resp = client.post(
            "/clients",
            json=_client_body(firm_a["firm_id"], adv_b["advisor_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert resp.status_code == 422

    def test_primary_advisor_not_found_returns_422(self, client: TestClient) -> None:
        firm = _create_firm(client)
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], "advisor_GHOST"),
            headers={"Authorization": _ADMIN},
        )
        assert resp.status_code == 422

    def test_duplicate_client_id_returns_409(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        body = _client_body(firm["firm_id"], adv["advisor_id"], client_id="client_DUPE")
        client.post("/clients", json=body, headers={"Authorization": _ADMIN})
        resp = client.post("/clients", json=body, headers={"Authorization": _ADMIN})
        assert resp.status_code == 409

    def test_no_token_returns_401(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post("/clients", json=_client_body(firm["firm_id"], adv["advisor_id"]))
        assert resp.status_code == 401

    def test_viewer_token_returns_403(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], adv["advisor_id"]),
            headers={"Authorization": _VIEWER},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == _RBAC_403_DETAIL

    def test_compliance_token_returns_403(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        resp = client.post(
            "/clients",
            json=_client_body(firm["firm_id"], adv["advisor_id"]),
            headers={"Authorization": _COMPLIANCE},
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Client — GET /clients, GET /clients/{id},
#          GET /firms/{id}/clients, GET /advisors/{id}/clients
# ─────────────────────────────────────────────────────────────────────────────


class TestListGetClient:
    def test_list_clients_empty_initially(self, client: TestClient) -> None:
        resp = client.get("/clients", headers={"Authorization": _ADMIN})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_list_clients_includes_created(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        resp = client.get("/clients", headers={"Authorization": _VIEWER})
        body = resp.json()
        assert body["count"] == 1
        assert body["clients"][0]["client_id"] == cli["client_id"]

    def test_get_client_by_id_returns_200(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"])
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        resp = client.get(f"/clients/{cli['client_id']}", headers={"Authorization": _COMPLIANCE})
        assert resp.status_code == 200
        assert resp.json()["client_id"] == cli["client_id"]

    def test_get_client_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/clients/client_GHOST", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_list_firm_clients_returns_only_firm_clients(self, client: TestClient) -> None:
        firm_a = _create_firm(client, display_name="Firm A")
        firm_b = _create_firm(client, display_name="Firm B")
        adv_a = _create_advisor(client, firm_a["firm_id"])
        adv_b = _create_advisor(client, firm_b["firm_id"])
        _create_client(client, firm_a["firm_id"], adv_a["advisor_id"], display_name="Cli A")
        _create_client(client, firm_b["firm_id"], adv_b["advisor_id"], display_name="Cli B")

        resp = client.get(
            f"/firms/{firm_a['firm_id']}/clients",
            headers={"Authorization": _ADVISOR},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["clients"][0]["firm_id"] == firm_a["firm_id"]

    def test_list_firm_clients_firm_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/firms/firm_GHOST/clients", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_list_advisor_clients_returns_only_advisor_clients(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv_1 = _create_advisor(client, firm["firm_id"], display_name="Adv 1", email="a1@f.com")
        adv_2 = _create_advisor(client, firm["firm_id"], display_name="Adv 2", email="a2@f.com")
        _create_client(client, firm["firm_id"], adv_1["advisor_id"], display_name="Cli 1")
        _create_client(client, firm["firm_id"], adv_2["advisor_id"], display_name="Cli 2")

        resp = client.get(
            f"/advisors/{adv_1['advisor_id']}/clients",
            headers={"Authorization": _ADMIN},
        )
        body = resp.json()
        assert body["count"] == 1
        assert body["clients"][0]["primary_advisor_id"] == adv_1["advisor_id"]

    def test_list_advisor_clients_advisor_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.get("/advisors/advisor_GHOST/clients", headers={"Authorization": _ADMIN})
        assert resp.status_code == 404

    def test_list_clients_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.get("/clients")
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Regresión: endpoints existentes siguen funcionando
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRegression:
    def test_health_still_works(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_auth_me_still_works_with_admin_token(self, client: TestClient) -> None:
        resp = client.get("/auth/me", headers={"Authorization": _ADMIN})
        assert resp.status_code == 200
        body = resp.json()
        assert body["advisor_id"] == "ADM-ENT-001"
        assert "admin" in body["roles"]
