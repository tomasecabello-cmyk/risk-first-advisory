"""
Tests del M-Engine — motor de scoring determinístico (ai_layer.risk_scoring).

Cubre: perfil declarado (bandas + capacidad-acota-tolerancia), señal revelada,
y el Risk Gap real (alineado / pánico / contradicción willingness-vs-ability).
"""

from __future__ import annotations

from risk_first_advisory.ai_layer.risk_scoring import (
    PROFILES,
    assess_revealed_signal,
    compute_capacity_score,
    capacity_gap_from_kyc,
    compute_risk_gap,
    compute_tolerance_score,
    explain_capacity_gap,
    score_stated_profile,
)
from risk_first_advisory.api_layer.schemas import RiskGap


def _kyc(**over):
    base = {
        "risk_tolerance_score": 5,
        "risk_capacity_score": 5,
        "investment_horizon_years": 7,
        "liquidity_need_score": 5,
        "investment_experience": "moderada",
        "investment_objective": "balanced",
        "open_risk_reaction": "",
    }
    base.update(over)
    return base


# ── score_stated_profile ──────────────────────────────────────────────────────


def test_stated_low_everything_is_conservador():
    s = score_stated_profile(_kyc(
        risk_tolerance_score=1, risk_capacity_score=1, investment_horizon_years=1,
        liquidity_need_score=8, investment_experience="ninguna",
        investment_objective="capital_preservation"))
    assert s["profile"] == "conservador"


def test_stated_high_everything_is_agresivo():
    s = score_stated_profile(_kyc(
        risk_tolerance_score=10, risk_capacity_score=10, investment_horizon_years=20,
        liquidity_need_score=3, investment_experience="experto",
        investment_objective="aggressive_growth"))
    assert s["profile"] == "agresivo"


def test_capacity_caps_tolerance():
    # Alta tolerancia pero baja capacidad/horizonte -> el perfil efectivo baja.
    s = score_stated_profile(_kyc(
        risk_tolerance_score=10, risk_capacity_score=2, investment_horizon_years=2,
        liquidity_need_score=8, investment_experience="ninguna",
        investment_objective="aggressive_growth"))
    assert s["binding_dimension"] == "ability"
    assert s["profile"] in ("conservador", "moderado-defensivo")
    assert s["internal_gap_bands"] >= 3  # quiere mucho más de lo que puede


def test_stated_moderate_is_consistent():
    s = score_stated_profile(_kyc())
    assert s["profile"] == "moderado"
    assert s["internal_gap_bands"] == 0


# ── assess_revealed_signal ────────────────────────────────────────────────────


def test_revealed_panic_is_lower():
    assert assess_revealed_signal(_kyc(open_risk_reaction="Si cae 30% vendo todo"))["direction"] == "lower"


def test_revealed_composed():
    assert assess_revealed_signal(_kyc(open_risk_reaction="Mantengo a largo plazo, aprovecho"))["direction"] == "composed"


def test_revealed_empty_is_none():
    assert assess_revealed_signal(_kyc(open_risk_reaction=""))["direction"] == "none"


# ── compute_risk_gap ──────────────────────────────────────────────────────────


def test_gap_aligned_is_low():
    gap = compute_risk_gap(_kyc(open_risk_reaction="Mantengo posiciones, largo plazo"))
    assert gap["gap_level"] == "low"
    assert "consistente" in gap["gap_explanation"].lower()


def test_gap_panic_aggressive_is_high():
    gap = compute_risk_gap(_kyc(
        risk_tolerance_score=9, risk_capacity_score=8, investment_horizon_years=10,
        liquidity_need_score=3, investment_experience="avanzada",
        investment_objective="aggressive_growth",
        open_risk_reaction="Si cae vendo todo, no lo soporto"))
    assert gap["gap_level"] == "high"
    assert "inconsistencia" in gap["gap_explanation"].lower()


def test_gap_willingness_exceeds_ability_flags():
    gap = compute_risk_gap(_kyc(
        risk_tolerance_score=10, risk_capacity_score=2, investment_horizon_years=2,
        liquidity_need_score=8, investment_experience="ninguna",
        investment_objective="aggressive_growth", open_risk_reaction=""))
    assert gap["gap_level"] in ("medium", "high")
    assert gap["_severity_bands"] >= 2


def test_gap_deterministic():
    k = _kyc(risk_tolerance_score=9, open_risk_reaction="vendo todo")
    assert compute_risk_gap(k) == compute_risk_gap(k)


def test_gap_builds_valid_riskgap_schema():
    gap = compute_risk_gap(_kyc(
        risk_tolerance_score=9, investment_objective="growth",
        open_risk_reaction="me asusto y vendo"))
    public = {k: v for k, v in gap.items() if not k.startswith("_")}
    rg = RiskGap(**public)  # extra="forbid": las claves publicas deben matchear exactamente
    assert rg.gap_level in ("low", "medium", "high")
    assert rg.declared_profile in PROFILES


def test_handles_missing_fields_without_crashing():
    gap = compute_risk_gap({})
    assert gap["declared_profile"] in PROFILES
    assert gap["gap_level"] in ("low", "medium", "high")


# ─────────────────────────────────────────────────────────────────────────────
# Capacidad medida de hechos (no fabricada de la tolerancia)
# ─────────────────────────────────────────────────────────────────────────────


def test_compute_capacity_score_high_vs_low():
    high = compute_capacity_score({
        "annual_income_usd": 50000, "liquid_net_worth": 300000,  # colchón 6x
        "investment_horizon_years": 20, "income_stability": "stable",
        "essential_expenses_covered": True, "dependents_count": 0,
    })
    low = compute_capacity_score({
        "annual_income_usd": 80000, "liquid_net_worth": 8000,  # colchón 0.1x
        "investment_horizon_years": 1, "income_stability": "unstable",
        "essential_expenses_covered": False, "dependents_count": 4,
    })
    assert 1.0 <= low <= 10.0 and 1.0 <= high <= 10.0
    assert high >= 8.0 and low <= 3.0


def test_capacity_from_facts_caps_high_tolerance():
    # Tolerancia declarada alta + capacity_score declarado alto, pero los HECHOS
    # dicen baja capacidad -> con capacity_from_facts la capacidad acota.
    payload = {
        "risk_tolerance_score": 10, "risk_capacity_score": 10,  # declarado (placeholder)
        "investment_objective": "growth", "investment_horizon_years": 1,
        "liquidity_need_score": 9, "investment_experience": "ninguna",
        "annual_income_usd": 80000, "liquid_net_worth": 5000,
        "income_stability": "unstable", "essential_expenses_covered": False,
        "dependents_count": 3, "capacity_from_facts": True,
    }
    s = score_stated_profile(payload)
    assert s["binding_dimension"] == "ability"  # la capacidad financiera limita
    assert s["ability"] < 0.4
    # Sin el flag, el score declarado (10) mandaría -> ability alta. Contraste:
    legacy = score_stated_profile({**payload, "capacity_from_facts": False})
    assert legacy["ability"] > s["ability"]


# ─────────────────────────────────────────────────────────────────────────────
# Tolerancia medida con Grable-Lytton (no slider autoreportado)
# ─────────────────────────────────────────────────────────────────────────────


def test_compute_tolerance_score_high_vs_low():
    high = compute_tolerance_score({"tolerance_answers": {
        "q1": "a", "q2": "d", "q3": "d", "q4": "c", "q5": "c", "q6": "d", "q7": "d",
        "q8": "d", "q9": "b", "q10": "b", "q11": "d", "q12": "c", "q13": "d",
    }})
    low = compute_tolerance_score({"tolerance_answers": {
        "q1": "d", "q2": "a", "q3": "a", "q4": "a", "q5": "a", "q6": "a", "q7": "a",
        "q8": "a", "q9": "a", "q10": "a", "q11": "a", "q12": "a", "q13": "a",
    }})
    assert high == 10.0 and low == 1.0


def test_tolerance_from_questionnaire_gate_overrides_slider():
    # Slider declara bajo (2) pero el cuestionario G-L sale máximo → willingness alta.
    base = {
        "risk_tolerance_score": 2, "investment_objective": "growth",
        "risk_capacity_score": 9, "investment_horizon_years": 20,
        "liquidity_need_score": 3, "investment_experience": "avanzada",
        "tolerance_from_questionnaire": True,
        "tolerance_answers": {
            "q1": "a", "q2": "d", "q3": "d", "q4": "c", "q5": "c", "q6": "d",
            "q7": "d", "q8": "d", "q9": "b", "q10": "b", "q11": "d", "q12": "c", "q13": "d",
        },
    }
    s = score_stated_profile(base)
    # Sin el flag mandaría el slider (2 → willingness baja). Con el flag, el
    # cuestionario manda → willingness alta.
    legacy = score_stated_profile({**base, "tolerance_from_questionnaire": False})
    assert s["willingness"] > legacy["willingness"]


# ── explain_capacity_gap (conversación pre-override) ──────────────────────────


def _kyc_low_capacity(**over):
    # Capacidad TODA mal → ability bajísima (tope conservador), sin importar tolerancia.
    base = {
        "capacity_from_facts": True,
        "annual_income_usd": 80000,
        "liquid_net_worth": 5000,
        "net_worth": 10000,
        "investment_horizon_years": 1,
        "liquidity_need_score": 8,
        "investment_experience": "ninguna",
        "income_stability": "inestable",
        "dependents_count": 3,
        "essential_expenses_covered": False,
        "investment_objective": "aggressive_growth",
    }
    base.update(over)
    return base


def test_explain_capacity_gap_exceeds_requires_override():
    # Cliente con capacidad muy baja que quiere agresivo: el perfil supera el tope.
    g = explain_capacity_gap(_kyc_low_capacity(), "agresivo")
    assert g["capacity_ceiling"] == "conservador"
    assert g["exceeds_capacity"] is True
    assert g["override_required"] is True
    assert g["bands_over"] == PROFILES.index("agresivo") - PROFILES.index("conservador")
    assert g["binding_dimension"] == "ability"
    assert "override" in g["explanation"].lower()
    assert "agresivo" in g["explanation"]


def test_explain_capacity_gap_within_capacity_no_override():
    g = explain_capacity_gap(_kyc_low_capacity(), "conservador")
    assert g["exceeds_capacity"] is False
    assert g["override_required"] is False
    assert g["bands_over"] == 0
    assert "no requiere override" in g["explanation"].lower()


def test_explain_capacity_gap_bands_count_is_distance():
    # Un escalón por encima del tope → exactamente 1 banda.
    g = explain_capacity_gap(_kyc_low_capacity(), "moderado-defensivo")
    assert g["bands_over"] == 1
    assert g["exceeds_capacity"] is True


def test_explain_capacity_gap_is_pure():
    payload = _kyc_low_capacity()
    assert explain_capacity_gap(payload, "agresivo") == explain_capacity_gap(payload, "agresivo")


def test_capacity_gap_from_kyc_uses_willingness_as_desired():
    # Tolerancia agresiva + capacidad pésima: el "deseado" sale de willingness
    # (alto) y el tope de la capacidad (conservador) → override requerido.
    agressive_tol = {
        "tolerance_from_questionnaire": True,
        "tolerance_answers": {
            "q1": "a", "q2": "d", "q3": "d", "q4": "c", "q5": "c", "q6": "d",
            "q7": "d", "q8": "d", "q9": "b", "q10": "b", "q11": "d", "q12": "c", "q13": "d",
        },
    }
    g = capacity_gap_from_kyc({**_kyc_low_capacity(), **agressive_tol})
    assert g["capacity_ceiling"] == "conservador"
    assert g["override_required"] is True
    # desired = perfil que implica la tolerancia (más riesgoso que el tope)
    assert PROFILES.index(g["desired_profile"]) > PROFILES.index(g["capacity_ceiling"])
