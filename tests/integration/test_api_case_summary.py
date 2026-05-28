"""
Integration tests for Phase 2 case summary endpoint.

Cubre:
    GET /cases/{case_id}/summary  — devuelve estado completo del caso.

Estados testeados:
    - Case nuevo (sin nada todavía).
    - Estados intermedios después de cada paso del workflow.
    - Full workflow completo (todos los current_* presentes).
    - Audit chain roto manualmente → summary.audit.is_intact=false.

OpenAI se monkeypatchea (profile=moderado para que GROWTH requiera override y
podamos testear el path con override approval).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
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


_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-SUM-001
    display_name: Test Admin
    firm_id: null
    roles: [admin]
  test-advisor-token:
    advisor_id: ADV-SUM-001
    display_name: Test Advisor
    firm_id: null
    roles: [advisor]
  test-compliance-token:
    advisor_id: CMP-SUM-001
    display_name: Test Compliance
    firm_id: null
    roles: [compliance]
  test-viewer-token:
    advisor_id: VWR-SUM-001
    display_name: Test Viewer
    firm_id: null
    roles: [viewer]
"""

_ADMIN = "Bearer test-admin-token"
_ADVISOR = "Bearer test-advisor-token"
_COMPLIANCE = "Bearer test-compliance-token"
_VIEWER = "Bearer test-viewer-token"


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "sum_tokens.yaml"
    tokens_yaml.write_text(_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def sum_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "sum_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI (moderado profile → GROWTH requiere override)
# ─────────────────────────────────────────────────────────────────────────────


_MODERADO_KYC_RESPONSE: dict = {
    "preliminary_profile": "moderado",
    "confidence": 0.85,
    "contradictions": [],
    "follow_up_questions": [],
    "advisor_notes": [],
}


def _make_fake_chat(content: str) -> Any:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    cli = MagicMock()
    cli.chat.completions.create.return_value = completion
    return cli


@pytest.fixture
def patch_ai_client(monkeypatch: pytest.MonkeyPatch):
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    def _install(response: dict | None = None) -> None:
        fake = _make_fake_chat(json.dumps(response or _MODERADO_KYC_RESPONSE))
        cli = OpenAIProfileClient(_client=fake)
        monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: cli)

    return _install


# ─────────────────────────────────────────────────────────────────────────────
# Entity helpers
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "SUM Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "display_name": "SUM Advisor",
            "email": "a@sum.com", "roles": ["advisor"], **kw}


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "primary_advisor_id": advisor_id,
            "display_name": "SUM Client", **kw}


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "client_id": client_id,
            "lead_advisor_id": advisor_id, "title": "SUM Case", **kw}


def _kyc_body(**overrides: Any) -> dict:
    base = {
        "age": 42, "risk_tolerance_score": 6, "risk_capacity_score": 7,
        "liquidity_need_score": 3, "investment_horizon_years": 10,
        "investment_experience": "moderada", "income_stability": "stable",
        "net_worth": 500_000.0, "liquid_net_worth": 150_000.0,
        "max_acceptable_drawdown_pct": 20.0,
    }
    base.update(overrides)
    return base


_BROAD_PREFS: dict[str, Any] = {
    "allowed_instrument_types": [
        "ETF", "CORPORATE_BOND", "SOVEREIGN_BOND",
        "STOCK", "CEDEAR", "MUTUAL_FUND", "MONEY_MARKET",
    ],
}


def _post(c: TestClient, path: str, body: dict, token: str = _ADVISOR) -> Any:
    return c.post(path, json=body, headers={"Authorization": token})


def _setup_empty_case(c: TestClient) -> dict:
    """firm + advisor + client + case (sin nada más)."""
    firm = _post(c, "/firms", _firm_body(), _ADMIN).json()
    adv = _post(c, "/advisors", _advisor_body(firm["firm_id"], advisor_id="ADV-SUM-001"), _ADMIN).json()
    cli = _post(c, "/clients", _client_body(firm["firm_id"], adv["advisor_id"]), _ADMIN).json()
    case = _post(c, "/cases", _case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"])).json()
    return {"firm": firm, "advisor": adv, "client": cli, "case": case}


def _find_override_variant(proposal: dict) -> str | None:
    for c in proposal["candidates"]:
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is True:
            return c.get("variant")
    return None


def _find_non_override_variant(proposal: dict) -> str | None:
    for c in proposal["candidates"]:
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is False:
            return c.get("variant")
    return None


def _full_workflow(c: TestClient, patch_ai_client) -> dict:
    """Pipeline completo: empty → KYC → analysis → approval → prefs → filter
    → proposal → override → selection → report."""
    patch_ai_client()
    ctx = _setup_empty_case(c)
    case_id = ctx["case"]["case_id"]
    _post(c, f"/cases/{case_id}/kyc", _kyc_body())
    _post(c, f"/cases/{case_id}/ai/profile-analysis", {})
    _post(c, f"/cases/{case_id}/profile-approval",
          {"decision": "approve", "rationale": "ok"})
    _post(c, f"/cases/{case_id}/investment-preferences",
          {"structured_preferences": _BROAD_PREFS})
    _post(c, f"/cases/{case_id}/universe-filter", {})
    proposal = _post(c, f"/cases/{case_id}/portfolio-proposal", {}).json()
    override_variant = _find_override_variant(proposal)
    # Override approval sobre el variant que lo requiere.
    if override_variant is not None:
        _post(c, f"/cases/{case_id}/override-approval",
              {"candidate_variant": override_variant, "decision": "approve",
               "rationale": "Cliente acepta exceso de riesgo."})
        selection = _post(c, f"/cases/{case_id}/portfolio-selection",
                          {"selected_variant": override_variant,
                           "rationale": "Variante GROWTH con override"}).json()
    else:
        non_override = _find_non_override_variant(proposal)
        assert non_override is not None
        selection = _post(c, f"/cases/{case_id}/portfolio-selection",
                          {"selected_variant": non_override,
                           "rationale": "Variante sin override"}).json()
    _post(c, f"/cases/{case_id}/reports", {})
    ctx["proposal"] = proposal
    ctx["selection"] = selection
    return ctx


def _get_summary(c: TestClient, case_id: str, token: str = _ADVISOR) -> Any:
    return c.get(f"/cases/{case_id}/summary", headers={"Authorization": token})


# ═════════════════════════════════════════════════════════════════════════════
# Empty / new case
# ═════════════════════════════════════════════════════════════════════════════


class TestEmptyCase:
    def test_200(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        r = _get_summary(client, ctx["case"]["case_id"])
        assert r.status_code == 200, r.text

    def test_case_correct(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["case"]["case_id"] == ctx["case"]["case_id"]
        assert body["case"]["status"] == "DRAFT"

    def test_firm_present(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["firm"] is not None
        assert body["firm"]["firm_id"] == ctx["firm"]["firm_id"]

    def test_client_present(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["client"] is not None
        assert body["client"]["client_id"] == ctx["client"]["client_id"]

    def test_lead_advisor_present(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["lead_advisor"] is not None
        assert body["lead_advisor"]["advisor_id"] == ctx["advisor"]["advisor_id"]

    def test_all_current_none(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        for field in (
            "latest_kyc", "latest_ai_profile_analysis",
            "current_profile_approval", "current_investment_preferences",
            "current_universe_filter", "current_portfolio_proposal",
            "current_override_approval", "current_portfolio_selection",
            "current_report",
        ):
            assert body[field] is None, f"{field} should be None on empty case"

    def test_progress_all_false(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        p = body["progress"]
        for flag in (
            "has_kyc", "has_ai_profile_analysis", "has_profile_approval",
            "has_investment_preferences", "has_universe_filter",
            "has_portfolio_proposal", "has_override_approval",
            "has_portfolio_selection", "has_report",
        ):
            assert p[flag] is False, f"{flag} should be False on empty case"

    def test_next_action_submit_kyc(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["progress"]["next_recommended_action"] == "submit_kyc"

    def test_completion_ratio_zero(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["progress"]["completion_ratio"] == 0.0

    def test_audit_intact_after_case_created(self, client: TestClient) -> None:
        # case_created event ya existe; chain debe ser intact.
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["audit"]["is_intact"] is True
        assert body["audit"]["total_events"] >= 1

    def test_ai_logs_count_zero(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["ai"]["ai_logs_count"] == 0
        assert body["ai"]["latest_ai_log_id"] is None


# ═════════════════════════════════════════════════════════════════════════════
# Full workflow
# ═════════════════════════════════════════════════════════════════════════════


class TestFullWorkflow:
    def test_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        r = _get_summary(client, ctx["case"]["case_id"])
        assert r.status_code == 200, r.text

    def test_all_current_present(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        required = [
            "latest_kyc", "latest_ai_profile_analysis",
            "current_profile_approval", "current_investment_preferences",
            "current_universe_filter", "current_portfolio_proposal",
            "current_portfolio_selection", "current_report",
        ]
        for field in required:
            assert body[field] is not None, f"{field} should be present"

    def test_current_report_version_1(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["current_report"]["version"] == 1

    def test_current_portfolio_selection_correct(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["current_portfolio_selection"]["selection_id"] == ctx["selection"]["selection_id"]

    def test_progress_has_report_true(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["progress"]["has_report"] is True

    def test_next_action_ready_for_review(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["progress"]["next_recommended_action"] == "ready_for_review"

    def test_completion_ratio_one(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["progress"]["completion_ratio"] == 1.0

    def test_audit_intact(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        assert body["audit"]["is_intact"] is True

    def test_ai_logs_count_positive(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        body = _get_summary(client, ctx["case"]["case_id"]).json()
        # Al menos 1 (AI profile analysis emite log con case_id).
        assert body["ai"]["ai_logs_count"] >= 1
        assert body["ai"]["latest_ai_log_id"] is not None
        assert body["ai"]["latest_validation_status"] in (
            "parsed_ok", "api_error", "parse_error", "validation_error",
        )

    def test_closed_case_next_action(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        case_id = ctx["case"]["case_id"]
        client.patch(f"/cases/{case_id}/status", json={"status": "CLOSED"},
                     headers={"Authorization": _ADVISOR})
        body = _get_summary(client, case_id).json()
        assert body["progress"]["next_recommended_action"] == "closed"


# ═════════════════════════════════════════════════════════════════════════════
# Intermediate states — next_recommended_action progression
# ═════════════════════════════════════════════════════════════════════════════


class TestIntermediateStates:
    def test_after_kyc_run_ai_profile_analysis(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _setup_empty_case(client)
        case_id = ctx["case"]["case_id"]
        _post(client, f"/cases/{case_id}/kyc", _kyc_body())
        body = _get_summary(client, case_id).json()
        assert body["progress"]["next_recommended_action"] == "run_ai_profile_analysis"
        assert body["progress"]["has_kyc"] is True

    def test_after_analysis_approve_profile(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _setup_empty_case(client)
        case_id = ctx["case"]["case_id"]
        _post(client, f"/cases/{case_id}/kyc", _kyc_body())
        _post(client, f"/cases/{case_id}/ai/profile-analysis", {})
        body = _get_summary(client, case_id).json()
        assert body["progress"]["next_recommended_action"] == "approve_profile"

    def test_after_approval_record_preferences(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _setup_empty_case(client)
        case_id = ctx["case"]["case_id"]
        _post(client, f"/cases/{case_id}/kyc", _kyc_body())
        _post(client, f"/cases/{case_id}/ai/profile-analysis", {})
        _post(client, f"/cases/{case_id}/profile-approval",
              {"decision": "approve", "rationale": "ok"})
        body = _get_summary(client, case_id).json()
        assert body["progress"]["next_recommended_action"] == "record_investment_preferences"

    def test_after_prefs_run_universe_filter(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _setup_empty_case(client)
        case_id = ctx["case"]["case_id"]
        _post(client, f"/cases/{case_id}/kyc", _kyc_body())
        _post(client, f"/cases/{case_id}/ai/profile-analysis", {})
        _post(client, f"/cases/{case_id}/profile-approval",
              {"decision": "approve", "rationale": "ok"})
        _post(client, f"/cases/{case_id}/investment-preferences",
              {"structured_preferences": _BROAD_PREFS})
        body = _get_summary(client, case_id).json()
        assert body["progress"]["next_recommended_action"] == "run_universe_filter"

    def test_after_filter_generate_proposal(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _setup_empty_case(client)
        case_id = ctx["case"]["case_id"]
        _post(client, f"/cases/{case_id}/kyc", _kyc_body())
        _post(client, f"/cases/{case_id}/ai/profile-analysis", {})
        _post(client, f"/cases/{case_id}/profile-approval",
              {"decision": "approve", "rationale": "ok"})
        _post(client, f"/cases/{case_id}/investment-preferences",
              {"structured_preferences": _BROAD_PREFS})
        _post(client, f"/cases/{case_id}/universe-filter", {})
        body = _get_summary(client, case_id).json()
        assert body["progress"]["next_recommended_action"] == "generate_portfolio_proposal"

    def test_after_proposal_review_override_or_select(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """Si el proposal tiene candidate que requiere override → review_override;
        si no → select_portfolio."""
        patch_ai_client()
        ctx = _setup_empty_case(client)
        case_id = ctx["case"]["case_id"]
        _post(client, f"/cases/{case_id}/kyc", _kyc_body())
        _post(client, f"/cases/{case_id}/ai/profile-analysis", {})
        _post(client, f"/cases/{case_id}/profile-approval",
              {"decision": "approve", "rationale": "ok"})
        _post(client, f"/cases/{case_id}/investment-preferences",
              {"structured_preferences": _BROAD_PREFS})
        _post(client, f"/cases/{case_id}/universe-filter", {})
        proposal = _post(client, f"/cases/{case_id}/portfolio-proposal", {}).json()
        body = _get_summary(client, case_id).json()
        if _find_override_variant(proposal) is not None:
            assert body["progress"]["next_recommended_action"] == "review_override"
        else:
            assert body["progress"]["next_recommended_action"] == "select_portfolio"

    def test_after_selection_generate_report(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        ctx = _setup_empty_case(client)
        case_id = ctx["case"]["case_id"]
        _post(client, f"/cases/{case_id}/kyc", _kyc_body())
        _post(client, f"/cases/{case_id}/ai/profile-analysis", {})
        _post(client, f"/cases/{case_id}/profile-approval",
              {"decision": "approve", "rationale": "ok"})
        _post(client, f"/cases/{case_id}/investment-preferences",
              {"structured_preferences": _BROAD_PREFS})
        _post(client, f"/cases/{case_id}/universe-filter", {})
        proposal = _post(client, f"/cases/{case_id}/portfolio-proposal", {}).json()
        override_variant = _find_override_variant(proposal)
        if override_variant is not None:
            _post(client, f"/cases/{case_id}/override-approval",
                  {"candidate_variant": override_variant, "decision": "approve",
                   "rationale": "ok"})
            _post(client, f"/cases/{case_id}/portfolio-selection",
                  {"selected_variant": override_variant, "rationale": "ok"})
        else:
            non_override = _find_non_override_variant(proposal)
            _post(client, f"/cases/{case_id}/portfolio-selection",
                  {"selected_variant": non_override, "rationale": "ok"})
        body = _get_summary(client, case_id).json()
        assert body["progress"]["next_recommended_action"] == "generate_report"


# ═════════════════════════════════════════════════════════════════════════════
# Audit broken in DB
# ═════════════════════════════════════════════════════════════════════════════


class TestAuditBroken:
    def test_corrupted_payload_returns_is_intact_false(
        self, client: TestClient, patch_ai_client, sum_db: Path
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        case_id = ctx["case"]["case_id"]
        # Mutar el payload_json del primer evento.
        conn = sqlite3.connect(str(sum_db))
        try:
            conn.execute(
                "UPDATE audit_events SET payload_json = ? WHERE case_id = ? AND sequence = 1",
                ('{"tampered":true}', case_id),
            )
            conn.commit()
        finally:
            conn.close()
        body = _get_summary(client, case_id).json()
        assert body["audit"]["is_intact"] is False
        assert body["audit"]["first_broken_sequence"] is not None


# ═════════════════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════════════════


class TestRBAC:
    def test_no_token_401(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        r = client.get(f"/cases/{ctx['case']['case_id']}/summary")
        assert r.status_code == 401

    def test_advisor_200(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        r = _get_summary(client, ctx["case"]["case_id"], token=_ADVISOR)
        assert r.status_code == 200

    def test_admin_200(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        r = _get_summary(client, ctx["case"]["case_id"], token=_ADMIN)
        assert r.status_code == 200

    def test_compliance_200(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        r = _get_summary(client, ctx["case"]["case_id"], token=_COMPLIANCE)
        assert r.status_code == 200

    def test_viewer_200(self, client: TestClient) -> None:
        ctx = _setup_empty_case(client)
        r = _get_summary(client, ctx["case"]["case_id"], token=_VIEWER)
        assert r.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Validation
# ═════════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_missing_case_404(self, client: TestClient) -> None:
        r = _get_summary(client, "case_nope")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()


# ═════════════════════════════════════════════════════════════════════════════
# No regression
# ═════════════════════════════════════════════════════════════════════════════


class TestNoRegression:
    def test_reports_endpoint_works(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200

    def test_portfolio_selection_endpoint_works(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_workflow(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200

    def test_health(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    def test_auth_me(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert r.status_code == 200
        assert r.json()["advisor_id"] == "ADV-SUM-001"
