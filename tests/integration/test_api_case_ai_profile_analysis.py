"""
Integration tests for Phase 2 case-scoped AI profile analysis.

Cubre:
    POST /cases/{case_id}/ai/profile-analysis  — advisor/admin lanza análisis.
    GET  /cases/{case_id}/ai/profile-analysis  — listado por caso.

Persistencia:
    - Migrations 0001 + 0002 + 0003 corridas en DB temporal.
    - El análisis queda vinculado a (case_id, kyc_submission_id, ai_request_log_id).
    - AIRequestLog se persiste con case_id poblado e input_redacted (sin texto libre).
    - AuditEvent ai_profile_analyzed se crea con metadata.

No usa OpenAI real; el cliente se monkeypatchea.
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
# Migrate import
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

_TEST_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-CPA-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-CPA-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-CPA-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-CPA-001
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
def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "cpa_tokens.yaml"
    tokens_yaml.write_text(_TEST_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def cpa_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "cpa_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI client
# ─────────────────────────────────────────────────────────────────────────────


_VALID_KYC_RESPONSE: dict = {
    "preliminary_profile": "moderado",
    "confidence": 0.78,
    "contradictions": [
        {
            "field": "risk_tolerance_score",
            "severity": "medium",
            "explanation": "High tolerance but high liquidity need.",
        }
    ],
    "follow_up_questions": ["¿Cuál es su horizonte real?"],
    "advisor_notes": ["Verificar coherencia."],
}


def _make_fake_chat(content: str) -> Any:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    completion = MagicMock()
    completion.choices = [choice]
    cli = MagicMock()
    cli.chat.completions.create.return_value = completion
    return cli


def _make_failing_chat() -> Any:
    cli = MagicMock()
    cli.chat.completions.create.side_effect = RuntimeError("simulated OpenAI failure")
    return cli


@pytest.fixture
def patch_ai_client(monkeypatch: pytest.MonkeyPatch):
    """Inyecta OpenAIProfileClient con un fake chat."""
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    def _install(response: dict | None = None, failing: bool = False) -> None:
        if failing:
            fake = _make_failing_chat()
        else:
            fake = _make_fake_chat(json.dumps(response or _VALID_KYC_RESPONSE))
        client_obj = OpenAIProfileClient(_client=fake)
        monkeypatch.setattr(
            _main_module, "_get_openai_profile_client", lambda: client_obj
        )

    return _install


# ─────────────────────────────────────────────────────────────────────────────
# Entity helpers
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "CPA Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "display_name": "CPA Advisor",
        "email": "a@cpa.com",
        "roles": ["advisor"],
        **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "primary_advisor_id": advisor_id,
        "display_name": "CPA Client",
        **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "lead_advisor_id": advisor_id,
        "title": "CPA Case",
        **kw,
    }


def _kyc_body(**overrides: Any) -> dict:
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
        "open_concerns": "Texto libre con detalle sensible del cliente xyz123",
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


def _post_kyc(c: TestClient, case_id: str, **overrides) -> Any:
    return c.post(
        f"/cases/{case_id}/kyc",
        json=_kyc_body(**overrides),
        headers={"Authorization": _ADVISOR},
    )


def _full_chain_with_kyc(c: TestClient) -> dict:
    """Crea firm + advisor (ADV-CPA-001) + client + case + 1 KYC submission.
    Devuelve dict con 'case' y 'kyc'."""
    firm = _create_firm(c)
    adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-CPA-001")
    cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
    case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    kyc_resp = _post_kyc(c, case["case_id"])
    assert kyc_resp.status_code == 201, kyc_resp.text
    return {"case": case, "kyc": kyc_resp.json()}


def _post_analysis(c: TestClient, case_id: str, **body) -> Any:
    return c.post(
        f"/cases/{case_id}/ai/profile-analysis",
        json=body,
        headers={"Authorization": _ADVISOR},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateAnalysis:
    def test_201(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.status_code == 201, r.text

    def test_analysis_id_prefix(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.json()["analysis_id"].startswith("ai_profile_analysis_")

    def test_case_id_in_response(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.json()["case_id"] == ctx["case"]["case_id"]

    def test_kyc_submission_id_in_response(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.json()["kyc_submission_id"] == ctx["kyc"]["kyc_submission_id"]

    def test_ai_request_log_id_populated(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        rl = r.json()["ai_request_log_id"]
        assert rl is not None
        assert rl.startswith("ai_request_")

    def test_analysis_type_default_initial(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.json()["analysis_type"] == "initial"

    def test_preliminary_profile_from_ai(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.json()["preliminary_profile"] == "moderado"

    def test_confidence_from_ai(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.json()["confidence"] == pytest.approx(0.78)

    def test_result_contains_ai_fields(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        result = r.json()["result"]
        assert result["preliminary_profile"] == "moderado"
        assert "contradictions" in result
        assert "follow_up_questions" in result
        assert "advisor_notes" in result

    def test_get_lists_one(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        _post_analysis(client, ctx["case"]["case_id"])
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_second_post_creates_second(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        _post_analysis(client, ctx["case"]["case_id"])
        _post_analysis(client, ctx["case"]["case_id"])
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            headers={"Authorization": _ADVISOR},
        )
        assert r.json()["count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# KYC selection
# ─────────────────────────────────────────────────────────────────────────────


class TestKYCSelection:
    def test_default_uses_current_kyc_submission(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        # Crear segunda KYC; current pasa a ser la nueva.
        second = _post_kyc(client, ctx["case"]["case_id"], age=55).json()
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.json()["kyc_submission_id"] == second["kyc_submission_id"]

    def test_explicit_kyc_submission_id_used(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        first_id = ctx["kyc"]["kyc_submission_id"]
        # Crear segunda KYC para que current cambie
        _post_kyc(client, ctx["case"]["case_id"], age=55)
        r = _post_analysis(
            client, ctx["case"]["case_id"], kyc_submission_id=first_id
        )
        assert r.json()["kyc_submission_id"] == first_id

    def test_kyc_submission_id_unknown_returns_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(
            client,
            ctx["case"]["case_id"],
            kyc_submission_id="kyc_submission_NOPE",
        )
        assert r.status_code == 422
        assert "KYC submission not found" in r.json()["detail"]

    def test_kyc_submission_id_from_other_case_returns_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        # Caso A con KYC
        ctx_a = _full_chain_with_kyc(client)
        # Caso B con su propia KYC (mismo firm/client/advisor)
        firm = ctx_a["case"]["firm_id"]
        adv_id = ctx_a["case"]["lead_advisor_id"]
        client_id = ctx_a["case"]["client_id"]
        case_b_resp = client.post(
            "/cases",
            json=_case_body(firm, client_id, adv_id, title="Case B"),
            headers={"Authorization": _ADVISOR},
        )
        case_b = case_b_resp.json()
        # Tratar de usar KYC del caso A en el caso B
        r = _post_analysis(
            client,
            case_b["case_id"],
            kyc_submission_id=ctx_a["kyc"]["kyc_submission_id"],
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_case_without_kyc_returns_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        # Caso sin KYC submission.
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"], advisor_id="ADV-CPA-001")
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        r = _post_analysis(client, case["case_id"])
        assert r.status_code == 409
        assert "no KYC submission" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# AIRequestLog integration
# ─────────────────────────────────────────────────────────────────────────────


class TestAIRequestLogIntegration:
    def test_log_has_case_id(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        rid = r.json()["ai_request_log_id"]
        log = client.get(
            f"/admin/ai-logs/{rid}", headers={"Authorization": _ADMIN}
        ).json()
        assert log["case_id"] == ctx["case"]["case_id"]

    def test_log_input_redacted_does_not_contain_open_concerns(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        rid = r.json()["ai_request_log_id"]
        log = client.get(
            f"/admin/ai-logs/{rid}", headers={"Authorization": _ADMIN}
        ).json()
        # open_concerns contiene "xyz123" — debe estar redactado.
        assert "xyz123" not in json.dumps(log["input_redacted"])
        oc = log["input_redacted"].get("open_concerns")
        if oc is not None:
            assert oc.startswith("<REDACTED:text_")

    def test_log_validation_status_parsed_ok(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        rid = r.json()["ai_request_log_id"]
        log = client.get(
            f"/admin/ai-logs/{rid}", headers={"Authorization": _ADMIN}
        ).json()
        assert log["validation_status"] == "parsed_ok"

    def test_log_prompt_version(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        rid = r.json()["ai_request_log_id"]
        log = client.get(
            f"/admin/ai-logs/{rid}", headers={"Authorization": _ADMIN}
        ).json()
        assert log["prompt_version"] == "case_profile_analysis_v1"

    def test_log_endpoint(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        rid = r.json()["ai_request_log_id"]
        log = client.get(
            f"/admin/ai-logs/{rid}", headers={"Authorization": _ADMIN}
        ).json()
        assert log["endpoint"] == f"/cases/{ctx['case']['case_id']}/ai/profile-analysis"

    def test_case_ai_logs_includes_the_log(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        rid = r.json()["ai_request_log_id"]
        logs = client.get(
            f"/cases/{ctx['case']['case_id']}/ai-logs",
            headers={"Authorization": _ADMIN},
        ).json()
        ids = [lg["request_id"] for lg in logs["logs"]]
        assert rid in ids


# ─────────────────────────────────────────────────────────────────────────────
# Audit integration
# ─────────────────────────────────────────────────────────────────────────────


class TestAuditIntegration:
    def test_chain_has_case_created_kyc_submitted_profile_analyzed(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        _post_analysis(client, ctx["case"]["case_id"])
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "case_created" in types
        assert "kyc_submitted" in types
        assert "ai_profile_analyzed" in types

    def test_event_payload_metadata(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        body = r.json()
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        evt = next(e for e in events if e["event_type"] == "ai_profile_analyzed")
        p = evt["payload"]
        assert p["analysis_id"] == body["analysis_id"]
        assert p["kyc_submission_id"] == body["kyc_submission_id"]
        assert p["ai_request_log_id"] == body["ai_request_log_id"]
        assert p["analysis_type"] == "initial"
        assert p["preliminary_profile"] == "moderado"

    def test_verify_intact_after(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        _post_analysis(client, ctx["case"]["case_id"])
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200
        assert r.json()["is_intact"] is True


# ─────────────────────────────────────────────────────────────────────────────
# RBAC
# ─────────────────────────────────────────────────────────────────────────────


class TestRBACPost:
    def test_no_token_returns_401(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis", json={}
        )
        assert r.status_code == 401

    def test_compliance_returns_403(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            json={},
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403

    def test_viewer_returns_403(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            json={},
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_returns_201(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.status_code == 201

    def test_admin_returns_201(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            json={},
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACGet:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        ctx = _full_chain_with_kyc(client)
        r = client.get(f"/cases/{ctx['case']['case_id']}/ai/profile-analysis")
        assert r.status_code == 401

    def test_compliance_returns_200(self, client: TestClient) -> None:
        ctx = _full_chain_with_kyc(client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_viewer_returns_200(self, client: TestClient) -> None:
        ctx = _full_chain_with_kyc(client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200

    def test_advisor_returns_200(self, client: TestClient) -> None:
        ctx = _full_chain_with_kyc(client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200

    def test_admin_returns_200(self, client: TestClient) -> None:
        ctx = _full_chain_with_kyc(client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Validation / errors
# ─────────────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_case_post_returns_404(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        r = _post_analysis(client, "case_nope")
        assert r.status_code == 404

    def test_missing_case_get_returns_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/ai/profile-analysis",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404

    def test_closed_case_returns_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        case_id = ctx["case"]["case_id"]
        # llevar a CLOSED (DRAFT→IN_PROGRESS ya ocurrió por POST KYC, así que
        # solo faltan PORTFOLIO_SELECTED → CLOSED).
        client.patch(
            f"/cases/{case_id}/status",
            json={"status": "PORTFOLIO_SELECTED"},
            headers={"Authorization": _ADVISOR},
        )
        client.patch(
            f"/cases/{case_id}/status",
            json={"status": "CLOSED"},
            headers={"Authorization": _ADVISOR},
        )
        r = _post_analysis(client, case_id)
        assert r.status_code == 409
        assert "CLOSED" in r.json()["detail"]

    def test_analysis_type_invalid_returns_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(
            client, ctx["case"]["case_id"], analysis_type="bogus"
        )
        assert r.status_code == 422

    def test_analysis_type_follow_up_returns_422_not_implemented(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(
            client, ctx["case"]["case_id"], analysis_type="follow_up"
        )
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI failure
# ─────────────────────────────────────────────────────────────────────────────


class TestOpenAIFailure:
    def test_returns_502(self, client: TestClient, patch_ai_client) -> None:
        patch_ai_client(failing=True)
        ctx = _full_chain_with_kyc(client)
        r = _post_analysis(client, ctx["case"]["case_id"])
        assert r.status_code == 502

    def test_creates_ai_request_log_with_api_error(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client(failing=True)
        ctx = _full_chain_with_kyc(client)
        _post_analysis(client, ctx["case"]["case_id"])
        logs = client.get(
            "/admin/ai-logs", headers={"Authorization": _ADMIN}
        ).json()["logs"]
        # Encontrar el log de este endpoint
        endpoint = f"/cases/{ctx['case']['case_id']}/ai/profile-analysis"
        relevant = [lg for lg in logs if lg["endpoint"] == endpoint]
        assert len(relevant) == 1
        assert relevant[0]["validation_status"] == "api_error"
        assert relevant[0]["error_message"] is not None

    def test_does_not_create_analysis(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client(failing=True)
        ctx = _full_chain_with_kyc(client)
        _post_analysis(client, ctx["case"]["case_id"])
        body = client.get(
            f"/cases/{ctx['case']['case_id']}/ai/profile-analysis",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert body["count"] == 0

    def test_does_not_create_audit_event(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client(failing=True)
        ctx = _full_chain_with_kyc(client)
        _post_analysis(client, ctx["case"]["case_id"])
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "ai_profile_analyzed" not in types


# ─────────────────────────────────────────────────────────────────────────────
# No regression
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRegression:
    def test_health(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200

    def test_auth_me(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert r.status_code == 200
        assert r.json()["advisor_id"] == "ADV-CPA-001"

    def test_advisor_profile_approval(self, client: TestClient) -> None:
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

    def test_filtered_portfolio_demo_no_auth(
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
        assert r.status_code != 401
