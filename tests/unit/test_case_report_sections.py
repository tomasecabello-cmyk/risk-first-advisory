"""
Tests de las secciones nuevas del reporte case-scoped: resumen ejecutivo,
capacidad vs. tolerancia, y diversificación en métricas.
"""

from __future__ import annotations

from risk_first_advisory.ai_layer.risk_number import client_risk_number
from risk_first_advisory.ai_layer.risk_scoring import (
    capacity_gap_from_kyc,
    deterministic_assessment,
)
from risk_first_advisory.portfolio_layer.diversification import assess_diversification
from risk_first_advisory.reporting_layer.case_markdown_report import (
    CaseMarkdownReportGenerator,
)


def _low_capacity_kyc():
    tol = {
        "q1": "a", "q2": "d", "q3": "d", "q4": "c", "q5": "c", "q6": "d",
        "q7": "d", "q8": "d", "q9": "b", "q10": "b", "q11": "d", "q12": "c", "q13": "d",
    }
    return dict(
        tolerance_from_questionnaire=True, tolerance_answers=tol,
        capacity_from_facts=True, annual_income_usd=80000, liquid_net_worth=5000,
        net_worth=10000, investment_horizon_years=1, liquidity_need_score=8,
        investment_experience="ninguna", income_stability="inestable",
        dependents_count=3, essential_expenses_covered=False,
        investment_objective="aggressive_growth",
    )


def _holdings():
    return [
        {"ticker": "SPY", "asset_class": "EQUITY", "sector": "Equity", "currency": "USD", "weight": 0.35},
        {"ticker": "TLT", "asset_class": "FIXED_INCOME", "sector": "Treasuries", "currency": "USD", "weight": 0.30},
        {"ticker": "GLD", "asset_class": "COMMODITY", "sector": "Commodities", "currency": "USD", "weight": 0.20},
        {"ticker": "AAPL", "asset_class": "EQUITY", "sector": "Technology", "currency": "ARS", "weight": 0.15},
    ]


def _candidate(**over):
    cand = dict(
        variant="GROWTH", objective="MAX_RETURN", expected_return_annual=0.14,
        volatility_annual=0.19, risk_score=0.6, constraints_satisfied=True,
        holdings=_holdings(), holdings_count=4,
        metadata={"requires_advisor_override": True, "exceeded_constraints": ["max_volatility"]},
        diversification=assess_diversification(_holdings()),
    )
    cand.update(over)
    return cand


def _gen(capacity=True, override=True, risk_number=False, candidate_risk_number=False):
    kyc = _low_capacity_kyc()
    cap = None
    if capacity:
        cap = {
            "deterministic": deterministic_assessment(kyc),
            "capacity_gap": capacity_gap_from_kyc(kyc),
        }
    rn_data = None
    if risk_number:
        rn_data = {"client": client_risk_number(kyc)}
    over = {}
    if candidate_risk_number:
        over["risk_number"] = {"number": 68.0, "band": "agresivo"}
        over["risk_alignment"] = {
            "status": "over_capacity",
            "explanation": "La cartera excede el techo de capacidad del cliente.",
            "client_kyc_submission_id": "kyc_submission_000007",
        }
    cand = _candidate(**over)
    md, _ = CaseMarkdownReportGenerator().generate(
        case_data={"case_id": "c1", "title": "Juan Pérez", "status": "PORTFOLIO_SELECTED"},
        selection_data={"selected_variant": "GROWTH", "selected_candidate": cand,
                        "selection_id": "s1", "proposal_id": "p1",
                        "override_approval_id": "o1" if override else None},
        approval_data={"approved_profile": "moderado-agresivo", "decision": "modify"},
        override_data={"override_approval_id": "o1"} if override else None,
        capacity_data=cap,
        risk_number_data=rn_data,
        generated_at_utc="2026-06-15T12:00:00Z",
    )
    return md


def test_executive_summary_present_and_leads():
    md = _gen()
    assert "## Resumen ejecutivo" in md
    # El resumen va ANTES de la metadata.
    assert md.index("## Resumen ejecutivo") < md.index("## Metadata")
    assert "Juan Pérez" in md
    assert "moderado-agresivo" in md


def test_capacity_section_shows_willingness_and_ability():
    md = _gen(capacity=True)
    assert "## Capacidad vs. tolerancia" in md
    assert "Tolerancia declarada (quiere)" in md
    assert "Capacidad financiera (puede)" in md
    assert "100/100" in md  # tolerancia máxima
    assert "11/100" in md   # capacidad pésima


def test_capacity_section_omitted_when_no_capacity_data():
    md = _gen(capacity=False)
    assert "## Capacidad vs. tolerancia" not in md
    # El resto del reporte sigue armándose.
    assert "## Resumen ejecutivo" in md


def test_diversification_in_metrics():
    md = _gen()
    assert "Diversificación" in md
    assert "Reparto por clase de activo" in md
    assert "EQUITY" in md


def test_override_mentioned_in_summary():
    md = _gen(override=True)
    assert "override" in md.lower()


def test_risk_number_section_with_client_and_portfolio():
    md = _gen(risk_number=True, candidate_risk_number=True)
    assert "## Risk Number" in md
    assert "Número del cliente (operativo)" in md
    assert "Número de la cartera seleccionada" in md
    assert "68/100" in md
    assert "over_capacity" in md
    assert "Alineación cliente" in md
    # Nota de trazabilidad: la alineación se computó contra el KYC de la
    # propuesta; si el número del cliente (KYC vigente) difiere, se avisa.
    assert "kyc_submission_000007" in md
    assert "al generar la propuesta" in md


def test_risk_number_section_omitted_when_no_data():
    md = _gen(risk_number=False, candidate_risk_number=False)
    assert "## Risk Number" not in md
    # El resto del reporte sigue armándose.
    assert "## Resumen ejecutivo" in md


def test_risk_number_section_client_only_no_legacy_break():
    """Proposal viejo sin risk_number persistido: la cartera se marca
    'no disponible' pero el reporte no rompe y sigue mostrando al cliente."""
    md = _gen(risk_number=True, candidate_risk_number=False)
    assert "## Risk Number" in md
    assert "Número del cliente (operativo)" in md
    assert "no disponible" in md


def test_risk_number_section_no_kyc_but_candidate_has_number():
    """Case sin KYC vigente (risk_number_data=None) pero el candidate SÍ trae
    risk_number persistido: la sección se muestra igual, cliente 'no disponible'."""
    md = _gen(risk_number=False, candidate_risk_number=True)
    assert "## Risk Number" in md
    assert "Número del cliente" in md
    assert "no disponible" in md
    assert "68/100" in md


# ─────────────────────────────────────────────────────────────────────────────
# Notas de producto complejo (DD-017 ext.)
# ─────────────────────────────────────────────────────────────────────────────


def _holdings_with_cedear():
    note = (
        "Producto complejo: certificado argentino sobre una acción extranjera."
    )
    return [
        {"ticker": "SPY", "asset_class": "EQUITY", "sector": "Equity",
         "currency": "USD", "weight": 0.50, "instrument_type": "ETF",
         "complex_product_note": None},
        {"ticker": "AAPL", "asset_class": "EQUITY", "sector": "Technology",
         "currency": "USD", "weight": 0.30, "instrument_type": "CEDEAR",
         "complex_product_note": note},
        {"ticker": "KO", "asset_class": "EQUITY", "sector": "Consumer",
         "currency": "USD", "weight": 0.20, "instrument_type": "CEDEAR",
         "complex_product_note": note},
    ]


def test_product_notes_section_lists_complex_holdings():
    """Los holdings con complex_product_note generan la sección 'Notas de
    producto', agrupando tickers por nota (el report solo formatea, I-013)."""
    cand = _candidate(
        holdings=_holdings_with_cedear(), holdings_count=3,
        diversification=assess_diversification(_holdings_with_cedear()),
    )
    md, _ = CaseMarkdownReportGenerator().generate(
        case_data={"case_id": "c1", "title": "Juan Pérez", "status": "PORTFOLIO_SELECTED"},
        selection_data={"selected_variant": "GROWTH", "selected_candidate": cand,
                        "selection_id": "s1", "proposal_id": "p1",
                        "override_approval_id": None},
        approval_data={"approved_profile": "agresivo", "decision": "approve"},
        override_data=None,
        generated_at_utc="2026-06-15T12:00:00Z",
    )
    assert "### Notas de producto" in md
    # Ambos CEDEARs agrupados en la misma nota.
    assert "`AAPL`" in md and "`KO`" in md
    assert "Producto complejo" in md


def test_product_notes_section_absent_without_complex_holdings():
    """Snapshots viejos (sin el campo) o carteras sin productos complejos:
    la sección no aparece y el reporte no rompe."""
    md = _gen()
    assert "### Notas de producto" not in md
