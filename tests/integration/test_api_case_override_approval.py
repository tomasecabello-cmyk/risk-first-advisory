"""
Integration tests for Phase 2 case-scoped advisor override approvals.

Cubre:
    POST /cases/{case_id}/override-approval  — advisor decide sobre una
                                                 variant que requiere override.
    GET  /cases/{case_id}/override-approval  — listado por case.

Persistencia:
    - Migrations 0001..0007 corridas en DB temporal.
    - Override approval anclada a (case_id, proposal_id, candidate_variant).
    - is_current management a nivel case.
    - AuditEvents: advisor_override_approved / _rejected.

OpenAI se monkeypatchea para el AI profile analysis del flow case-scoped.
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
    advisor_id: ADM-OVR-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-OVR-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-OVR-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-OVR-001
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
    tokens_yaml = tmp_path / "ovr_tokens.yaml"
    tokens_yaml.write_text(_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def ovr_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "ovr_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI: profile moderado para que GROWTH excedan el presupuesto y
# requiera override (consistente con el comportamiento del /ai/filtered-portfolio-demo
# legacy donde GROWTH típicamente requiere advisor override bajo moderado).
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
    return {"display_name": "OVR Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id, "display_name": "OVR Advisor",
        "email": "a@ovr.com", "roles": ["advisor"], **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id, "primary_advisor_id": advisor_id,
        "display_name": "OVR Client", **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id, "client_id": client_id,
        "lead_advisor_id": advisor_id, "title": "OVR Case", **kw,
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


def _post_override(c: TestClient, case_id: str, **body) -> Any:
    return c.post(
        f"/cases/{case_id}/override-approval", json=body,
        headers={"Authorization": _ADVISOR},
    )


def _full_setup(c: TestClient, patch_ai_client) -> dict:
    """
    Pipeline completo hasta tener un PortfolioProposal completed con al menos
    un candidate que requiere advisor override (típicamente GROWTH bajo
    profile conservador).
    """
    patch_ai_client()
    firm = _create_firm(c)
    adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-OVR-001")
    cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
    case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    _post_kyc(c, case["case_id"])
    _post_analysis(c, case["case_id"])
    approval = _post_approval(
        c, case["case_id"], decision="approve", rationale="ok"
    )
    pref = _post_pref(c, case["case_id"], structured_preferences=_BROAD_PREFS)
    filter_run = _post_filter(c, case["case_id"])
    proposal = _post_proposal(c, case["case_id"])
    return {
        "case": case, "approval": approval, "preference": pref,
        "filter_run": filter_run, "proposal": proposal,
    }


def _find_override_variant(proposal: dict) -> str | None:
    """
    Devuelve el primer variant del proposal cuyo metadata.requires_advisor_override
    sea True. None si ninguno requiere override.
    """
    for c in proposal["candidates"]:
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is True:
            return c.get("variant")
    return None


def _find_non_override_variant(proposal: dict) -> str | None:
    """Devuelve el primer variant que NO requiere override."""
    for c in proposal["candidates"]:
        meta = c.get("metadata") or {}
        if meta.get("requires_advisor_override") is False:
            return c.get("variant")
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Create approve
# ═════════════════════════════════════════════════════════════════════════════


class TestCreateApprove:
    def test_proposal_has_at_least_one_override_variant(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """Guardrail: si el fixture cambia y ningún variant requiere override,
        el resto de los tests se vuelve trivialmente verde con _find devolviendo
        None y los tests dependientes asumiendo otra cosa. Este test rompe
        rápido si esa premisa falla."""
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        assert variant is not None, (
            "No candidate requires advisor override in fixture proposal — "
            "ajustar el setup (profile / preferences) hasta forzar al menos "
            "un override-requiring variant. Candidates: "
            + json.dumps([
                {"variant": c["variant"],
                 "requires_override": c["metadata"]["requires_advisor_override"]}
                for c in ctx["proposal"]["candidates"]
            ])
        )

    def test_approve_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="Cliente acepta el exceso de riesgo informado.",
        )
        assert r.status_code == 201, r.text

    def test_override_approval_id_prefix(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
        )
        assert r.json()["override_approval_id"].startswith("case_override_approval_")

    def test_proposal_id_in_response(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
        )
        assert r.json()["proposal_id"] == ctx["proposal"]["proposal_id"]

    def test_candidate_variant_in_response(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
        )
        assert r.json()["candidate_variant"] == variant

    def test_decision_approve(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
        )
        assert r.json()["decision"] == "approve"

    def test_reason_codes_round_trip(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        codes = ["PORTFOLIO_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET"]
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
            reason_codes=codes,
        )
        assert r.json()["reason_codes"] == codes

    def test_exceeded_constraints_round_trip(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        cons = ["max_volatility", "max_equity"]
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
            exceeded_constraints=cons,
        )
        assert r.json()["exceeded_constraints"] == cons

    def test_advisor_id_from_entity(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
        )
        assert r.json()["advisor_id"] == "ADV-OVR-001"

    def test_is_current_true(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
        )
        assert r.json()["is_current"] is True

    def test_get_lists_one(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="approve",
            rationale="ok",
        )
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# Reject
# ═════════════════════════════════════════════════════════════════════════════


class TestReject:
    def test_reject_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant,
            decision="reject",
            rationale="No procede.",
        )
        assert r.status_code == 201
        assert r.json()["decision"] == "reject"


# ═════════════════════════════════════════════════════════════════════════════
# Current management
# ═════════════════════════════════════════════════════════════════════════════


class TestCurrent:
    def test_second_marks_first_not_current(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        first = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="approve", rationale="ok",
        ).json()
        second = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="reject", rationale="reconsidero",
        ).json()
        body = client.get(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            headers={"Authorization": _ADVISOR},
        ).json()
        flags = {a["override_approval_id"]: a["is_current"] for a in body["override_approvals"]}
        assert flags[first["override_approval_id"]] is False
        assert flags[second["override_approval_id"]] is True


# ═════════════════════════════════════════════════════════════════════════════
# Validation
# ═════════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_missing_case_post_404(self, client: TestClient) -> None:
        r = client.post(
            "/cases/case_nope/override-approval",
            json={"candidate_variant": "GROWTH", "decision": "approve", "rationale": "ok"},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_missing_case_get_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/override-approval",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404

    def test_closed_case_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        case_id = ctx["case"]["case_id"]
        for status in ("PORTFOLIO_SELECTED", "CLOSED"):
            client.patch(
                f"/cases/{case_id}/status", json={"status": status},
                headers={"Authorization": _ADVISOR},
            )
        variant = _find_override_variant(ctx["proposal"]) or "GROWTH"
        r = _post_override(
            client, case_id,
            candidate_variant=variant, decision="approve", rationale="ok",
        )
        assert r.status_code == 409

    def test_no_proposal_409(self, client: TestClient) -> None:
        # case sin proposal
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"], advisor_id="ADV-OVR-001")
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        r = _post_override(
            client, case["case_id"],
            candidate_variant="GROWTH", decision="approve", rationale="ok",
        )
        assert r.status_code == 409
        assert "no portfolio proposal" in r.json()["detail"].lower()

    def test_proposal_id_from_other_case_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx_a = _full_setup(client, patch_ai_client)
        # Crear case B paralelo y obtener su proposal — luego usar el del A
        # contra B → 422.
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
        variant = _find_override_variant(ctx_a["proposal"]) or "GROWTH"
        r = _post_override(
            client, case_b["case_id"],
            proposal_id=ctx_a["proposal"]["proposal_id"],
            candidate_variant=variant, decision="approve", rationale="ok",
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_proposal_unknown_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_override(
            client, ctx["case"]["case_id"],
            proposal_id="case_portfolio_proposal_NOPE",
            candidate_variant="GROWTH", decision="approve", rationale="ok",
        )
        assert r.status_code == 422

    def test_candidate_variant_not_in_proposal_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        # Si el proposal genera DEFENSIVE/BALANCED/GROWTH siempre, ninguno
        # debería faltar — pero el schema acepta solo esos 3. Forcemos un
        # caso edge: borrar GROWTH del proposal vía DB y pedir GROWTH.
        # Más simple: el proposal generalmente genera los 3; probamos un
        # candidate inválido contra el schema (rechazado por el validator)
        # vs contra el lookup. Aquí probamos el lookup: si el proposal
        # tiene solo 1-2 variants, pedimos uno faltante; si tiene los 3,
        # el chequeo se cubre por test_candidate_does_not_require_override.
        variants_in_proposal = {c["variant"] for c in ctx["proposal"]["candidates"]}
        missing = {"DEFENSIVE", "BALANCED", "GROWTH"} - variants_in_proposal
        if missing:
            target = next(iter(missing))
            r = _post_override(
                client, ctx["case"]["case_id"],
                candidate_variant=target, decision="approve", rationale="ok",
            )
            assert r.status_code == 422
        else:
            # Fixture tiene los 3; este branch no aplica.
            pytest.skip("Fixture proposal contains all 3 variants; skip.")

    def test_candidate_does_not_require_override_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        non_override_variant = _find_non_override_variant(ctx["proposal"])
        if non_override_variant is None:
            pytest.skip("Fixture proposal has all candidates requiring override.")
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=non_override_variant,
            decision="approve",
            rationale="ok",
        )
        assert r.status_code == 422
        assert "does not require advisor override" in r.json()["detail"]

    def test_decision_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant="GROWTH", decision="maybe", rationale="ok",
        )
        assert r.status_code == 422

    def test_rationale_whitespace_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant="GROWTH", decision="approve", rationale="   ",
        )
        assert r.status_code == 422

    def test_source_whitespace_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant="GROWTH", decision="approve", rationale="ok",
            source="   ",
        )
        assert r.status_code == 422

    def test_reason_codes_not_list_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant="GROWTH", decision="approve", rationale="ok",
            reason_codes="not_a_list",
        )
        assert r.status_code == 422

    def test_exceeded_constraints_not_list_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant="GROWTH", decision="approve", rationale="ok",
            exceeded_constraints="not_a_list",
        )
        assert r.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════════════════


class TestRBACPost:
    def test_no_token_401(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            json={"candidate_variant": "GROWTH", "decision": "approve", "rationale": "ok"},
        )
        assert r.status_code == 401

    def test_compliance_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            json={"candidate_variant": "GROWTH", "decision": "approve", "rationale": "ok"},
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403

    def test_viewer_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            json={"candidate_variant": "GROWTH", "decision": "approve", "rationale": "ok"},
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="approve", rationale="ok",
        )
        assert r.status_code == 201

    def test_admin_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            json={"candidate_variant": variant, "decision": "approve", "rationale": "ok"},
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACGet:
    def test_no_token_401(self, client: TestClient) -> None:
        r = client.get("/cases/case_x/override-approval")
        assert r.status_code == 401

    def test_compliance_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_viewer_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/override-approval",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Audit
# ═════════════════════════════════════════════════════════════════════════════


class TestAudit:
    def test_approve_emits_advisor_override_approved(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        r = _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="approve", rationale="ok",
        )
        body = r.json()
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "advisor_override_approved" in types
        evt = next(e for e in events if e["event_type"] == "advisor_override_approved")
        assert evt["payload"]["override_approval_id"] == body["override_approval_id"]
        assert evt["payload"]["candidate_variant"] == variant
        assert evt["payload"]["decision"] == "approve"

    def test_reject_emits_advisor_override_rejected(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="reject", rationale="ok",
        )
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "advisor_override_rejected" in types

    def test_audit_chain_intact(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        variant = _find_override_variant(ctx["proposal"])
        _post_override(
            client, ctx["case"]["case_id"],
            candidate_variant=variant, decision="approve", rationale="ok",
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
    def test_legacy_advisor_override_approval(self, client: TestClient) -> None:
        r = client.post(
            "/advisor/override-approval",
            json={
                "client_id": "C-X",
                "candidate_variant": "GROWTH",
                "decision": "approve",
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
        assert r.json()["advisor_id"] == "ADV-OVR-001"
