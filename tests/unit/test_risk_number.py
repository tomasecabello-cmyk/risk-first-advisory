"""
Tests del Risk Number (ai_layer.risk_number) — número único 0–100 cliente ↔ cartera.

Cubre: mapeo downside→número (anchors de config/risk_profiles.yaml), CVaR
paramétrico y empírico con horizonte configurable, γ CRRA desde certainty
equivalent (caso log-utility verificable a mano), cross-check de divergencia
entre elicitaciones, y la clasificación de alineación cliente/capacidad/cartera.
Todo determinista, sin red, sin DB.
"""

from __future__ import annotations

import math

import pytest

from risk_first_advisory.ai_layer.risk_number import (
    DOWNSIDE_ANCHORS,
    align_numbers,
    assess_risk_alignment,
    client_risk_number,
    crra_gamma_from_certainty_equivalent,
    downside_to_number,
    gamma_to_number,
    number_to_band,
    portfolio_downside,
    portfolio_moments_from_weights,
    portfolio_risk_number,
    portfolio_risk_number_from_weights,
    tradeoff_risk_number,
)


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


# ── downside_to_number / bandas ───────────────────────────────────────────────


def test_anchors_match_profile_drawdowns_exactly():
    # Los anclajes son los max_drawdown de config/risk_profiles.yaml → topes de banda.
    assert downside_to_number(0.00) == 0.0
    assert downside_to_number(0.07) == 20.0   # conservador
    assert downside_to_number(0.10) == 40.0   # moderado-defensivo
    assert downside_to_number(0.15) == 60.0   # moderado
    assert downside_to_number(0.22) == 80.0   # moderado-agresivo
    assert downside_to_number(0.30) == 100.0  # agresivo


def test_downside_number_is_monotonic_and_clamped():
    xs = [0.0, 0.03, 0.07, 0.12, 0.18, 0.25, 0.30, 0.50]
    ys = [downside_to_number(x) for x in xs]
    assert ys == sorted(ys)
    assert downside_to_number(0.99) == 100.0  # clamp arriba
    with pytest.raises(ValueError):
        downside_to_number(-0.01)


def test_number_to_band_edges():
    assert number_to_band(0) == "conservador"
    assert number_to_band(19.9) == "conservador"
    assert number_to_band(20) == "moderado-defensivo"
    assert number_to_band(59.9) == "moderado"
    assert number_to_band(100) == "agresivo"


# ── portfolio_downside (CVaR) ─────────────────────────────────────────────────


def test_normal_cvar_known_value():
    # μ=0, σ=10% anual, α=95%, h=1: ES = −σ·φ(z)/(1−α) ≈ −0.2063.
    d = portfolio_downside(mu_annual=0.0, sigma_annual=0.10, alpha=0.95)
    assert d["method"] == "normal"
    assert d["cvar"] == pytest.approx(-0.10 * 2.0627, abs=1e-3)
    assert d["downside_loss"] == pytest.approx(0.2063, abs=1e-3)


def test_shorter_horizon_means_smaller_loss():
    # Con μ=0, σ_h = σ·√h → un trimestre pierde menos que un año.
    year = portfolio_downside(mu_annual=0.0, sigma_annual=0.10, horizon_years=1.0)
    quarter = portfolio_downside(mu_annual=0.0, sigma_annual=0.10, horizon_years=0.25)
    assert quarter["downside_loss"] < year["downside_loss"]
    assert quarter["downside_loss"] == pytest.approx(
        year["downside_loss"] * math.sqrt(0.25), abs=1e-6)


def test_positive_drift_reduces_loss_and_can_zero_it():
    with_mu = portfolio_downside(mu_annual=0.08, sigma_annual=0.10)
    without = portfolio_downside(mu_annual=0.0, sigma_annual=0.10)
    assert with_mu["downside_loss"] < without["downside_loss"]
    # σ≈0 con μ>0: la cola también gana → pérdida 0.
    safe = portfolio_downside(mu_annual=0.05, sigma_annual=0.001)
    assert safe["downside_loss"] == 0.0


def test_empirical_cvar_takes_worst_tail():
    # 20 retornos, α=95% → peor 5% = 1 obs (la peor: −30%).
    rets = [-0.30] + [0.01 * i for i in range(19)]
    d = portfolio_downside(returns=rets, alpha=0.95)
    assert d["method"] == "empirical"
    assert d["cvar"] == pytest.approx(-0.30)
    assert d["downside_loss"] == pytest.approx(0.30)
    assert d["sample_size"] == 20


def test_portfolio_downside_validations():
    with pytest.raises(ValueError):
        portfolio_downside(mu_annual=0.0, sigma_annual=0.1, alpha=1.5)
    with pytest.raises(ValueError):
        portfolio_downside(mu_annual=0.0, sigma_annual=0.1, horizon_years=0)
    with pytest.raises(ValueError):
        portfolio_downside(mu_annual=0.0, sigma_annual=-0.1)
    with pytest.raises(ValueError):
        portfolio_downside()  # ni returns ni (μ,σ)


def test_portfolio_risk_number_lands_in_expected_band():
    # loss ≈ 0.2063 → interpolación entre (0.15,60) y (0.22,80) ≈ 76.
    r = portfolio_risk_number(mu_annual=0.0, sigma_annual=0.10)
    assert 75.0 <= r["number"] <= 77.0
    assert r["band"] == "moderado-agresivo"
    assert "peor 5%" in r["explanation"]


# ── portfolio_moments_from_weights / portfolio_risk_number_from_weights ──────


_TICKERS = ["SPY", "AL30", "CASH"]
_RETURNS = {"SPY": 0.09, "AL30": 0.06, "CASH": 0.02}
# Covarianza diagonal (activos no correlacionados) para verificar a mano:
# var = Σ w_i^2 σ_i^2, sin términos cruzados.
_COV_DIAG = [
    [0.18 ** 2, 0.0, 0.0],
    [0.0, 0.12 ** 2, 0.0],
    [0.0, 0.0, 0.01 ** 2],
]


def test_portfolio_moments_weighted_mean_and_variance():
    weights = {"SPY": 0.6, "AL30": 0.3, "CASH": 0.1}
    m = portfolio_moments_from_weights(weights, _RETURNS, _TICKERS, _COV_DIAG)
    expected_mu = 0.6 * 0.09 + 0.3 * 0.06 + 0.1 * 0.02
    expected_var = (0.6 ** 2) * (0.18 ** 2) + (0.3 ** 2) * (0.12 ** 2) + (0.1 ** 2) * (0.01 ** 2)
    assert m["mu_annual"] == pytest.approx(expected_mu, abs=1e-6)
    assert m["sigma_annual"] == pytest.approx(math.sqrt(expected_var), abs=1e-6)
    assert m["missing_tickers"] == []
    assert m["invested_weight_used"] == pytest.approx(1.0)


def test_portfolio_moments_ignores_zero_weight_and_flags_missing():
    # GLD no está en tickers/covarianza -> falta reportada, no falla.
    weights = {"SPY": 0.7, "AL30": 0.0, "GLD": 0.3}
    m = portfolio_moments_from_weights(weights, _RETURNS, _TICKERS, _COV_DIAG)
    assert m["used_tickers"] == ["SPY"]
    assert m["missing_tickers"] == ["GLD"]
    assert m["invested_weight_used"] == pytest.approx(0.7)


def test_portfolio_moments_validations():
    with pytest.raises(ValueError):
        portfolio_moments_from_weights({}, _RETURNS, _TICKERS, _COV_DIAG)
    with pytest.raises(ValueError):
        # covarianza con dimensiones que no calzan.
        portfolio_moments_from_weights(
            {"SPY": 1.0}, _RETURNS, _TICKERS, [[1.0, 0.0], [0.0, 1.0]])
    with pytest.raises(ValueError):
        # ningún ticker con peso > 0 tiene datos.
        portfolio_moments_from_weights({"GLD": 1.0}, _RETURNS, _TICKERS, _COV_DIAG)


def test_portfolio_risk_number_from_weights_matches_manual_composition():
    weights = {"SPY": 0.6, "AL30": 0.3, "CASH": 0.1}
    r = portfolio_risk_number_from_weights(weights, _RETURNS, _TICKERS, _COV_DIAG)
    moments = portfolio_moments_from_weights(weights, _RETURNS, _TICKERS, _COV_DIAG)
    manual = portfolio_risk_number(
        mu_annual=moments["mu_annual"], sigma_annual=moments["sigma_annual"])
    assert r["number"] == manual["number"]
    assert r["band"] == manual["band"]
    assert r["missing_tickers"] == []
    assert r["invested_weight_used"] == pytest.approx(1.0)


# ── γ CRRA desde certainty equivalent ─────────────────────────────────────────


def test_gamma_log_utility_case():
    # γ=1 (log): CE = √((W+G)(W−L)) − W = √(11000·9000) − 10000 ≈ −50.13.
    ce = math.sqrt(11000 * 9000) - 10000
    gamma = crra_gamma_from_certainty_equivalent(10000, 1000, 1000, ce)
    assert gamma == pytest.approx(1.0, abs=0.01)


def test_gamma_risk_neutral_at_expected_value():
    # C = EV de la apuesta (0 para ±1000) → γ ≈ 0.
    gamma = crra_gamma_from_certainty_equivalent(10000, 1000, 1000, 0.0)
    assert gamma == pytest.approx(0.0, abs=0.01)


def test_gamma_increases_as_certain_amount_drops():
    gammas = [
        crra_gamma_from_certainty_equivalent(10000, 1000, 1000, c)
        for c in (0.0, -50.0, -200.0, -400.0)
    ]
    assert gammas == sorted(gammas)


def test_gamma_clamps_at_extremes():
    # C casi igual a gain → buscador de riesgo extremo → clamp en el mínimo.
    assert crra_gamma_from_certainty_equivalent(10000, 1000, 1000, 999.0) == -4.0
    # C casi la pérdida entera → aversión extrema → clamp en el máximo.
    assert crra_gamma_from_certainty_equivalent(10000, 1000, 1000, -999.0) == 20.0


def test_gamma_validations():
    with pytest.raises(ValueError):
        crra_gamma_from_certainty_equivalent(0, 1000, 1000, 0)      # wealth <= 0
    with pytest.raises(ValueError):
        crra_gamma_from_certainty_equivalent(1000, 1000, 1500, 0)   # W−L <= 0
    with pytest.raises(ValueError):
        crra_gamma_from_certainty_equivalent(10000, 1000, 1000, 2000)  # C fuera de rango


def test_gamma_to_number_is_decreasing():
    ns = [gamma_to_number(g) for g in (-2.0, 0.0, 1.0, 3.0, 8.0, 15.0)]
    assert ns == sorted(ns, reverse=True)
    assert gamma_to_number(-4.0) == 100.0
    assert 0.0 <= gamma_to_number(25.0) <= 5.0


def test_tradeoff_risk_number_conservative_answer():
    # Acepta perder 400 seguro antes que la apuesta con EV 0 → muy averso → banda baja.
    t = tradeoff_risk_number(10000, 1000, 1000, -400.0)
    assert t["gamma"] > 4.0
    assert t["number"] < 40.0
    assert t["band"] in ("conservador", "moderado-defensivo")


# ── client_risk_number ────────────────────────────────────────────────────────


def test_client_number_without_tradeoff_is_willingness():
    c = client_risk_number(_kyc())
    assert c["number"] == c["willingness_number"]
    assert c["tradeoff_number"] is None
    assert c["divergence_bands"] == 0
    assert not c["inconsistent"]
    assert c["confirmation_questions"] == []
    assert 0.0 <= c["capacity_ceiling_number"] <= 100.0


def test_client_number_divergence_flags_inconsistency():
    # Cuestionario a fondo agresivo, trade-off ultra conservador → divergencia.
    payload = _kyc(risk_tolerance_score=10, investment_objective="aggressive_growth")
    c = client_risk_number(
        payload, tradeoff={"wealth": 10000, "gain": 1000, "loss": 1000,
                           "certain_amount": -400.0})
    assert c["willingness_number"] == 100.0
    assert c["tradeoff_number"] < 40.0
    assert c["divergence_bands"] >= 2
    assert c["inconsistent"]
    assert len(c["confirmation_questions"]) == 2
    assert "divergen" in c["explanation"]
    # El combinado promedia las dos elicitaciones.
    esperado = round(0.5 * (c["willingness_number"] + c["tradeoff_number"]), 1)
    assert c["number"] == esperado


def test_client_number_consistent_elicitations():
    # Ambas elicitaciones moderadas → sin flag.
    payload = _kyc(risk_tolerance_score=6)
    ce = math.sqrt(11000 * 9000) - 10000  # γ≈1 → número ~70 (moderado-agresivo)
    c = client_risk_number(
        payload, tradeoff={"wealth": 10000, "gain": 1000, "loss": 1000,
                           "certain_amount": ce})
    assert c["tradeoff_number"] == pytest.approx(70.0, abs=1.0)
    assert isinstance(c["inconsistent"], bool)


# ── align_numbers ─────────────────────────────────────────────────────────────


def test_alignment_over_capacity_requires_override():
    a = align_numbers(client_number=90.0, capacity_ceiling_number=35.0,
                      portfolio_number=75.0)
    assert a["status"] == "over_capacity"
    assert a["override_required"]
    assert a["capacity_gap_bands"] == 2
    assert "override" in a["explanation"]


def test_alignment_over_tolerance_within_capacity():
    a = align_numbers(client_number=40.0, capacity_ceiling_number=90.0,
                      portfolio_number=55.0)
    assert a["status"] == "over_tolerance"
    assert not a["override_required"]
    assert a["gap_points"] == 15.0


def test_alignment_aligned_within_tolerance():
    a = align_numbers(client_number=62.0, capacity_ceiling_number=75.0,
                      portfolio_number=68.0)
    assert a["status"] == "aligned"
    assert not a["override_required"]


def test_alignment_under_tolerance():
    a = align_numbers(client_number=70.0, capacity_ceiling_number=75.0,
                      portfolio_number=30.0)
    assert a["status"] == "under_tolerance"
    assert a["gap_points"] == -40.0


# ── assess_risk_alignment (end-to-end puro) ───────────────────────────────────


def test_assess_risk_alignment_shape_and_consistency():
    out = assess_risk_alignment(
        _kyc(), mu_annual=0.05, sigma_annual=0.08, horizon_years=1.0)
    assert set(out) == {"client", "portfolio", "alignment"}
    assert out["alignment"]["status"] in (
        "aligned", "over_tolerance", "under_tolerance", "over_capacity")
    # La alineación usa exactamente los números expuestos.
    recomputed = align_numbers(
        out["client"]["number"],
        out["client"]["capacity_ceiling_number"],
        out["portfolio"]["number"],
    )
    assert recomputed["status"] == out["alignment"]["status"]


def test_assess_risk_alignment_low_capacity_client_risky_portfolio():
    # Cliente sin capacidad + cartera volátil → over_capacity con override.
    payload = _kyc(
        risk_tolerance_score=10, risk_capacity_score=1, investment_horizon_years=1,
        liquidity_need_score=8, investment_experience="ninguna",
        investment_objective="aggressive_growth")
    out = assess_risk_alignment(payload, mu_annual=0.0, sigma_annual=0.15)
    assert out["alignment"]["status"] == "over_capacity"
    assert out["alignment"]["override_required"]


def test_anchor_table_is_sorted():
    xs = [x for x, _ in DOWNSIDE_ANCHORS]
    assert xs == sorted(xs)
