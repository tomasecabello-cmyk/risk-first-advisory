"""
Tests del Risk Gap — mapper puro (ai_layer.risk_gap) + schema (api_layer.schemas.RiskGap).

Cobertura M-Demo:
    - derive_risk_gap determinístico desde el output de analyze_kyc.
    - severidades en inglés y español.
    - estado alineado (sin contradicciones) → gap_level low.
    - perfil declarado ausente → None.
    - señal de estrés desde open_risk_reaction.
    - follow_up_questions usados y capeados a 2; defaults si no hay.
    - RiskGap valida gap_level (Literal) y rechaza claves extra (sin confidence).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from risk_first_advisory.ai_layer.risk_gap import combine_risk_gaps, derive_risk_gap
from risk_first_advisory.api_layer.schemas import RiskGap

# ─────────────────────────────────────────────────────────────────────────────
# derive_risk_gap
# ─────────────────────────────────────────────────────────────────────────────


def test_aligned_no_contradictions_is_low():
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [],
        "follow_up_questions": [],
    }
    gap = derive_risk_gap(result)
    assert gap is not None
    assert gap["declared_profile"] == "moderado"
    assert gap["gap_level"] == "low"
    assert "consistente" in gap["gap_explanation"].lower()
    # Estado alineado usa preguntas por defecto (no hay follow-ups).
    assert len(gap["confirmation_questions"]) == 2


def test_high_severity_contradiction_is_high():
    result = {
        "preliminary_profile": "agresivo",
        "contradictions": [
            {"field": "drawdown", "severity": "high", "explanation": "Declara agresivo pero teme perder."},
        ],
        "follow_up_questions": [],
    }
    gap = derive_risk_gap(result)
    assert gap["gap_level"] == "high"
    assert "inconsistencia" in gap["gap_explanation"].lower()


def test_spanish_severity_media_is_medium():
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [
            {"field": "x", "severity": "media", "description": "señal media"},
        ],
    }
    gap = derive_risk_gap(result)
    assert gap["gap_level"] == "medium"


def test_mixed_severity_takes_highest():
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [
            {"field": "a", "severity": "low", "explanation": "x"},
            {"field": "b", "severity": "high", "explanation": "y"},
        ],
    }
    assert derive_risk_gap(result)["gap_level"] == "high"


def test_missing_profile_returns_none():
    assert derive_risk_gap({"contradictions": []}) is None
    assert derive_risk_gap({"preliminary_profile": None}) is None
    assert derive_risk_gap("not a dict") is None  # type: ignore[arg-type]


def test_stress_signal_from_kyc_open_risk_reaction():
    result = {"preliminary_profile": "moderado", "contradictions": []}
    kyc = {"open_risk_reaction": "Ante una caída del 30% vendería todo."}
    gap = derive_risk_gap(result, kyc)
    assert gap["stress_signal"] == "Ante una caída del 30% vendería todo."


def test_follow_up_questions_used_and_capped_at_two():
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [{"field": "a", "severity": "medium", "explanation": "x"}],
        "follow_up_questions": ["Q1", "Q2", "Q3"],
    }
    gap = derive_risk_gap(result)
    assert gap["confirmation_questions"] == ["Q1", "Q2"]


def test_no_double_period_when_contradiction_ends_in_period():
    # Regression: ISSUE-QA-001 — gap_explanation mostraba ".." cuando la
    # explicación de la contradicción ya terminaba en ".".
    # Found by /qa on 2026-06-03
    # Report: .gstack/qa-reports/qa-report-127-0-0-1-2026-06-03.md
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [
            {"field": "x", "severity": "medium",
             "explanation": "El cliente indica que vendería todo."},
        ],
    }
    gap = derive_risk_gap(result)
    assert ".." not in gap["gap_explanation"]


def test_deterministic_same_input_same_output():
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [{"field": "a", "severity": "high", "explanation": "x"}],
        "follow_up_questions": [],
    }
    assert derive_risk_gap(result) == derive_risk_gap(result)


# ─────────────────────────────────────────────────────────────────────────────
# RiskGap schema
# ─────────────────────────────────────────────────────────────────────────────


def test_riskgap_schema_valid_and_serializes_expected_keys():
    rg = RiskGap(
        declared_profile="moderado",
        stress_signal="vendería todo",
        gap_level="medium",
        gap_explanation="inconsistencia",
        confirmation_questions=["a", "b"],
    )
    dumped = rg.model_dump()
    assert set(dumped.keys()) == {
        "declared_profile",
        "stress_signal",
        "gap_level",
        "gap_explanation",
        "confirmation_questions",
        "agreement",
    }
    assert dumped["gap_level"] == "medium"


def test_riskgap_rejects_invalid_gap_level():
    with pytest.raises(ValidationError):
        RiskGap(
            declared_profile="moderado",
            gap_level="critical",  # no está en el Literal
            gap_explanation="x",
            confirmation_questions=[],
        )


def test_riskgap_forbids_numeric_confidence():
    # extra="forbid": un confidence numérico inventado debe ser rechazado.
    with pytest.raises(ValidationError):
        RiskGap(
            declared_profile="moderado",
            gap_level="low",
            gap_explanation="x",
            confirmation_questions=[],
            confidence=0.78,  # type: ignore[call-arg]
        )


def test_riskgap_can_be_built_from_mapper_output():
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [{"field": "a", "severity": "high", "explanation": "x"}],
        "follow_up_questions": ["Q1"],
    }
    gap = derive_risk_gap(result, {"open_risk_reaction": "pánico"})
    rg = RiskGap(**gap)
    assert rg.gap_level == "high"
    assert rg.confirmation_questions == ["Q1"]


# ─────────────────────────────────────────────────────────────────────────────
# Reporte markdown — sección condicional Risk Gap
# ─────────────────────────────────────────────────────────────────────────────


def _minimal_report_inputs():
    case_data = {"case_id": "case_x", "status": "PORTFOLIO_SELECTED", "title": "t"}
    selection_data = {
        "selected_variant": "BALANCED",
        "selected_candidate": {"objective": "balanced", "weights": {"AAA": 1.0}},
        "selection_id": "sel_1",
        "proposal_id": "prop_1",
        "override_approval_id": None,
    }
    return case_data, selection_data


def test_report_includes_risk_gap_section_when_analysis_present():
    from risk_first_advisory.reporting_layer.case_markdown_report import (
        CaseMarkdownReportGenerator,
    )

    case_data, selection_data = _minimal_report_inputs()
    analysis_data = {
        "result": {
            "preliminary_profile": "moderado",
            "contradictions": [
                {"field": "drawdown", "severity": "high", "explanation": "teme perder"},
            ],
            "follow_up_questions": [],
        }
    }
    md, _ = CaseMarkdownReportGenerator().generate(
        case_data=case_data,
        selection_data=selection_data,
        analysis_data=analysis_data,
        generated_at_utc="2026-06-03T00:00:00Z",
    )
    assert "Risk Gap" in md
    assert "perfil declarado" in md.lower()


def test_report_omits_risk_gap_section_when_analysis_none():
    from risk_first_advisory.reporting_layer.case_markdown_report import (
        CaseMarkdownReportGenerator,
    )

    case_data, selection_data = _minimal_report_inputs()
    md, _ = CaseMarkdownReportGenerator().generate(
        case_data=case_data,
        selection_data=selection_data,
        analysis_data=None,
        generated_at_utc="2026-06-03T00:00:00Z",
    )
    assert "Risk Gap" not in md  # backward-compat: sin análisis, sin sección


# ─────────────────────────────────────────────────────────────────────────────
# _DemoProfileClient (RFA_DEMO_MODE) — determinístico, sin OPENAI_API_KEY
# ─────────────────────────────────────────────────────────────────────────────


def test_demo_client_panic_reaction_yields_medium_gap():
    from risk_first_advisory.api_layer.main import _DemoProfileClient

    res = _DemoProfileClient().analyze_kyc(
        {"open_risk_reaction": "Ante una caída del 30% vendería todo."}
    )
    gap = derive_risk_gap(res, {"open_risk_reaction": "vendería todo"})
    assert gap["gap_level"] == "medium"
    assert gap["confirmation_questions"]  # no vacío


def test_demo_client_calm_reaction_yields_low_gap():
    from risk_first_advisory.api_layer.main import _DemoProfileClient

    res = _DemoProfileClient().analyze_kyc(
        {"open_risk_reaction": "Mantendría la inversión, sé que es a largo plazo."}
    )
    gap = derive_risk_gap(res)
    assert gap["gap_level"] == "low"


def test_demo_client_is_deterministic():
    from risk_first_advisory.api_layer.main import _DemoProfileClient

    payload = {"open_risk_reaction": "saldría de todo por miedo"}
    assert _DemoProfileClient().analyze_kyc(payload) == _DemoProfileClient().analyze_kyc(payload)


# ─────────────────────────────────────────────────────────────────────────────
# combine_risk_gaps — IA + motor determinístico (M-Engine)
# ─────────────────────────────────────────────────────────────────────────────


def _calm_moderate_kyc():
    return {
        "risk_tolerance_score": 5, "risk_capacity_score": 5,
        "investment_horizon_years": 7, "liquidity_need_score": 5,
        "investment_experience": "moderada", "investment_objective": "balanced",
        "open_risk_reaction": "Mantengo posiciones, largo plazo",
    }


def test_combine_no_ai_uses_base():
    # result sin preliminary_profile -> derive_risk_gap None -> solo base.
    out = combine_risk_gaps({"contradictions": []}, _calm_moderate_kyc())
    assert out["agreement"] == "solo-base (sin IA)"
    RiskGap(**out)  # debe armar un RiskGap valido


def test_combine_ai_and_base_agree():
    result = {"preliminary_profile": "moderado", "contradictions": [], "follow_up_questions": []}
    out = combine_risk_gaps(result, _calm_moderate_kyc())
    assert out["agreement"] == "coinciden"
    assert out["gap_level"] == "low"
    RiskGap(**out)


def test_combine_ai_and_base_differ_takes_more_severe():
    # IA marca high (contradiccion alta); base de un KYC calmo/consistente da low.
    result = {
        "preliminary_profile": "moderado",
        "contradictions": [{"field": "x", "severity": "high", "explanation": "teme perder"}],
        "follow_up_questions": ["Q1"],
    }
    out = combine_risk_gaps(result, _calm_moderate_kyc())
    assert out["gap_level"] == "high"            # el mas severo
    assert "difieren" in out["agreement"]
    assert "IA: high" in out["agreement"] and "base: low" in out["agreement"]
    RiskGap(**out)


def test_combine_explanation_coherent_when_base_more_severe():
    # Regresión: el badge mostraba "Medio" (base) pero el texto decía
    # "consistente" (IA). La explicación DEBE venir de la fuente más severa.
    # KYC con gran spread willingness-vs-ability -> base medium/high; IA low.
    result = {"preliminary_profile": "moderado", "contradictions": [], "follow_up_questions": []}
    kyc = {
        "risk_tolerance_score": 10, "risk_capacity_score": 1,
        "investment_horizon_years": 1, "liquidity_need_score": 9,
        "investment_experience": "ninguna", "investment_objective": "growth",
        "open_risk_reaction": "Mantengo posiciones, largo plazo",
    }
    out = combine_risk_gaps(result, kyc)
    assert out["gap_level"] in {"medium", "high"}      # base manda
    assert "difieren" in out["agreement"]
    # La explicación NO debe afirmar que es consistente (sería incoherente con el badge).
    assert "es consistente" not in out["gap_explanation"].lower()
    RiskGap(**out)


def test_combine_explanation_mentions_cross_check():
    result = {"preliminary_profile": "moderado", "contradictions": [], "follow_up_questions": []}
    out = combine_risk_gaps(result, _calm_moderate_kyc())
    assert "base auditable" in out["gap_explanation"].lower()


def test_combine_handles_none_result():
    out = combine_risk_gaps(None, _calm_moderate_kyc())
    assert out["agreement"] == "solo-base (sin IA)"
    RiskGap(**out)
