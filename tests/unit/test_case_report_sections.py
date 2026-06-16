"""
Tests de las secciones nuevas del reporte case-scoped: resumen ejecutivo,
capacidad vs. tolerancia, y diversificación en métricas.
"""

from __future__ import annotations

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


def _gen(capacity=True, override=True):
    kyc = _low_capacity_kyc()
    cap = None
    if capacity:
        cap = {
            "deterministic": deterministic_assessment(kyc),
            "capacity_gap": capacity_gap_from_kyc(kyc),
        }
    cand = _candidate()
    md, _ = CaseMarkdownReportGenerator().generate(
        case_data={"case_id": "c1", "title": "Juan Pérez", "status": "PORTFOLIO_SELECTED"},
        selection_data={"selected_variant": "GROWTH", "selected_candidate": cand,
                        "selection_id": "s1", "proposal_id": "p1",
                        "override_approval_id": "o1" if override else None},
        approval_data={"approved_profile": "moderado-agresivo", "decision": "modify"},
        override_data={"override_approval_id": "o1"} if override else None,
        capacity_data=cap,
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
