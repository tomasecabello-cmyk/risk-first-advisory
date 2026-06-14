"""
Integration tests for Phase 2 case-scoped reports (markdown).

Cubre:
    POST /cases/{case_id}/reports                  — genera nuevo reporte.
    GET  /cases/{case_id}/reports                  — lista por case.
    GET  /cases/{case_id}/reports/{report_id}      — detalle.

Persistencia:
    - Migrations 0001..0009 corridas en DB temporal.
    - report vinculado a (case_id, portfolio_selection_id, portfolio_proposal_id).
    - version monotónica por case_id.
    - AuditEvent report_generated.
    - is_current management.
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


_TOKENS_YAML = """\
tokens:
  test-admin-token:
    advisor_id: ADM-RPT-001
    display_name: Test Admin
    firm_id: null
    roles: [admin]
  test-advisor-token:
    advisor_id: ADV-RPT-001
    display_name: Test Advisor
    firm_id: null
    roles: [advisor]
  test-compliance-token:
    advisor_id: CMP-RPT-001
    display_name: Test Compliance
    firm_id: null
    roles: [compliance]
  test-viewer-token:
    advisor_id: VWR-RPT-001
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
    tokens_yaml = tmp_path / "rpt_tokens.yaml"
    tokens_yaml.write_text(_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def rpt_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "rpt_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI (moderado profile)
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
    return {"display_name": "RPT Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "display_name": "RPT Advisor",
            "email": "a@rpt.com", "roles": ["advisor"], **kw}


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "primary_advisor_id": advisor_id,
            "display_name": "RPT Client", **kw}


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {"firm_id": firm_id, "client_id": client_id,
            "lead_advisor_id": advisor_id, "title": "RPT Case", **kw}


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


def _setup_case_with_selection(
    c: TestClient, patch_ai_client
) -> dict[str, Any]:
    """Pipeline completo hasta tener una portfolio selection vigente."""
    patch_ai_client()
    firm = _post(c, "/firms", _firm_body(), _ADMIN).json()
    adv = _post(c, "/advisors", _advisor_body(firm["firm_id"], advisor_id="ADV-RPT-001"), _ADMIN).json()
    cli = _post(c, "/clients", _client_body(firm["firm_id"], adv["advisor_id"]), _ADMIN).json()
    case = _post(c, "/cases", _case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"])).json()
    _post(c, f"/cases/{case['case_id']}/kyc", _kyc_body())
    _post(c, f"/cases/{case['case_id']}/ai/profile-analysis", {})
    _post(c, f"/cases/{case['case_id']}/profile-approval",
          {"decision": "approve", "rationale": "ok"})
    _post(c, f"/cases/{case['case_id']}/investment-preferences",
          {"structured_preferences": _BROAD_PREFS})
    _post(c, f"/cases/{case['case_id']}/universe-filter", {})
    proposal = _post(c, f"/cases/{case['case_id']}/portfolio-proposal", {}).json()
    # Encontrar variante sin override
    non_override = None
    for cand in proposal["candidates"]:
        meta = cand.get("metadata") or {}
        if meta.get("requires_advisor_override") is False:
            non_override = cand["variant"]
            break
    assert non_override is not None
    selection = _post(c, f"/cases/{case['case_id']}/portfolio-selection",
                      {"selected_variant": non_override, "rationale": "ok"}).json()
    return {"case": case, "proposal": proposal, "selection": selection}


def _post_report(c: TestClient, case_id: str, **body) -> Any:
    return c.post(f"/cases/{case_id}/reports", json=body,
                  headers={"Authorization": _ADVISOR})


# ═════════════════════════════════════════════════════════════════════════════
# Create
# ═════════════════════════════════════════════════════════════════════════════


class TestCreate:
    def test_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.status_code == 201, r.text

    def test_report_id_prefix(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["report_id"].startswith("case_report_")

    def test_version_1(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["version"] == 1

    def test_case_id_correct(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["case_id"] == ctx["case"]["case_id"]

    def test_portfolio_selection_id_correct(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["portfolio_selection_id"] == ctx["selection"]["selection_id"]

    def test_portfolio_proposal_id_correct(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["portfolio_proposal_id"] == ctx["proposal"]["proposal_id"]

    def test_report_type_default(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["report_type"] == "portfolio_recommendation"

    def test_status_default_draft(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["status"] == "draft"

    def test_status_final_supported(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"], status="final")
        assert r.status_code == 201
        assert r.json()["status"] == "final"

    def test_markdown_not_empty(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        md = r.json()["markdown"]
        assert isinstance(md, str) and len(md) > 100

    def test_markdown_contains_case_id(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert ctx["case"]["case_id"] in r.json()["markdown"]

    def test_markdown_contains_selected_variant(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert ctx["selection"]["selected_variant"] in r.json()["markdown"]

    def test_markdown_contains_ai_disclaimer(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        md = r.json()["markdown"]
        # El generator incluye un disclaimer explícito sobre la IA y
        # la responsabilidad del asesor.
        assert "IA" in md or "asesor" in md.lower()

    def test_markdown_contains_composicion_section(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """Phase 3.6: el reporte debe tener una sección titulada
        'Composición de la cartera seleccionada' con tabla legible."""
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        md = r.json()["markdown"]
        assert "## Composición de la cartera seleccionada" in md
        # tabla markdown: header "Instrumento | Tipo | Moneda | Peso | Motivo"
        assert "| Instrumento |" in md
        assert "| Tipo |" in md
        assert "| Moneda |" in md
        assert "| Peso |" in md

    def test_markdown_contains_holdings_with_ticker_and_weight(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """Phase 3.6: la tabla de composición debe listar instrumentos reales
        del portfolio (tickers del snapshot del filter run, con peso %)."""
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        md = r.json()["markdown"]
        # Trazamos la sección de holdings y verificamos que al menos un
        # ticker del proposal aparezca en el markdown.
        cand = ctx["selection"]["selected_candidate"]
        holdings = cand.get("holdings") or []
        assert holdings, "Selected candidate should have holdings to test against"
        ticker_zero = holdings[0]["ticker"]
        assert f"`{ticker_zero}`" in md
        # algún porcentaje (formato del helper _pct: "12.34%")
        import re
        assert re.search(r"\d+\.\d+%", md)

    def test_markdown_contains_variantes_comparison_when_proposal_present(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """Phase 3.6: si el proposal tiene candidates, el reporte debe incluir
        la tabla 'Comparación de variantes generadas' con al menos 2 de las
        variantes estándar (DEFENSIVE / BALANCED / GROWTH — la disponibilidad
        depende de la feasibility del universo)."""
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        md = r.json()["markdown"]
        assert "## Comparación de variantes generadas" in md
        # Cabecera de la tabla
        assert "| Variante |" in md
        assert "Top holdings" in md
        # Al menos 2 variantes (cuáles exactamente depende del universo)
        variants_present = sum(v in md for v in ("DEFENSIVE", "BALANCED", "GROWTH"))
        assert variants_present >= 2, (
            f"expected at least 2 standard variants in comparison table, "
            f"found {variants_present}"
        )

    def test_metadata_holdings_summary(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """Phase 3.6: la metadata persistida incluye un holdings_summary
        compacto (ticker + weight) además del asset_count."""
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        meta = r.json()["metadata"]
        assert isinstance(meta.get("holdings_summary"), list)
        assert len(meta["holdings_summary"]) == meta["asset_count"]
        for h in meta["holdings_summary"]:
            assert "ticker" in h
            assert "weight" in h

    def test_metadata_dict_not_empty(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        meta = r.json()["metadata"]
        assert isinstance(meta, dict) and len(meta) > 0
        assert meta["case_id"] == ctx["case"]["case_id"]
        assert meta["selection_id"] == ctx["selection"]["selection_id"]

    def test_is_current_true(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.json()["is_current"] is True

    def test_get_list_count_1(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        _post_report(client, ctx["case"]["case_id"])
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_get_single_returns_report(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        post_r = _post_report(client, ctx["case"]["case_id"])
        report_id = post_r.json()["report_id"]
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports/{report_id}",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["report_id"] == report_id

    def test_second_post_creates_version_2_and_marks_first_not_current(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        first = _post_report(client, ctx["case"]["case_id"]).json()
        second = _post_report(client, ctx["case"]["case_id"]).json()
        assert second["version"] == 2
        # Listar para confirmar flags.
        body = client.get(
            f"/cases/{ctx['case']['case_id']}/reports",
            headers={"Authorization": _ADVISOR},
        ).json()
        flags = {r["report_id"]: r["is_current"] for r in body["reports"]}
        assert flags[first["report_id"]] is False
        assert flags[second["report_id"]] is True


# ═════════════════════════════════════════════════════════════════════════════
# Validation
# ═════════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_missing_case_post_404(self, client: TestClient) -> None:
        r = _post_report(client, "case_nope")
        assert r.status_code == 404

    def test_missing_case_get_list_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/reports", headers={"Authorization": _COMPLIANCE}
        )
        assert r.status_code == 404

    def test_missing_case_get_single_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/reports/case_report_X",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404

    def test_no_selection_409(self, client: TestClient) -> None:
        # case sin selection
        firm = _post(client, "/firms", _firm_body(), _ADMIN).json()
        adv = _post(client, "/advisors", _advisor_body(firm["firm_id"], advisor_id="ADV-RPT-001"), _ADMIN).json()
        cli = _post(client, "/clients", _client_body(firm["firm_id"], adv["advisor_id"]), _ADMIN).json()
        case = _post(client, "/cases", _case_body(firm["firm_id"], cli["client_id"], adv["advisor_id"])).json()
        r = _post_report(client, case["case_id"])
        assert r.status_code == 409
        assert "no current portfolio selection" in r.json()["detail"].lower()

    def test_selection_from_other_case_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx_a = _setup_case_with_selection(client, patch_ai_client)
        firm = ctx_a["case"]["firm_id"]
        adv_id = ctx_a["case"]["lead_advisor_id"]
        cli_id = ctx_a["case"]["client_id"]
        case_b = _post(client, "/cases",
                       _case_body(firm, cli_id, adv_id, title="Case B")).json()
        r = _post_report(
            client, case_b["case_id"],
            portfolio_selection_id=ctx_a["selection"]["selection_id"],
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_selection_unknown_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(
            client, ctx["case"]["case_id"],
            portfolio_selection_id="case_portfolio_selection_NOPE",
        )
        assert r.status_code == 422
        assert "not found" in r.json()["detail"].lower()

    def test_report_type_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"], report_type="bogus")
        assert r.status_code == 422

    def test_status_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"], status="bogus")
        assert r.status_code == 422

    def test_closed_case_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        case_id = ctx["case"]["case_id"]
        # case ya está en PORTFOLIO_SELECTED por la selection; mover a CLOSED.
        client.patch(
            f"/cases/{case_id}/status", json={"status": "CLOSED"},
            headers={"Authorization": _ADVISOR},
        )
        r = _post_report(client, case_id)
        assert r.status_code == 409

    def test_report_missing_404(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports/case_report_NOPE",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_report_from_other_case_404(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx_a = _setup_case_with_selection(client, patch_ai_client)
        report_a = _post_report(client, ctx_a["case"]["case_id"]).json()
        # Crear case B separado
        firm = ctx_a["case"]["firm_id"]
        adv_id = ctx_a["case"]["lead_advisor_id"]
        cli_id = ctx_a["case"]["client_id"]
        case_b = _post(client, "/cases",
                       _case_body(firm, cli_id, adv_id, title="Case B")).json()
        r = client.get(
            f"/cases/{case_b['case_id']}/reports/{report_a['report_id']}",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════════════════


class TestRBACPost:
    def test_no_token_401(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = client.post(f"/cases/{ctx['case']['case_id']}/reports", json={})
        assert r.status_code == 401

    def test_compliance_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/reports", json={},
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403

    def test_viewer_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/reports", json={},
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = _post_report(client, ctx["case"]["case_id"])
        assert r.status_code == 201

    def test_admin_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/reports", json={},
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACGet:
    def test_no_token_list_401(self, client: TestClient) -> None:
        r = client.get("/cases/case_x/reports")
        assert r.status_code == 401

    def test_no_token_single_401(self, client: TestClient) -> None:
        r = client.get("/cases/case_x/reports/case_report_y")
        assert r.status_code == 401

    def test_compliance_list_200(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_viewer_list_200(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200

    def test_compliance_single_200(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        rep = _post_report(client, ctx["case"]["case_id"]).json()
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports/{rep['report_id']}",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_viewer_single_200(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        rep = _post_report(client, ctx["case"]["case_id"]).json()
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/reports/{rep['report_id']}",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Audit
# ═════════════════════════════════════════════════════════════════════════════


class TestAudit:
    def test_event_report_generated(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        rep = _post_report(client, ctx["case"]["case_id"]).json()
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "report_generated" in types
        evt = next(e for e in events if e["event_type"] == "report_generated")
        assert evt["payload"]["report_id"] == rep["report_id"]
        assert evt["payload"]["version"] == 1

    def test_audit_chain_intact(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _setup_case_with_selection(client, patch_ai_client)
        _post_report(client, ctx["case"]["case_id"])
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
        assert r.json()["advisor_id"] == "ADV-RPT-001"
