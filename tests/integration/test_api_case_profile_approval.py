"""
Integration tests for Phase 2 case-scoped AdvisorProfileApproval.

Cubre:
    POST /cases/{case_id}/profile-approval  — advisor decide approve/modify/reject.
    GET  /cases/{case_id}/profile-approval  — listado por caso.

Persistencia:
    - Migrations 0001..0004 corridas en DB temporal.
    - approval vinculado a (case_id, ai_profile_analysis_id, kyc_submission_id,
      advisor_id).
    - is_current management: approve/modify marca previous=0, reject=0 desde
      el insert.
    - current_approved_profile_id del case: approve/modify lo actualizan;
      reject no lo toca.
    - AuditEvent advisor_profile_approved / _modified / _rejected.

OpenAI se monkeypatchea para crear el AIProfileAnalysis.
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
# Tokens
# ─────────────────────────────────────────────────────────────────────────────

_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-CPA10-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-CPA10-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-CPA10-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-CPA10-001
    display_name: Test Viewer
    firm_id: null
    roles:
      - viewer
"""

_ADMIN = "Bearer test-admin-token"
_ADVISOR = "Bearer test-advisor-token"
_COMPLIANCE = "Bearer test-compliance-token"
_VIEWER = "Bearer test-viewer-token"
_RBAC_403 = "Advisor role is not authorized for this action."


# ─────────────────────────────────────────────────────────────────────────────
# Autouse fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "cpa10_tokens.yaml"
    tokens_yaml.write_text(_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def cpa10_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "cpa10_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI
# ─────────────────────────────────────────────────────────────────────────────


_VALID_KYC_RESPONSE: dict = {
    "preliminary_profile": "moderado",
    "confidence": 0.78,
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
        fake = _make_fake_chat(json.dumps(response or _VALID_KYC_RESPONSE))
        ai = OpenAIProfileClient(_client=fake)
        monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: ai)

    return _install


# ─────────────────────────────────────────────────────────────────────────────
# Entity helpers
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "CPA10 Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "display_name": "CPA10 Advisor",
        "email": "a@cpa10.com",
        "roles": ["advisor"],
        **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "primary_advisor_id": advisor_id,
        "display_name": "CPA10 Client",
        **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "lead_advisor_id": advisor_id,
        "title": "CPA10 Case",
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
    }
    base.update(overrides)
    return base


def _create_firm(c: TestClient, **kw: Any) -> dict:
    r = c.post("/firms", json=_firm_body(**kw), headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_advisor(c: TestClient, firm_id: str, **kw: Any) -> dict:
    r = c.post(
        "/advisors", json=_advisor_body(firm_id, **kw), headers={"Authorization": _ADMIN}
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


def _post_kyc(c: TestClient, case_id: str, **overrides) -> dict:
    r = c.post(
        f"/cases/{case_id}/kyc",
        json=_kyc_body(**overrides),
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _post_analysis(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(
        f"/cases/{case_id}/ai/profile-analysis",
        json=body,
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _post_approval(c: TestClient, case_id: str, **body) -> Any:
    return c.post(
        f"/cases/{case_id}/profile-approval",
        json=body,
        headers={"Authorization": _ADVISOR},
    )


def _full_chain(c: TestClient, patch_ai_client) -> dict:
    """firm + advisor (ADV-CPA10-001) + client + case + KYC + analysis."""
    patch_ai_client()
    firm = _create_firm(c)
    adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-CPA10-001")
    cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
    case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    kyc = _post_kyc(c, case["case_id"])
    analysis = _post_analysis(c, case["case_id"])
    return {"case": case, "kyc": kyc, "analysis": analysis}


# ─────────────────────────────────────────────────────────────────────────────
# Create approve
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateApprove:
    def test_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="Perfil consistente con KYC.",
        )
        assert r.status_code == 201, r.text

    def test_approval_id_prefix(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="Perfil ok.",
        )
        assert r.json()["approval_id"].startswith("advisor_profile_approval_")

    def test_case_id_in_response(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["case_id"] == ctx["case"]["case_id"]

    def test_ai_profile_analysis_id_auto(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["ai_profile_analysis_id"] == ctx["analysis"]["analysis_id"]

    def test_kyc_submission_id_inherited_from_analysis(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["kyc_submission_id"] == ctx["kyc"]["kyc_submission_id"]

    def test_advisor_id_from_entity(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["advisor_id"] == "ADV-CPA10-001"

    def test_decision_is_approve(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["decision"] == "approve"

    def test_proposed_profile_derived(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["proposed_profile"] == "moderado"

    def test_approved_profile_auto_fills_to_proposed(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["approved_profile"] == "moderado"

    def test_rationale_persisted(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="Razón concreta del asesor.",
        )
        assert r.json()["rationale"] == "Razón concreta del asesor."

    def test_is_current_true(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.json()["is_current"] is True

    def test_get_lists_one(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_case_current_approved_profile_id_updated(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        approval_id = r.json()["approval_id"]
        case_after = client.get(
            f"/cases/{ctx['case']['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["current_approved_profile_id"] == approval_id


# ─────────────────────────────────────────────────────────────────────────────
# Modify
# ─────────────────────────────────────────────────────────────────────────────


class TestCreateModify:
    def test_modify_with_valid_approved_profile(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="modify",
            approved_profile="conservador",
            rationale="Cliente intolerante a drawdowns.",
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["decision"] == "modify"
        assert body["approved_profile"] == "conservador"
        assert body["proposed_profile"] == "moderado"

    def test_current_approved_profile_id_points_to_modify(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        # primero approve
        first = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        ).json()
        # luego modify
        modify = _post_approval(
            client, ctx["case"]["case_id"],
            decision="modify",
            approved_profile="moderado-defensivo",
            rationale="Reajuste.",
        ).json()
        case_after = client.get(
            f"/cases/{ctx['case']['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["current_approved_profile_id"] == modify["approval_id"]
        assert case_after["current_approved_profile_id"] != first["approval_id"]

    def test_previous_approval_is_current_false(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        first = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        ).json()
        _post_approval(
            client, ctx["case"]["case_id"],
            decision="modify",
            approved_profile="moderado-defensivo",
            rationale="ok",
        )
        lst = client.get(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            headers={"Authorization": _ADVISOR},
        ).json()
        flags = {a["approval_id"]: a["is_current"] for a in lst["approvals"]}
        assert flags[first["approval_id"]] is False


# ─────────────────────────────────────────────────────────────────────────────
# Reject
# ─────────────────────────────────────────────────────────────────────────────


class TestReject:
    def test_reject_without_approved_profile(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="reject",
            rationale="No procede.",
        )
        assert r.status_code == 201, r.text
        assert r.json()["approved_profile"] is None
        assert r.json()["is_current"] is False

    def test_reject_with_approved_profile_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="reject",
            approved_profile="moderado",
            rationale="No procede.",
        )
        assert r.status_code == 422

    def test_reject_does_not_overwrite_previous_approved(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        first = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        ).json()
        _post_approval(
            client, ctx["case"]["case_id"],
            decision="reject",
            rationale="Reconsidero.",
        )
        case_after = client.get(
            f"/cases/{ctx['case']['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["current_approved_profile_id"] == first["approval_id"]


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_missing_case_post_404(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        r = client.post(
            "/cases/case_nope/profile-approval",
            json={"decision": "approve", "rationale": "x", "proposed_profile": "moderado"},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_missing_case_get_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/profile-approval",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404

    def test_closed_case_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        case_id = ctx["case"]["case_id"]
        # case ya está IN_PROGRESS por el POST KYC en _full_chain.
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
        r = _post_approval(
            client, case_id, decision="approve", rationale="ok"
        )
        assert r.status_code == 409
        assert "CLOSED" in r.json()["detail"]

    def test_analysis_id_unknown_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            ai_profile_analysis_id="ai_profile_analysis_nope",
            decision="approve",
            rationale="ok",
        )
        assert r.status_code == 422

    def test_analysis_id_from_other_case_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx_a = _full_chain(client, patch_ai_client)
        # case B con su análisis
        firm = ctx_a["case"]["firm_id"]
        adv_id = ctx_a["case"]["lead_advisor_id"]
        client_id = ctx_a["case"]["client_id"]
        case_b = client.post(
            "/cases",
            json=_case_body(firm, client_id, adv_id, title="Case B"),
            headers={"Authorization": _ADVISOR},
        ).json()
        _post_kyc(client, case_b["case_id"])
        _post_analysis(client, case_b["case_id"])
        # Usar análisis del case A en case B
        r = _post_approval(
            client, case_b["case_id"],
            ai_profile_analysis_id=ctx_a["analysis"]["analysis_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_kyc_submission_id_from_other_case_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx_a = _full_chain(client, patch_ai_client)
        firm = ctx_a["case"]["firm_id"]
        adv_id = ctx_a["case"]["lead_advisor_id"]
        client_id = ctx_a["case"]["client_id"]
        case_b = client.post(
            "/cases",
            json=_case_body(firm, client_id, adv_id, title="Case B"),
            headers={"Authorization": _ADVISOR},
        ).json()
        _post_kyc(client, case_b["case_id"])
        r = _post_approval(
            client, case_b["case_id"],
            kyc_submission_id=ctx_a["kyc"]["kyc_submission_id"],
            decision="approve",
            rationale="ok",
            proposed_profile="moderado",
        )
        assert r.status_code == 422

    def test_proposed_profile_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
            proposed_profile="not_a_profile",
        )
        assert r.status_code == 422

    def test_approved_profile_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="modify",
            approved_profile="not_a_profile",
            rationale="ok",
        )
        assert r.status_code == 422

    def test_approve_with_different_approved_profile_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            approved_profile="conservador",
            rationale="ok",
            proposed_profile="moderado",
        )
        assert r.status_code == 422

    def test_modify_without_approved_profile_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="modify",
            rationale="ok",
        )
        assert r.status_code == 422

    def test_rationale_whitespace_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="   ",
        )
        assert r.status_code == 422

    def test_decision_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="maybe",
            rationale="ok",
        )
        assert r.status_code == 422

    def test_proposed_profile_required_when_no_ai_analysis_422(
        self, client: TestClient
    ) -> None:
        # case sin análisis
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"], advisor_id="ADV-CPA10-001")
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        r = _post_approval(
            client, case["case_id"],
            decision="approve",
            rationale="ok",
        )
        assert r.status_code == 422
        assert "proposed_profile" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Audit
# ─────────────────────────────────────────────────────────────────────────────


class TestAudit:
    def test_approve_emits_advisor_profile_approved(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "advisor_profile_approved" in types
        evt = next(e for e in events if e["event_type"] == "advisor_profile_approved")
        assert evt["payload"]["approval_id"] == r.json()["approval_id"]
        assert evt["payload"]["decision"] == "approve"

    def test_modify_emits_advisor_profile_modified(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        _post_approval(
            client, ctx["case"]["case_id"],
            decision="modify",
            approved_profile="conservador",
            rationale="ok",
        )
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "advisor_profile_modified" in types

    def test_reject_emits_advisor_profile_rejected(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        _post_approval(
            client, ctx["case"]["case_id"],
            decision="reject",
            rationale="No procede.",
        )
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "advisor_profile_rejected" in types

    def test_audit_chain_intact(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_chain(client, patch_ai_client)
        _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve",
            rationale="ok",
        )
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
    def test_no_token_401(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            json={"decision": "approve", "rationale": "ok"},
        )
        assert r.status_code == 401

    def test_compliance_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            json={"decision": "approve", "rationale": "ok"},
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403

    def test_viewer_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            json={"decision": "approve", "rationale": "ok"},
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = _post_approval(
            client, ctx["case"]["case_id"],
            decision="approve", rationale="ok",
        )
        assert r.status_code == 201

    def test_admin_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            json={"decision": "approve", "rationale": "ok"},
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACGet:
    def test_no_token_401(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.get(f"/cases/{ctx['case']['case_id']}/profile-approval")
        assert r.status_code == 401

    def test_compliance_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_viewer_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200

    def test_advisor_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200

    def test_admin_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_chain(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/profile-approval",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# No regression
# ─────────────────────────────────────────────────────────────────────────────


class TestNoRegression:
    def test_legacy_advisor_profile_approval(self, client: TestClient) -> None:
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

    def test_health(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    def test_auth_me(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert r.status_code == 200
        assert r.json()["advisor_id"] == "ADV-CPA10-001"

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


# ─────────────────────────────────────────────────────────────────────────────
# Tope determinístico: el marco (capacidad) acota a la IA
# ─────────────────────────────────────────────────────────────────────────────


class TestFrameworkCeiling:
    """El perfil aprobado no puede superar el tope de capacidad sin override."""

    def _low_capacity_case(self, c: TestClient, patch_ai_client) -> dict:
        # KYC de baja capacidad financiera → tope determinístico = conservador.
        patch_ai_client()
        firm = _create_firm(c)
        adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-CPA10-001")
        cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
        case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        _post_kyc(c, case["case_id"], risk_capacity_score=1,
                  investment_horizon_years=1, liquidity_need_score=9)
        _post_analysis(c, case["case_id"])
        return case

    def test_exceeding_ceiling_without_override_is_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        case = self._low_capacity_case(client, patch_ai_client)
        r = _post_approval(client, case["case_id"], decision="modify",
                           approved_profile="agresivo",
                           rationale="el cliente quiere agresivo")
        assert r.status_code == 409
        assert "tope de capacidad" in r.json()["detail"]

    def test_exceeding_ceiling_with_override_is_201(
        self, client: TestClient, patch_ai_client
    ) -> None:
        case = self._low_capacity_case(client, patch_ai_client)
        r = _post_approval(client, case["case_id"], decision="modify",
                           approved_profile="agresivo",
                           rationale="cliente educado en riesgo, insiste y firma",
                           framework_override_acknowledged=True)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["framework_override"] is True
        assert body["framework_ceiling_profile"] == "conservador"

    def test_within_ceiling_no_override(
        self, client: TestClient, patch_ai_client
    ) -> None:
        case = self._low_capacity_case(client, patch_ai_client)
        r = _post_approval(client, case["case_id"], decision="modify",
                           approved_profile="conservador",
                           rationale="coherente con la capacidad")
        assert r.status_code == 201, r.text
        assert r.json()["framework_override"] is False

    def test_override_keeps_audit_chain_intact(
        self, client: TestClient, patch_ai_client
    ) -> None:
        case = self._low_capacity_case(client, patch_ai_client)
        _post_approval(client, case["case_id"], decision="modify",
                       approved_profile="agresivo", rationale="override firmado",
                       framework_override_acknowledged=True)
        ver = client.get(f"/cases/{case['case_id']}/audit/verify",
                         headers={"Authorization": _COMPLIANCE})
        assert ver.status_code == 200
        assert ver.json()["is_intact"] is True
