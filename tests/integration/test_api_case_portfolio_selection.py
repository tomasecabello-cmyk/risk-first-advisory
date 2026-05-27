"""
Integration tests for Phase 2 case-scoped PortfolioSelection.

Cubre:
    POST /cases/{case_id}/portfolio-selection  — selección final del advisor.
    GET  /cases/{case_id}/portfolio-selection  — listado por case.

Persistencia:
    - Migrations 0001..0008 corridas en DB temporal.
    - selection vincula (case_id, proposal_id, override_approval_id, candidate).
    - actualiza advisory_cases.current_portfolio_selection_id.
    - transiciona status IN_PROGRESS → PORTFOLIO_SELECTED.
    - AuditEvent portfolio_selected.

OpenAI se monkeypatchea para el AI profile analysis (profile=moderado para
que GROWTH requiera override en al menos un test).
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
    advisor_id: ADM-SEL-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-SEL-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-SEL-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-SEL-001
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
def _setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, raising=False)
    monkeypatch.setattr(
        _tokens_module, "DEFAULT_ADVISOR_TOKENS_PATH", tmp_path / "absent.yaml"
    )
    tokens_yaml = tmp_path / "sel_tokens.yaml"
    tokens_yaml.write_text(_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def sel_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "sel_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI (profile=moderado para que GROWTH requiera override)
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
    return {"display_name": "SEL Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id, "display_name": "SEL Advisor",
        "email": "a@sel.com", "roles": ["advisor"], **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id, "primary_advisor_id": advisor_id,
        "display_name": "SEL Client", **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id, "client_id": client_id,
        "lead_advisor_id": advisor_id, "title": "SEL Case", **kw,
    }


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


def _create_firm(c: TestClient, **kw: Any) -> dict:
    r = c.post("/firms", json=_firm_body(**kw), headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_advisor(c: TestClient, firm_id: str, **kw: Any) -> dict:
    r = c.post("/advisors", json=_advisor_body(firm_id, **kw),
               headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_client(c: TestClient, firm_id: str, advisor_id: str, **kw: Any) -> dict:
    r = c.post("/clients", json=_client_body(firm_id, advisor_id, **kw),
               headers={"Authorization": _ADMIN})
    assert r.status_code == 201, r.text
    return r.json()


def _create_case(c: TestClient, firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    r = c.post("/cases", json=_case_body(firm_id, client_id, advisor_id, **kw),
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_kyc(c: TestClient, case_id: str, **overrides) -> dict:
    r = c.post(f"/cases/{case_id}/kyc", json=_kyc_body(**overrides),
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_analysis(c: TestClient, case_id: str) -> dict:
    r = c.post(f"/cases/{case_id}/ai/profile-analysis", json={},
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_approval(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(f"/cases/{case_id}/profile-approval", json=body,
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_pref(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(f"/cases/{case_id}/investment-preferences", json=body,
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_filter(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(f"/cases/{case_id}/universe-filter", json=body,
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_proposal(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(f"/cases/{case_id}/portfolio-proposal", json=body,
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_override(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(f"/cases/{case_id}/override-approval", json=body,
               headers={"Authorization": _ADVISOR})
    assert r.status_code == 201, r.text
    return r.json()


def _post_selection(c: TestClient, case_id: str, **body) -> Any:
    return c.post(
        f"/cases/{case_id}/portfolio-selection", json=body,
        headers={"Authorization": _ADVISOR},
    )


def _full_setup(c: TestClient, patch_ai_client) -> dict:
    """Pipeline completo hasta tener un proposal completed (sin selection todavía)."""
    patch_ai_client()
    firm = _create_firm(c)
    adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-SEL-001")
    cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
    case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    _post_kyc(c, case["case_id"])
    _post_analysis(c, case["case_id"])
    approval = _post_approval(c, case["case_id"], decision="approve", rationale="ok")
    pref = _post_pref(c, case["case_id"], structured_preferences=_BROAD_PREFS)
    filter_run = _post_filter(c, case["case_id"])
    proposal = _post_proposal(c, case["case_id"])
    return {
        "case": case, "approval": approval, "preference": pref,
        "filter_run": filter_run, "proposal": proposal,
    }


def _find_non_override_variant(proposal: dict) -> str | None:
    for c in proposal["candidates"]:
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is False:
            return c.get("variant")
    return None


def _find_override_variant(proposal: dict) -> str | None:
    for c in proposal["candidates"]:
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is True:
            return c.get("variant")
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Create — variant que NO requiere override
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateNoOverride:
    def test_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        assert variant is not None, "Fixture must contain a non-override variant"
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant,
            rationale="Cliente prefiere esta variante.",
        )
        assert r.status_code == 201, r.text

    def test_selection_id_prefix(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.json()["selection_id"].startswith("case_portfolio_selection_")

    def test_proposal_id_in_response(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.json()["proposal_id"] == ctx["proposal"]["proposal_id"]

    def test_selected_variant_in_response(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.json()["selected_variant"] == variant

    def test_selected_candidate_not_empty(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        cand = r.json()["selected_candidate"]
        assert cand["variant"] == variant
        assert "weights" in cand
        assert "expected_return_annual" in cand

    def test_override_approval_id_none(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.json()["override_approval_id"] is None

    def test_advisor_id_from_entity(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.json()["advisor_id"] == "ADV-SEL-001"

    def test_is_current_true(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.json()["is_current"] is True

    def test_get_lists_one(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_case_current_portfolio_selection_id_updated(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        sel_id = r.json()["selection_id"]
        case_after = client.get(
            f"/cases/{ctx['case']['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["current_portfolio_selection_id"] == sel_id

    def test_case_status_transitions_to_portfolio_selected(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        case_after = client.get(
            f"/cases/{ctx['case']['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["status"] == "PORTFOLIO_SELECTED"


# ═════════════════════════════════════════════════════════════════════════════
# Create — variant que SÍ requiere override
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateWithOverride:
    def test_growth_without_override_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        assert variant is not None, "Fixture must contain an override-required variant"
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.status_code == 409
        assert "requires an approved override" in r.json()["detail"]

    def test_growth_with_explicit_override_201(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        ovr = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="approve",
            rationale="ok",
        )
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant,
            override_approval_id=ovr["override_approval_id"],
            rationale="Cliente acepta el override.",
        )
        assert r.status_code == 201, r.text
        assert r.json()["override_approval_id"] == ovr["override_approval_id"]

    def test_growth_uses_current_approved_override_when_id_omitted(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        ovr = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="approve", rationale="ok",
        )
        # No pasamos override_approval_id; el endpoint debe usar el current.
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        assert r.status_code == 201, r.text
        assert r.json()["override_approval_id"] == ovr["override_approval_id"]


# ═════════════════════════════════════════════════════════════════════════════
# Current management
# ═════════════════════════════════════════════════════════════════════════════


class TestCurrent:
    def test_second_marks_first_not_current(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        non_override = _find_non_override_variant(ctx["proposal"])
        # Para tener 2 selections necesitamos 2 variants distintos sin override
        # (si solo hay 1 non-override, hacemos 2 selections sobre el mismo).
        first = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=non_override, rationale="ok",
        ).json()
        second = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=non_override, rationale="reconsidero",
        ).json()
        body = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            headers={"Authorization": _ADVISOR},
        ).json()
        flags = {s["selection_id"]: s["is_current"] for s in body["selections"]}
        assert flags[first["selection_id"]] is False
        assert flags[second["selection_id"]] is True

    def test_current_pointer_updates_to_latest(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        non_override = _find_non_override_variant(ctx["proposal"])
        _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=non_override, rationale="first",
        )
        second = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=non_override, rationale="second",
        ).json()
        case_after = client.get(
            f"/cases/{ctx['case']['case_id']}",
            headers={"Authorization": _ADVISOR},
        ).json()
        assert case_after["current_portfolio_selection_id"] == second["selection_id"]


# ═════════════════════════════════════════════════════════════════════════════
# Validation
# ═════════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_missing_case_post_404(self, client: TestClient) -> None:
        r = client.post(
            "/cases/case_nope/portfolio-selection",
            json={"selected_variant": "BALANCED", "rationale": "ok"},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_missing_case_get_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/portfolio-selection",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404

    def test_closed_case_409(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        case_id = ctx["case"]["case_id"]
        non_override = _find_non_override_variant(ctx["proposal"])
        # transition a CLOSED requiere pasar por PORTFOLIO_SELECTED primero.
        _post_selection(
            client, case_id,
            selected_variant=non_override, rationale="ok",
        )
        client.patch(
            f"/cases/{case_id}/status", json={"status": "CLOSED"},
            headers={"Authorization": _ADVISOR},
        )
        r = _post_selection(
            client, case_id,
            selected_variant=non_override, rationale="ok",
        )
        assert r.status_code == 409

    def test_no_proposal_409(self, client: TestClient) -> None:
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"], advisor_id="ADV-SEL-001")
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        r = _post_selection(
            client, case["case_id"],
            selected_variant="BALANCED", rationale="ok",
        )
        assert r.status_code == 409
        assert "no portfolio proposal" in r.json()["detail"].lower()

    def test_proposal_id_from_other_case_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx_a = _full_setup(client, patch_ai_client)
        firm = ctx_a["case"]["firm_id"]
        adv_id = ctx_a["case"]["lead_advisor_id"]
        cli_id = ctx_a["case"]["client_id"]
        case_b = client.post(
            "/cases",
            json=_case_body(firm, cli_id, adv_id, title="Case B"),
            headers={"Authorization": _ADVISOR},
        ).json()
        _post_kyc(client, case_b["case_id"])
        _post_analysis(client, case_b["case_id"])
        _post_approval(client, case_b["case_id"], decision="approve", rationale="ok")
        _post_pref(client, case_b["case_id"], structured_preferences=_BROAD_PREFS)
        _post_filter(client, case_b["case_id"])
        _post_proposal(client, case_b["case_id"])
        non_override_a = _find_non_override_variant(ctx_a["proposal"]) or "BALANCED"
        r = _post_selection(
            client, case_b["case_id"],
            proposal_id=ctx_a["proposal"]["proposal_id"],
            selected_variant=non_override_a, rationale="ok",
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_selected_variant_not_in_proposal_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        # Variants generadas; pedimos una que falte si la hay.
        variants_present = {c["variant"] for c in ctx["proposal"]["candidates"]}
        missing = {"DEFENSIVE", "BALANCED", "GROWTH"} - variants_present
        if not missing:
            pytest.skip("Fixture proposal contains all 3 variants.")
        target = next(iter(missing))
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=target, rationale="ok",
        )
        assert r.status_code == 422

    def test_override_rejected_decision_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        ovr = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="reject", rationale="no",
        )
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant,
            override_approval_id=ovr["override_approval_id"],
            rationale="ok",
        )
        assert r.status_code == 409
        assert "decision='approve'" in r.json()["detail"]

    def test_override_from_other_case_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx_a = _full_setup(client, patch_ai_client)
        variant_a = _find_override_variant(ctx_a["proposal"])
        ovr_a = _post_override(
            client, ctx_a["case"]["case_id"],
            candidate_variant=variant_a, decision="approve", rationale="ok",
        )
        # Setup case B con proposal
        firm = ctx_a["case"]["firm_id"]
        adv_id = ctx_a["case"]["lead_advisor_id"]
        cli_id = ctx_a["case"]["client_id"]
        case_b = client.post(
            "/cases",
            json=_case_body(firm, cli_id, adv_id, title="Case B"),
            headers={"Authorization": _ADVISOR},
        ).json()
        _post_kyc(client, case_b["case_id"])
        _post_analysis(client, case_b["case_id"])
        _post_approval(client, case_b["case_id"], decision="approve", rationale="ok")
        _post_pref(client, case_b["case_id"], structured_preferences=_BROAD_PREFS)
        _post_filter(client, case_b["case_id"])
        proposal_b = _post_proposal(client, case_b["case_id"])
        variant_b = _find_override_variant(proposal_b) or variant_a
        r = _post_selection(
            client, case_b["case_id"],
            selected_variant=variant_b,
            override_approval_id=ovr_a["override_approval_id"],
            rationale="ok",
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_override_from_other_proposal_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        ovr = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="approve", rationale="ok",
        )
        # Crear un segundo proposal — el override sigue refiriendo al primero.
        proposal2 = _post_proposal(client, ctx["case"]["case_id"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            proposal_id=proposal2["proposal_id"],
            selected_variant=variant,
            override_approval_id=ovr["override_approval_id"],
            rationale="ok",
        )
        assert r.status_code == 422
        assert "proposal" in r.json()["detail"].lower()

    def test_override_for_other_variant_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variants_with_override: list[str] = []
        for c in ctx["proposal"]["candidates"]:
            meta = c.get("metadata") or {}
            if meta.get("requires_advisor_override") is True:
                variants_with_override.append(c["variant"])
        if len(variants_with_override) < 1:
            pytest.skip("Need at least 1 override-requiring variant.")
        # Crear override sobre uno y tratar de seleccionar otro variant que
        # también requiera override (si hay 2). Si solo hay 1, este test
        # cubre el caso aproximado: pedir DEFENSIVE con override que es para
        # GROWTH.
        target_for_override = variants_with_override[0]
        ovr = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=target_for_override, decision="approve", rationale="ok",
        )
        # Buscar otro variant (cualquier otro) que esté en candidates pero
        # diferente del target.
        other_variant = next(
            (c["variant"] for c in ctx["proposal"]["candidates"]
             if c["variant"] != target_for_override),
            None,
        )
        if other_variant is None:
            pytest.skip("Proposal has only one variant.")
        # Si el otro variant no requiere override, la respuesta esperada es
        # 422 "does not require advisor override" en vez de "is for candidate".
        # Igualmente verifica que el sistema lo rechaza.
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=other_variant,
            override_approval_id=ovr["override_approval_id"],
            rationale="ok",
        )
        assert r.status_code == 422

    def test_non_override_variant_with_override_id_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        non_override = _find_non_override_variant(ctx["proposal"])
        override_variant = _find_override_variant(ctx["proposal"])
        if non_override is None or override_variant is None:
            pytest.skip("Need both override and non-override variants.")
        # Crear un override approval (sobre el variant que sí requiere) y
        # tratar de usarlo en una selection del variant que NO requiere.
        ovr = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=override_variant, decision="approve", rationale="ok",
        )
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=non_override,
            override_approval_id=ovr["override_approval_id"],
            rationale="ok",
        )
        assert r.status_code == 422
        assert "does not require advisor override" in r.json()["detail"]

    def test_rationale_whitespace_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant="BALANCED", rationale="   ",
        )
        assert r.status_code == 422

    def test_source_whitespace_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant="BALANCED", rationale="ok", source="   ",
        )
        assert r.status_code == 422

    def test_selected_variant_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant="UNKNOWN", rationale="ok",
        )
        assert r.status_code == 422

    def test_proposal_id_unknown_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_selection(
            client, ctx["case"]["case_id"],
            proposal_id="case_portfolio_proposal_NOPE",
            selected_variant="BALANCED", rationale="ok",
        )
        assert r.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════════════════


class TestRBACPost:
    def test_no_token_401(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            json={"selected_variant": "BALANCED", "rationale": "ok"},
        )
        assert r.status_code == 401

    def test_compliance_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            json={"selected_variant": "BALANCED", "rationale": "ok"},
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403

    def test_viewer_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            json={"selected_variant": "BALANCED", "rationale": "ok"},
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        non_override = _find_non_override_variant(ctx["proposal"])
        r = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=non_override, rationale="ok",
        )
        assert r.status_code == 201

    def test_admin_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        non_override = _find_non_override_variant(ctx["proposal"])
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            json={"selected_variant": non_override, "rationale": "ok"},
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACGet:
    def test_no_token_401(self, client: TestClient) -> None:
        r = client.get("/cases/case_x/portfolio-selection")
        assert r.status_code == 401

    def test_compliance_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_viewer_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-selection",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Audit
# ═════════════════════════════════════════════════════════════════════════════


class TestAudit:
    def test_event_portfolio_selected(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        sel = _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        ).json()
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "portfolio_selected" in types
        evt = next(e for e in events if e["event_type"] == "portfolio_selected")
        assert evt["payload"]["selection_id"] == sel["selection_id"]
        assert evt["payload"]["selected_variant"] == variant

    def test_audit_chain_intact(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_non_override_variant(ctx["proposal"])
        _post_selection(
            client, ctx["case"]["case_id"],
            selected_variant=variant, rationale="ok",
        )
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/audit/verify",
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 200
        assert r.json()["is_intact"] is True


# ═════════════════════════════════════════════════════════════════════════════
# No regression
# ═════════════════════════════════════════════════════════════════════════════


class TestNoRegression:
    def test_legacy_portfolio_selection(self, client: TestClient) -> None:
        r = client.post(
            "/advisor/portfolio-selection",
            json={
                "client_id": "C-X",
                "selected_variant": "BALANCED",
                "rationale": "ok",
            },
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code != 401
        assert r.status_code != 404

    def test_legacy_filtered_portfolio_demo(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        r = client.post(
            "/ai/filtered-portfolio-demo",
            json={
                "client_id": "C-X", "profile": "moderado",
                "natural_language_preferences": "x",
            },
        )
        assert r.status_code != 401

    def test_health(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200

    def test_auth_me(self, client: TestClient) -> None:
        r = client.get("/auth/me", headers={"Authorization": _ADVISOR})
        assert r.status_code == 200
        assert r.json()["advisor_id"] == "ADV-SEL-001"
