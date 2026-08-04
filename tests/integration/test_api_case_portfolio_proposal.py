"""
Integration tests for Phase 2 case-scoped PortfolioProposal.

Cubre:
    POST /cases/{case_id}/portfolio-proposal  — usa current approved profile +
                                                 current filter run; corre
                                                 PortfolioGenerationCoordinator
                                                 contra el snapshot del filter
                                                 run; persiste proposal +
                                                 AuditEvent.
    GET  /cases/{case_id}/portfolio-proposal  — listado por case.

Persistencia:
    - Migrations 0001..0006 corridas en DB temporal.
    - Proposal snapshot completo: risk_budget, snapshots, candidates, warnings.
    - is_current management.
    - AuditEvent portfolio_proposal_generated.

OpenAI se monkeypatchea para el AI profile analysis (necesario para construir
el approved profile vía el flow case-scoped).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
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
    advisor_id: ADM-CPP-001
    display_name: Test Admin
    firm_id: null
    roles:
      - admin
  test-advisor-token:
    advisor_id: ADV-CPP-001
    display_name: Test Advisor
    firm_id: null
    roles:
      - advisor
  test-compliance-token:
    advisor_id: CMP-CPP-001
    display_name: Test Compliance
    firm_id: null
    roles:
      - compliance
  test-viewer-token:
    advisor_id: VWR-CPP-001
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
    tokens_yaml = tmp_path / "cpp_tokens.yaml"
    tokens_yaml.write_text(_TOKENS_YAML, encoding="utf-8")
    monkeypatch.setenv(_tokens_module.ADVISOR_TOKENS_ENV_VAR, str(tokens_yaml))


@pytest.fixture(autouse=True)
def cpp_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "cpp_test.db"
    migrate.run(db_path, _MIGRATIONS_DIR, verbose=False)
    monkeypatch.setattr(_main_module, "DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fake OpenAI for AI profile analysis (necesario porque el flow case usa este
# análisis para construir el approved profile)
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
        cli = OpenAIProfileClient(_client=fake)
        monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: cli)

    return _install


# ─────────────────────────────────────────────────────────────────────────────
# Entity helpers
# ─────────────────────────────────────────────────────────────────────────────


def _firm_body(**kw: Any) -> dict:
    return {"display_name": "CPP Firm", "country": "AR", **kw}


def _advisor_body(firm_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "display_name": "CPP Advisor",
        "email": "a@cpp.com",
        "roles": ["advisor"],
        **kw,
    }


def _client_body(firm_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "primary_advisor_id": advisor_id,
        "display_name": "CPP Client",
        **kw,
    }


def _case_body(firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    return {
        "firm_id": firm_id,
        "client_id": client_id,
        "lead_advisor_id": advisor_id,
        "title": "CPP Case",
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


# Preferencias amplias para que pasen muchos instruments en el filter:
# sin restricciones duras → universo casi completo del fixture.
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
    r = c.post(
        "/advisors", json=_advisor_body(firm_id, **kw),
        headers={"Authorization": _ADMIN},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_client(c: TestClient, firm_id: str, advisor_id: str, **kw: Any) -> dict:
    r = c.post(
        "/clients", json=_client_body(firm_id, advisor_id, **kw),
        headers={"Authorization": _ADMIN},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_case(c: TestClient, firm_id: str, client_id: str, advisor_id: str, **kw: Any) -> dict:
    r = c.post(
        "/cases", json=_case_body(firm_id, client_id, advisor_id, **kw),
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


def _post_approval(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(
        f"/cases/{case_id}/profile-approval",
        json=body,
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _post_pref(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(
        f"/cases/{case_id}/investment-preferences",
        json=body,
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _post_filter(c: TestClient, case_id: str, **body) -> dict:
    r = c.post(
        f"/cases/{case_id}/universe-filter",
        json=body,
        headers={"Authorization": _ADVISOR},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _post_proposal(c: TestClient, case_id: str, **body) -> Any:
    return c.post(
        f"/cases/{case_id}/portfolio-proposal",
        json=body,
        headers={"Authorization": _ADVISOR},
    )


def _full_setup(c: TestClient, patch_ai_client, **kyc_overrides: Any) -> dict:
    """
    Pipeline completo hasta tener universe filter + approved profile listos
    para el portfolio proposal.
    """
    patch_ai_client()
    firm = _create_firm(c)
    adv = _create_advisor(c, firm["firm_id"], advisor_id="ADV-CPP-001")
    cli = _create_client(c, firm["firm_id"], adv["advisor_id"])
    case = _create_case(c, firm["firm_id"], cli["client_id"], adv["advisor_id"])
    kyc = _post_kyc(c, case["case_id"], **kyc_overrides)
    # AI profile analysis (genera preliminary_profile=moderado).
    r_analysis = c.post(
        f"/cases/{case['case_id']}/ai/profile-analysis",
        json={},
        headers={"Authorization": _ADVISOR},
    )
    assert r_analysis.status_code == 201
    approval = _post_approval(
        c, case["case_id"], decision="approve", rationale="ok"
    )
    pref = _post_pref(
        c, case["case_id"], structured_preferences=_BROAD_PREFS
    )
    filter_run = _post_filter(c, case["case_id"])
    return {
        "case": case, "kyc": kyc, "analysis": r_analysis.json(),
        "approval": approval, "preference": pref, "filter_run": filter_run,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Create
# ═════════════════════════════════════════════════════════════════════════════


class TestCreate:
    def test_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201, r.text

    def test_proposal_id_prefix(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.json()["proposal_id"].startswith("case_portfolio_proposal_")

    def test_case_id_in_response(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.json()["case_id"] == ctx["case"]["case_id"]

    def test_filter_run_id_from_current(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.json()["filter_run_id"] == ctx["filter_run"]["filter_run_id"]

    def test_approved_profile_id_from_current(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.json()["approved_profile_id"] == ctx["approval"]["approval_id"]

    def test_profile_name_moderado(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.json()["profile_name"] == "moderado"

    def test_risk_budget_not_empty(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        rb = r.json()["risk_budget"]
        assert rb["profile_name"] == "moderado"
        assert rb["max_single_asset"] > 0

    def test_snapshots_non_empty(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        snaps = r.json()["snapshots"]
        assert len(snaps) > 0
        # cada snapshot debe tener los campos básicos
        assert all("ticker" in s for s in snaps)

    def test_candidates_non_empty_when_completed(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        body = r.json()
        if body["status"] == "completed":
            assert len(body["candidates"]) > 0

    def test_status_value(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.json()["status"] in {
            "completed",
            "blocked_insufficient_universe",
            "blocked_insufficient_diversification_capacity",
            "infeasible",
        }

    def test_is_current_true(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.json()["is_current"] is True

    def test_get_lists_one(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        _post_proposal(client, ctx["case"]["case_id"])
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal",
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_second_marks_first_not_current(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        first = _post_proposal(client, ctx["case"]["case_id"]).json()
        second = _post_proposal(client, ctx["case"]["case_id"]).json()
        body = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal",
            headers={"Authorization": _ADVISOR},
        ).json()
        flags = {p["proposal_id"]: p["is_current"] for p in body["proposals"]}
        assert flags[first["proposal_id"]] is False
        assert flags[second["proposal_id"]] is True


# ═════════════════════════════════════════════════════════════════════════════
# Holdings visibility (Phase 3.6 — composición visible)
# ═════════════════════════════════════════════════════════════════════════════


def _completed_candidates(client: TestClient, patch_ai_client) -> tuple[dict, list[dict]]:
    """Helper: corre el flujo, devuelve (body, candidates) si status=completed."""
    ctx = _full_setup(client, patch_ai_client)
    body = _post_proposal(client, ctx["case"]["case_id"]).json()
    if body["status"] != "completed":
        pytest.skip(
            f"Proposal status is {body['status']!r}; need 'completed' to test "
            f"holdings. Universe fixture may be too narrow."
        )
    return body, body["candidates"]


class TestCandidateHoldings:
    """
    Verifica que cada candidate completed exponga su composición real
    (instrument_id, ticker, name, instrument_type, currency, weight, etc.)
    de forma estructurada — no solo `weights` por ticker.
    """

    def test_every_completed_candidate_has_holdings(
        self, client: TestClient, patch_ai_client
    ) -> None:
        _, cands = _completed_candidates(client, patch_ai_client)
        assert len(cands) > 0
        for c in cands:
            assert isinstance(c.get("holdings"), list), (
                f"candidate {c.get('variant')!r} missing 'holdings' list"
            )
            assert len(c["holdings"]) > 0, (
                f"candidate {c.get('variant')!r} has empty holdings"
            )

    def test_holding_shape(
        self, client: TestClient, patch_ai_client
    ) -> None:
        _, cands = _completed_candidates(client, patch_ai_client)
        for c in cands:
            for h in c["holdings"]:
                # Identificación: instrument_id + ticker presentes y no vacíos
                assert h.get("instrument_id"), f"holding missing instrument_id: {h!r}"
                assert h.get("ticker") == h.get("instrument_id"), (
                    "ticker should mirror instrument_id"
                )
                # Peso numérico y > 0
                assert isinstance(h.get("weight"), (int, float))
                assert h["weight"] > 0
                # weight_percent = weight*100 (con tolerancia)
                assert abs(h["weight_percent"] - h["weight"] * 100.0) < 1e-3
                # Reason codes & risk flags son listas (pueden estar vacías)
                assert isinstance(h.get("inclusion_reason_codes"), list)
                assert isinstance(h.get("risk_flags"), list)

    def test_holding_metadata_from_universe(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """
        Las holdings deben traer la metadata del instrumento (name, type, currency)
        cuando el ticker matchea con el snapshot del filter run.
        """
        _, cands = _completed_candidates(client, patch_ai_client)
        # Al menos UNA holding (cualquier candidate) debe tener name + type + currency
        # poblados — si todas vienen vacías es señal de que el lookup no enganchó.
        enriched = 0
        for c in cands:
            for h in c["holdings"]:
                if h.get("name") and h.get("instrument_type") and h.get("currency"):
                    enriched += 1
        assert enriched > 0, (
            "No holdings have name+instrument_type+currency — universe lookup is broken."
        )

    def test_holdings_count_matches(
        self, client: TestClient, patch_ai_client
    ) -> None:
        _, cands = _completed_candidates(client, patch_ai_client)
        for c in cands:
            assert c.get("holdings_count") == len(c["holdings"])

    def test_total_weight_close_to_one(
        self, client: TestClient, patch_ai_client
    ) -> None:
        _, cands = _completed_candidates(client, patch_ai_client)
        for c in cands:
            tw = c.get("total_weight")
            assert isinstance(tw, (int, float))
            # Tolerancia para floating point + el filtro w > 1e-6 del serializer.
            assert 0.99 <= tw <= 1.01, (
                f"candidate {c.get('variant')!r} total_weight={tw} not ≈ 1.0"
            )

    def test_holdings_sorted_by_weight_desc(
        self, client: TestClient, patch_ai_client
    ) -> None:
        _, cands = _completed_candidates(client, patch_ai_client)
        for c in cands:
            weights = [h["weight"] for h in c["holdings"]]
            assert weights == sorted(weights, reverse=True), (
                f"candidate {c.get('variant')!r} holdings not sorted by weight desc"
            )

    def test_weights_legacy_field_preserved(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """Backward compatibility: el campo `weights` (legacy) sigue presente."""
        _, cands = _completed_candidates(client, patch_ai_client)
        for c in cands:
            assert isinstance(c.get("weights"), list)
            assert len(c["weights"]) == len(c["holdings"])

    def test_blocked_proposal_has_empty_holdings(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """
        Si el proposal queda blocked/infeasible, los candidates están vacíos
        (no se simulan holdings). Lo verificamos vía el caso de "sin filter run":
        no es trivial forzar 'blocked' desde el flujo full, así que solo
        afirmamos que cuando status != completed, candidates es lista vacía.
        """
        ctx = _full_setup(client, patch_ai_client)
        body = _post_proposal(client, ctx["case"]["case_id"]).json()
        if body["status"] == "completed":
            return  # path feliz, no aplica
        assert body["candidates"] == [], (
            f"non-completed proposal ({body['status']!r}) leaked candidates"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Risk Number (Slice 3 — docs/RISK_NUMBER_DESIGN.md)
# ═════════════════════════════════════════════════════════════════════════════


class TestCandidateRiskNumber:
    """
    Cada candidate completed expone `risk_number` (0-100 de ESA cartera,
    derivado de sus pesos reales + los retornos/covarianza ya estimados para
    la propuesta — no vuelve a llamar al optimizer) y `risk_alignment`
    (comparación con el número del cliente, derivado del KYC del case).
    """

    def test_every_completed_candidate_has_risk_number(
        self, client: TestClient, patch_ai_client
    ) -> None:
        _, cands = _completed_candidates(client, patch_ai_client)
        for c in cands:
            rn = c.get("risk_number")
            assert rn is not None, (
                f"candidate {c.get('variant')!r} missing risk_number "
                "(usable_snapshots feed both the optimizer and the risk "
                "number, so a completed proposal should always have it)"
            )
            assert 0.0 <= rn["number"] <= 100.0
            assert rn["band"] in {
                "conservador", "moderado-defensivo", "moderado",
                "moderado-agresivo", "agresivo",
            }
            assert rn["missing_tickers"] == []

    def test_every_completed_candidate_has_risk_alignment(
        self, client: TestClient, patch_ai_client
    ) -> None:
        # _full_setup ya postea KYC, así que el case tiene current_kyc_submission_id.
        ctx_body, cands = _completed_candidates(client, patch_ai_client)
        for c in cands:
            al = c.get("risk_alignment")
            assert al is not None, (
                f"candidate {c.get('variant')!r} missing risk_alignment "
                "despite the case having a KYC submission"
            )
            assert al["status"] in {
                "aligned", "over_tolerance", "under_tolerance", "over_capacity",
            }
            assert isinstance(al["gap_points"], (int, float))
            assert isinstance(al["capacity_gap_points"], (int, float))
            # Señal INFORMATIVA: el flag de override lo gobierna únicamente
            # metadata.requires_advisor_override (I-018) — acá no debe existir.
            assert "override_required" not in al
            # Trazabilidad: qué KYC produjo el número del cliente.
            assert str(al["client_kyc_submission_id"]).startswith("kyc_submission_")

    def test_growth_variant_is_riskiest_or_tied(
        self, client: TestClient, patch_ai_client
    ) -> None:
        # No es un invariante estricto del optimizer, pero con el universo
        # fixture GROWTH (MAX_RETURN, budget relajado) no debería quedar por
        # debajo del número de DEFENSIVE (MIN_VARIANCE).
        _, cands = _completed_candidates(client, patch_ai_client)
        by_variant = {c["variant"]: c for c in cands}
        if "DEFENSIVE" in by_variant and "GROWTH" in by_variant:
            defensive_rn = by_variant["DEFENSIVE"]["risk_number"]
            growth_rn = by_variant["GROWTH"]["risk_number"]
            if defensive_rn and growth_rn:
                assert growth_rn["number"] >= defensive_rn["number"]

    def test_risk_alignment_present_with_valid_tradeoff_kyc(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """El KYC con la pregunta de trade-off respondida (Slice 4b) sigue
        produciendo risk_alignment por candidato — el cross-check declarado
        vs. trade-off es interno a client_risk_number, invisible aquí salvo
        por su efecto en el número/alineación."""
        ctx = _full_setup(
            client, patch_ai_client,
            tradeoff_gain_usd=15000.0, tradeoff_loss_usd=7500.0,
            tradeoff_certain_amount_usd=3000.0,
        )
        r = _post_proposal(client, ctx["case"]["case_id"])
        body = r.json()
        if body["status"] != "completed":
            pytest.skip("proposal not completed in this fixture universe run")
        for c in body["candidates"]:
            assert c.get("risk_alignment") is not None

    def test_risk_alignment_tolerant_to_invalid_tradeoff_kyc(
        self, client: TestClient, patch_ai_client
    ) -> None:
        """certain_amount fuera de rango (-loss, gain): el motor rechaza el
        trade-off (ValueError) pero la propuesta NUNCA responde 500 — cae a
        willingness-only, igual que si la pregunta no se hubiera respondido."""
        ctx = _full_setup(
            client, patch_ai_client,
            tradeoff_gain_usd=15000.0, tradeoff_loss_usd=7500.0,
            tradeoff_certain_amount_usd=99999.0,
        )
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201, r.text
        body = r.json()
        if body["status"] != "completed":
            pytest.skip("proposal not completed in this fixture universe run")
        for c in body["candidates"]:
            assert c.get("risk_alignment") is not None


# ═════════════════════════════════════════════════════════════════════════════
# Validation
# ═════════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_missing_case_post_404(self, client: TestClient) -> None:
        r = client.post(
            "/cases/case_nope/portfolio-proposal",
            json={},
            headers={"Authorization": _ADVISOR},
        )
        assert r.status_code == 404

    def test_missing_case_get_404(self, client: TestClient) -> None:
        r = client.get(
            "/cases/case_nope/portfolio-proposal",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 404

    def test_closed_case_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        case_id = ctx["case"]["case_id"]
        # case ya está IN_PROGRESS por POST KYC. PORTFOLIO_SELECTED → CLOSED.
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
        r = _post_proposal(client, case_id)
        assert r.status_code == 409

    def test_no_approved_profile_409(self, client: TestClient) -> None:
        # case con KYC + filter pero sin profile approval
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"], advisor_id="ADV-CPP-001")
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        _post_kyc(client, case["case_id"])
        _post_pref(client, case["case_id"], structured_preferences=_BROAD_PREFS)
        _post_filter(client, case["case_id"])
        r = _post_proposal(client, case["case_id"])
        assert r.status_code == 409
        assert "approved profile" in r.json()["detail"].lower()

    def test_no_universe_filter_409(
        self, client: TestClient, patch_ai_client
    ) -> None:
        patch_ai_client()
        firm = _create_firm(client)
        adv = _create_advisor(client, firm["firm_id"], advisor_id="ADV-CPP-001")
        cli = _create_client(client, firm["firm_id"], adv["advisor_id"])
        case = _create_case(client, firm["firm_id"], cli["client_id"], adv["advisor_id"])
        _post_kyc(client, case["case_id"])
        client.post(
            f"/cases/{case['case_id']}/ai/profile-analysis", json={},
            headers={"Authorization": _ADVISOR},
        )
        _post_approval(client, case["case_id"], decision="approve", rationale="ok")
        r = _post_proposal(client, case["case_id"])
        assert r.status_code == 409
        assert "universe filter" in r.json()["detail"].lower()

    def test_filter_run_id_from_other_case_422(
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
        client.post(
            f"/cases/{case_b['case_id']}/ai/profile-analysis", json={},
            headers={"Authorization": _ADVISOR},
        )
        _post_approval(client, case_b["case_id"], decision="approve", rationale="ok")
        _post_pref(client, case_b["case_id"], structured_preferences=_BROAD_PREFS)
        _post_filter(client, case_b["case_id"])
        # Usar filter_run del case A en case B
        r = _post_proposal(
            client, case_b["case_id"],
            filter_run_id=ctx_a["filter_run"]["filter_run_id"],
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_approved_profile_id_from_other_case_422(
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
        client.post(
            f"/cases/{case_b['case_id']}/ai/profile-analysis", json={},
            headers={"Authorization": _ADVISOR},
        )
        _post_approval(client, case_b["case_id"], decision="approve", rationale="ok")
        _post_pref(client, case_b["case_id"], structured_preferences=_BROAD_PREFS)
        _post_filter(client, case_b["case_id"])
        # Usar approval del case A en case B
        r = _post_proposal(
            client, case_b["case_id"],
            approved_profile_id=ctx_a["approval"]["approval_id"],
        )
        assert r.status_code == 422
        assert "belongs to case" in r.json()["detail"]

    def test_variant_policy_invalid_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"], variant_policy="bogus")
        assert r.status_code == 422

    def test_filter_run_unknown_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(
            client, ctx["case"]["case_id"],
            filter_run_id="case_universe_filter_run_NOPE",
        )
        assert r.status_code == 422

    def test_approval_unknown_422(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(
            client, ctx["case"]["case_id"],
            approved_profile_id="advisor_profile_approval_NOPE",
        )
        assert r.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# RBAC
# ═════════════════════════════════════════════════════════════════════════════


class TestRBACPost:
    def test_no_token_401(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal", json={}
        )
        assert r.status_code == 401

    def test_compliance_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal", json={},
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 403

    def test_viewer_403(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal", json={},
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 403

    def test_advisor_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201

    def test_admin_201(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.post(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal", json={},
            headers={"Authorization": _ADMIN},
        )
        assert r.status_code == 201


class TestRBACGet:
    def test_no_token_401(self, client: TestClient) -> None:
        r = client.get("/cases/case_x/portfolio-proposal")
        assert r.status_code == 401

    def test_compliance_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal",
            headers={"Authorization": _COMPLIANCE},
        )
        assert r.status_code == 200

    def test_viewer_200(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = client.get(
            f"/cases/{ctx['case']['case_id']}/portfolio-proposal",
            headers={"Authorization": _VIEWER},
        )
        assert r.status_code == 200


# ═════════════════════════════════════════════════════════════════════════════
# Audit
# ═════════════════════════════════════════════════════════════════════════════


class TestAudit:
    def test_event_portfolio_proposal_generated(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        proposal = _post_proposal(client, ctx["case"]["case_id"]).json()
        events = client.get(
            f"/cases/{ctx['case']['case_id']}/audit",
            headers={"Authorization": _ADVISOR},
        ).json()["events"]
        types = [e["event_type"] for e in events]
        assert "portfolio_proposal_generated" in types
        evt = next(e for e in events if e["event_type"] == "portfolio_proposal_generated")
        assert evt["payload"]["proposal_id"] == proposal["proposal_id"]
        assert evt["payload"]["candidate_count"] == len(proposal["candidates"])
        assert evt["payload"]["status"] == proposal["status"]

    def test_audit_chain_intact(
        self, client: TestClient, patch_ai_client
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        _post_proposal(client, ctx["case"]["case_id"])
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
                "client_id": "C-X",
                "profile": "moderado",
                "natural_language_preferences": "x",
            },
        )
        assert r.status_code != 401

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
        assert r.json()["advisor_id"] == "ADV-CPP-001"


# ═════════════════════════════════════════════════════════════════════════════
# KYC_STALE (KYC_012) — vigencia del KYC que respalda el proposal
# (auditoría compliance 2026-07-17; TTL via RFA_KYC_MAX_AGE_DAYS, default 365)
# ═════════════════════════════════════════════════════════════════════════════


def _backdate_kyc(db_path: Path, kyc_submission_id: str, created_at_utc: str) -> None:
    """Envejece la submission directamente en la DB (el API es append-only;
    esto es setup de test, no un path de producto)."""
    conn = sqlite3.connect(str(db_path))
    try:
        with conn:
            conn.execute(
                "UPDATE kyc_submissions SET created_at_utc = ? "
                "WHERE kyc_submission_id = ?",
                (created_at_utc, kyc_submission_id),
            )
    finally:
        conn.close()


class TestKYCStaleWarning:
    def test_fresh_kyc_no_warning(self, client: TestClient, patch_ai_client) -> None:
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201, r.text
        assert not any("KYC_012" in w for w in r.json()["warnings"])

    def test_stale_kyc_warns(
        self, client: TestClient, patch_ai_client, cpp_db: Path
    ) -> None:
        ctx = _full_setup(client, patch_ai_client)
        kyc_id = ctx["kyc"]["kyc_submission_id"]
        _backdate_kyc(cpp_db, kyc_id, "2020-01-01T00:00:00Z")
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201, r.text
        stale = [w for w in r.json()["warnings"] if "KYC_012" in w]
        assert stale, r.json()["warnings"]
        # El warning identifica QUÉ KYC está vencido (trazabilidad).
        assert kyc_id in stale[0]

    def test_stale_warning_is_nonblocking(
        self, client: TestClient, patch_ai_client, cpp_db: Path
    ) -> None:
        """KYC_012 es warning: el proposal se genera igual (completed)."""
        ctx = _full_setup(client, patch_ai_client)
        _backdate_kyc(
            cpp_db, ctx["kyc"]["kyc_submission_id"], "2020-01-01T00:00:00Z"
        )
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201
        assert r.json()["status"] == "completed"
        assert len(r.json()["candidates"]) > 0

    def test_ttl_zero_disables_check(
        self,
        client: TestClient,
        patch_ai_client,
        cpp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RFA_KYC_MAX_AGE_DAYS", "0")
        ctx = _full_setup(client, patch_ai_client)
        _backdate_kyc(
            cpp_db, ctx["kyc"]["kyc_submission_id"], "2020-01-01T00:00:00Z"
        )
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201
        assert not any("KYC_012" in w for w in r.json()["warnings"])

    def test_custom_ttl_from_env(
        self,
        client: TestClient,
        patch_ai_client,
        cpp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Con TTL de 5 días, un KYC de ~10 días dispara el warning."""
        monkeypatch.setenv("RFA_KYC_MAX_AGE_DAYS", "5")
        ctx = _full_setup(client, patch_ai_client)
        ten_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        _backdate_kyc(cpp_db, ctx["kyc"]["kyc_submission_id"], ten_days_ago)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201
        warnings = r.json()["warnings"]
        assert any("KYC_012" in w for w in warnings)
        assert any("máximo configurado: 5" in w for w in warnings)

    def test_invalid_ttl_env_falls_back_to_default(
        self,
        client: TestClient,
        patch_ai_client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env var no numérica → default 365; un KYC fresco no avisa."""
        monkeypatch.setenv("RFA_KYC_MAX_AGE_DAYS", "not-a-number")
        ctx = _full_setup(client, patch_ai_client)
        r = _post_proposal(client, ctx["case"]["case_id"])
        assert r.status_code == 201
        assert not any("KYC_012" in w for w in r.json()["warnings"])
