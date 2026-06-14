"""
Integration tests for Phase 2 AIRequestLog endpoints + automatic integration
en /ai/investment-preferences, /ai/filter-universe-demo, /ai/filtered-portfolio-demo.

Cubre:
    GET  /admin/ai-logs                  — listado; RBAC admin/compliance.
    GET  /admin/ai-logs/{request_id}     — detalle; 404.
    GET  /cases/{case_id}/ai-logs        — filtrado por case; 404 si case no existe.
    POST /admin/ai-logs                  — creación manual (admin); FK validation.
    POST /ai/investment-preferences       — log automático.
    POST /ai/filter-universe-demo         — log automático.
    POST /ai/filtered-portfolio-demo      — log automático.

OpenAI se monkeypatchea con un fake client. No usa la API real.
La migración 0001 se aplica a la DB temporal antes de cada test.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module
import risk_first_advisory.config_layer.advisor_tokens as _tokens_module

# ─────────────────────────────────────────────────────────────────────────────
# Import migrate module (importlib)
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
# Tokens YAML
# ─────────────────────────────────────────────────────────────────────────────

_AIL_TEST_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-AIL-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-AIL-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-AIL-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-AIL-001
    display_name: Test Viewer
    firm_id: null
    roles:
      - viewer
"""

_ADMIN = "Bearer test-admin-token"
_ADVISOR = "Bearer test-advisor-token"
_COMPLIANCE = "Bearer test-compliance-token"
_VIEWER = "Bearer test-viewer-token"


# ─────────────────────────────────────────────────────────────────────────────
# Autouse fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_ail_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "ail_tokens.yaml"
    tokens_yaml.write_text(_AIL_TEST_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def ail_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "ail_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI client
# ─────────────────────────────────────────────────────────────────────────────


_VALID_PREFERENCES_RESPONSE: dict = {
    "allowed_instrument_types":  ["CORPORATE_BOND"],
    "excluded_instrument_types": [],
    "currency":                  "USD",
    "country":                   "Argentina",
    "entity":                    "Balanz",
    "hard_dollar_only":          True,
    "avoid_sectors":             ["Energy"],
    "prefer_sectors":            [],
    "avoid_issuers":             [],
    "prefer_issuers":            [],
    "min_liquidity_score":       None,
    "max_maturity_year":         None,
    "hard_constraints":          ["instrument_type"],
    "soft_preferences":          [],
    "unparsed_preferences":      [],
    "confidence":                0.85,
    "advisor_notes":             ["Cliente claro y conciso."],
}


def _make_fake_client(content: str) -> Any:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


def _make_failing_client() -> Any:
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("simulated OpenAI failure")
    return client


@pytest.fixture
def patch_ai_client(monkeypatch: pytest.MonkeyPatch):
    """Devuelve un factory para inyectar un OpenAIProfileClient con fake."""
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    def _install(content: dict | None = None, failing: bool = False) -> None:
        if failing:
            fake = _make_failing_client()
        else:
            fake = _make_fake_client(json.dumps(content or _VALID_PREFERENCES_RESPONSE))
        ai_client = OpenAIProfileClient(_client=fake)
        monkeypatch.setattr(
            _main_module, "_get_openai_profile_client", lambda: ai_client
        )

    return _install


# ─────────────────────────────────────────────────────────────────────────────
# Entity helpers
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "AIL Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "display_name": "AIL Advisor",
        "email": "a@ail.com",
        "roles": ["advisor"],
        **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "primary_advisor_id": advisor_id,
        "display_name": "AIL Client",
        **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "lead_advisor_id": advisor_id,
        "title": "AIL Case",
        **kw,
    }


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
    firm = _create_firm(c)
    # Register token's advisor_id so audit-event FK passes when creating case
    adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-AIL-001")
    cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
    case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    return case


def _make_log_body(**overrides) -> dict:
    base = {
        "endpoint":          "/ai/investment-preferences",
        "model":             "gpt-4o-mini",
        "prompt_version":    "investment_preferences_v1",
        "input_payload":     {"client_id": "C-ZZZ", "natural_language_preferences": "x"},
        "validation_status": "parsed_ok",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# RBAC for GET /admin/ai-logs
# ─────────────────────────────────────────────────────────────────────────────


class TestRBACList:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        r = client.get("/admin/ai-logs")
        assert r.status_code == 401

    def test_advisor_returns_403(self, client: TestClient) -> None:
        r = client.get("/admin/ai-logs", headers={"Authorization": _ADVISOR})
        assert r.status_code == 403

    def test_viewer_returns_403(self, client: TestClient) -> None:
        r = client.get("/admin/ai-logs", headers={"Authorization": _VIEWER})
        assert r.status_code == 403

    def test_compliance_returns_200(self, client: TestClient) -> None:
        r = client.get("/admin/ai-logs", headers={"Authorization": _COMPLIANCE})
        assert r.status_code == 200
        assert r.json() == {"logs": [], "count": 0}

    def test_admin_returns_200(self, client: TestClient) -> None:
        r = client.get("/admin/ai-logs", headers={"Authorization": _ADMIN})
        assert r.status_code == 200


class TestRBACGet:
    def test_missing_log_returns_404(self, client: TestClient) -> None:
        r = client.get(
            "/admin/ai-logs/ai_request_nope",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 404

    def test_advisor_returns_403(self, client: TestClient) -> None:
        r = client.get(
            "/admin/ai-logs/ai_request_x",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 403


class TestRBACCaseLogs:
    def test_compliance_can_list(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/ai-logs",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 0  # case sin logs

    def test_advisor_returns_403(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(
            f"/cases/{case['case_id']}/ai-logs",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 403

    def test_no_token_returns_401(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.get(f"/cases/{case['case_id']}/ai-logs")
        assert r.status_code == 401

    def test_missing_case_returns_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/ai-logs",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# POST /admin/ai-logs — manual creation
# ─────────────────────────────────────────────────────────────────────────────


class TestPostManual:
    def test_admin_creates_log(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["request_id"].startswith("ai_request_")
        assert body["validation_status"] == "parsed_ok"
        assert body["endpoint"] == "/ai/investment-preferences"

    def test_advisor_forbidden(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(),
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 403

    def test_compliance_forbidden(self, client: TestClient) -> None:
        # POST is admin-only (no compliance writes).
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(),
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403

    def test_invalid_validation_status_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(validation_status="not_a_status"),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 422

    def test_missing_case_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(case_id="case_nope"),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 422
        assert "Case not found" in r.json()["detail"]

    def test_missing_advisor_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(requested_by_advisor_id="advisor_nope"),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 422

    def test_with_existing_case_succeeds(self, client: TestClient) -> None:
        case = _full_chain(client)
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(case_id=case["case_id"]),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201
        assert r.json()["case_id"] == case["case_id"]

    def test_empty_endpoint_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(endpoint=""),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 422

    def test_negative_latency_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(latency_ms=-1),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 422

    def test_input_payload_not_dict_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/admin/ai-logs",
            json=_make_log_body(input_payload=["not", "a", "dict"]),
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 422

    def test_post_log_redacts_input_in_persisted_record(
        self, client: TestClient
    ) -> None:
        # Pasamos client_id + texto libre y verificamos que el log persistido
        # NO contiene los valores originales en input_redacted.
        sensitive_text = "Esto es un open_concerns sensible del cliente"
        body = _make_log_body(
            input_payload={
                "client_id": "C-SENS-001",
                "open_concerns": sensitive_text,
            }
        )
        r = client.post(
            "/admin/ai-logs", json=body, headers={"Authorization": _ADMIN}
        )
        assert r.status_code == 201
        # GET to confirm persistence
        rid = r.json()["request_id"]
        got = client.get(
            f"/admin/ai-logs/{rid}", headers={"Authorization": _ADMIN}
        ).json()
        redacted_blob = json.dumps(got["input_redacted"])
        assert "C-SENS-001" not in redacted_blob
        assert sensitive_text not in redacted_blob
        assert got["input_redacted"]["client_id"].startswith("client_")


# ─────────────────────────────────────────────────────────────────────────────
# Auto-integration: /ai/investment-preferences
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoInvestmentPreferences:
    def test_endpoint_creates_log(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        r = client.post(
            "/ai/investment-preferences",
            json={
                "client_id": "C-INV-1",
                "natural_language_preferences": "Solo ONs hard dollar argentinas",
            },
        )
        assert r.status_code == 200, r.text
        listing = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()
        assert listing["count"] == 1
        log = listing["logs"][0]
        assert log["endpoint"] == "/ai/investment-preferences"
        assert log["prompt_version"] == "investment_preferences_v1"
        assert log["validation_status"] == "parsed_ok"

    def test_log_input_does_not_contain_natural_language(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        secret = "Texto libre con detalle único xyz123 del cliente"
        client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-X", "natural_language_preferences": secret},
        )
        listing = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()
        log = listing["logs"][0]
        assert secret not in json.dumps(log["input_redacted"])
        assert log["input_redacted"]["natural_language_preferences"].startswith(
            "<REDACTED:text_"
        )

    def test_log_client_id_is_hashed(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-XYZ-orig", "natural_language_preferences": "x"},
        )
        log = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"][0]
        assert log["input_redacted"]["client_id"] != "C-XYZ-orig"
        assert log["input_redacted"]["client_id"].startswith("client_")

    def test_log_raw_response_persisted(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-1", "natural_language_preferences": "x"},
        )
        log = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"][0]
        assert log["raw_response"] is not None
        assert "confidence" in log["raw_response"]

    def test_endpoint_still_returns_correct_response(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        r = client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-1", "natural_language_preferences": "x"},
        )
        body = r.json()
        # contract intacto
        assert body["client_id"] == "C-1"
        assert body["confidence"] == 0.85
        assert body["allowed_instrument_types"] == ["CORPORATE_BOND"]

    def test_input_hash_changes_with_different_input(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-1", "natural_language_preferences": "alpha"},
        )
        client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-1", "natural_language_preferences": "beta"},
        )
        logs = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"]
        assert len(logs) == 2
        assert logs[0]["input_hash"] != logs[1]["input_hash"]

    def test_log_validation_status_api_error_when_openai_fails(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client(failing=True)
        r = client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-1", "natural_language_preferences": "x"},
        )
        assert r.status_code == 502
        log = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"][0]
        assert log["validation_status"] == "api_error"
        assert log["error_message"] is not None
        assert log["raw_response"] is None

    def test_latency_ms_is_populated(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        client.post(
            "/ai/investment-preferences",
            json={"client_id": "C-1", "natural_language_preferences": "x"},
        )
        log = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"][0]
        assert isinstance(log["latency_ms"], int)
        assert log["latency_ms"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Auto-integration: /ai/filter-universe-demo
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoFilterUniverse:
    def test_endpoint_creates_log(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        r = client.post(
            "/ai/filter-universe-demo",
            json={
                "client_id": "C-FU-1",
                "natural_language_preferences": "Solo ONs USD",
            },
        )
        assert r.status_code == 200, r.text
        log = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"][0]
        assert log["endpoint"] == "/ai/filter-universe-demo"
        assert log["prompt_version"] == "ai_universe_filter_v1"
        assert log["validation_status"] == "parsed_ok"


# ─────────────────────────────────────────────────────────────────────────────
# Auto-integration: /ai/filtered-portfolio-demo
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoFilteredPortfolio:
    def test_endpoint_creates_log(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        # No es relevante si genera portfolios o se bloquea — solo
        # comprobamos que el log se creó.
        client.post(
            "/ai/filtered-portfolio-demo",
            json={
                "client_id": "C-FP-1",
                "profile": "moderado",
                "natural_language_preferences": "Algo razonable",
            },
        )
        log = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"][0]
        assert log["endpoint"] == "/ai/filtered-portfolio-demo"
        assert log["prompt_version"] == "ai_filtered_portfolio_v1"


# ─────────────────────────────────────────────────────────────────────────────
# GET ordering & content
# ─────────────────────────────────────────────────────────────────────────────


class TestListOrdering:
    def test_list_orders_by_created_at_asc(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        for i in range(3):
            client.post(
                "/ai/investment-preferences",
                json={"client_id": f"C-{i}", "natural_language_preferences": "x"},
            )
        logs = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"]
        # request_ids deben ser monotónicamente crecientes
        ids = [log["request_id"] for log in logs]
        assert ids == sorted(ids)

    def test_limit_query_param(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        for i in range(5):
            client.post(
                "/ai/investment-preferences",
                json={"client_id": f"C-{i}", "natural_language_preferences": "x"},
            )
        body = client.get(
            "/admin/ai-logs?limit=2", headers={"Authorization": _ADMIN}
        ).json()
        assert body["count"] == 2
        assert len(body["logs"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# No regression
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRegression:
    def test_health_still_works(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200

    def test_auth_me_still_works(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert r.status_code == 200

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
        assert r.status_code != 404
        assert r.status_code != 401

    def test_filtered_portfolio_demo_no_auth_required(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        r = client.post(
            "/ai/filtered-portfolio-demo",
            json={
                "client_id": "C-X",
                "profile": "moderado",
                "natural_language_preferences": "x",
            },
        )
        # Sin token: no 401 (sigue siendo público).
        assert r.status_code != 401
