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


def test_anchors_derive_from_config_max_volatility():
    # DD-012: los anclajes se DERIVAN del YAML (k·max_volatility por perfil),
    # no son copia a mano — si una firma edita el YAML, la escala lo sigue.
    from risk_first_advisory.ai_layer.risk_number import (
        DEFAULT_ALPHA,
        _cvar_loss_multiplier,
    )
    from risk_first_advisory.ai_layer.risk_scoring import PROFILES
    from risk_first_advisory.config_layer.risk_assumptions import (
        get_default_risk_profile_params,
    )

    params = get_default_risk_profile_params()
    k = _cvar_loss_multiplier(DEFAULT_ALPHA)
    assert DOWNSIDE_ANCHORS[0] == (0.0, 0.0)
    for i, profile in enumerate(PROFILES):
        x, y = DOWNSIDE_ANCHORS[i + 1]
        assert x == pytest.approx(k * params[profile]["max_volatility"], rel=1e-9)
        assert y == (i + 1) * 20.0


def test_budget_compliant_portfolio_never_bands_above_its_profile():
    # Garantía de la calibración: una cartera al tope de vol de su perfil
    # (mu >= 0) nunca banda por encima de ese perfil.
    from risk_first_advisory.ai_layer.risk_scoring import PROFILES
    from risk_first_advisory.config_layer.risk_assumptions import (
        get_default_risk_profile_params,
    )

    params = get_default_risk_profile_params()
    for i, profile in enumerate(PROFILES):
        max_vol = params[profile]["max_volatility"]
        at_cap = portfolio_risk_number(mu_annual=0.0, sigma_annual=max_vol)
        assert at_cap["number"] <= (i + 1) * 20.0
        with_mu = portfolio_risk_number(mu_annual=0.03, sigma_annual=max_vol)
        assert with_mu["number"] < (i + 1) * 20.0


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


def test_empty_returns_is_an_explicit_error():
    # Lista vacía provista NO es "ausente": error claro, sin fallback
    # silencioso al método paramétrico aunque haya (μ,σ) disponibles.
    with pytest.raises(ValueError, match="vacío"):
        portfolio_downside(returns=[], mu_annual=0.05, sigma_annual=0.1)
    with pytest.raises(ValueError, match="vacío"):
        portfolio_downside(returns=[])


def test_non_finite_inputs_raise_instead_of_reading_as_safe():
    # NaN/inf de un proveedor corrupto debe ser ERROR, no "riesgo 0 conservador".
    nan = float("nan")
    with pytest.raises(ValueError, match="finito"):
        portfolio_downside(mu_annual=nan, sigma_annual=0.10)
    with pytest.raises(ValueError, match="finito"):
        portfolio_downside(mu_annual=0.05, sigma_annual=float("inf"))
    with pytest.raises(ValueError, match="finitos"):
        portfolio_downside(returns=[0.01, nan, -0.05])


def test_nan_in_covariance_raises_instead_of_zero_risk():
    nan_cov = [
        [float("nan"), 0.0, 0.0],
        [0.0, 0.12 ** 2, 0.0],
        [0.0, 0.0, 0.01 ** 2],
    ]
    with pytest.raises(ValueError, match="no finitos"):
        portfolio_moments_from_weights(
            {"SPY": 0.6, "AL30": 0.3, "CASH": 0.1}, _RETURNS, _TICKERS, nan_cov)


def test_portfolio_risk_number_lands_in_expected_band():
    # σ=8%, μ=4%: loss = 0.08·2.0627 − 0.04 ≈ 0.1250 → entre el tope de
    # conservador (0.1031→20) y el de moderado-defensivo (0.1547→40) ≈ 28.5.
    r = portfolio_risk_number(mu_annual=0.04, sigma_annual=0.08)
    assert 27.5 <= r["number"] <= 29.5
    assert r["band"] == "moderado-defensivo"
    assert "peor 5%" in r["explanation"]


def test_explanation_tail_pct_never_reads_zero():
    # α=0.996 → cola 0.4%: el texto debe decir "0.4%", no "0%".
    r = portfolio_risk_number(mu_annual=0.0, sigma_annual=0.10, alpha=0.996)
    assert "peor 0%" not in r["explanation"]
    assert "peor 0.4%" in r["explanation"]


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


def test_portfolio_risk_number_from_weights_hand_computed():
    # Valores calculados A MANO (no vía las mismas funciones de producción):
    # μ = 0.6·0.09 + 0.3·0.06 + 0.1·0.02 = 0.074
    # σ = √(0.6²·0.18² + 0.3²·0.12² + 0.1²·0.01²) = √0.012961 ≈ 0.113846
    # loss = σ·2.06271 − μ ≈ 0.23483 − 0.074 = 0.16083
    # → entre tope mod-def (0.15470→40) y tope moderado (0.20627→60) ≈ 42.4
    weights = {"SPY": 0.6, "AL30": 0.3, "CASH": 0.1}
    r = portfolio_risk_number_from_weights(weights, _RETURNS, _TICKERS, _COV_DIAG)
    assert r["number"] == pytest.approx(42.4, abs=0.2)
    assert r["band"] == "moderado"
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


def test_gamma_is_scale_invariant_and_survives_huge_wealth():
    # CRRA es homotética: γ(W,G,L,C) == γ(sW,sG,sL,sC). Antes, riquezas
    # ≳1e17 crasheaban con ZeroDivisionError en el borde γ=20.
    g_small = crra_gamma_from_certainty_equivalent(10_000, 1_000, 500, 100)
    g_huge = crra_gamma_from_certainty_equivalent(1e18, 1e17, 5e16, 1e16)
    assert g_huge == pytest.approx(g_small, abs=1e-3)


def test_gamma_rejects_non_finite_inputs():
    with pytest.raises(ValueError, match="finito"):
        crra_gamma_from_certainty_equivalent(float("nan"), 1000, 500, 100)
    with pytest.raises(ValueError, match="finito"):
        crra_gamma_from_certainty_equivalent(10000, 1000, 500, float("inf"))


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


def test_client_number_without_tradeoff_within_capacity():
    # Base moderada: tolerancia < capacidad → el operativo ES la tolerancia.
    c = client_risk_number(_kyc())
    assert c["tolerance_number"] == c["willingness_number"]
    assert c["number"] == min(c["tolerance_number"], c["capacity_ceiling_number"])
    assert c["number"] == c["willingness_number"]
    assert c["tradeoff_number"] is None
    assert c["divergence_bands"] == 0
    assert not c["inconsistent"]
    assert c["confirmation_questions"] == []
    assert 0.0 <= c["capacity_ceiling_number"] <= 100.0


def test_client_number_is_capacity_capped():
    # Cliente ability-bound: quiere 100 pero su situación soporta mucho menos
    # → el número OPERATIVO es el techo (misma regla que deterministic.score).
    payload = _kyc(
        risk_tolerance_score=10, investment_objective="aggressive_growth",
        risk_capacity_score=1, investment_horizon_years=1,
        liquidity_need_score=8, investment_experience="ninguna")
    c = client_risk_number(payload)
    assert c["willingness_number"] == 100.0
    assert c["number"] == c["capacity_ceiling_number"]
    assert c["number"] < c["willingness_number"]
    assert "capacidad" in c["explanation"]


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
    # La tolerancia combinada promedia las dos elicitaciones; el operativo
    # además queda acotado por la capacidad.
    esperado = round(0.5 * (c["willingness_number"] + c["tradeoff_number"]), 1)
    assert c["tolerance_number"] == esperado
    assert c["number"] == round(
        min(esperado, c["capacity_ceiling_number"]), 1)


def test_client_number_consistent_elicitations():
    # Ambas elicitaciones cercanas (16.7 puntos < 20) → sin flag.
    payload = _kyc(risk_tolerance_score=6)
    ce = math.sqrt(11000 * 9000) - 10000  # γ≈1 → número ~70 (moderado-agresivo)
    c = client_risk_number(
        payload, tradeoff={"wealth": 10000, "gain": 1000, "loss": 1000,
                           "certain_amount": ce})
    assert c["tradeoff_number"] == pytest.approx(70.0, abs=1.0)
    assert not c["inconsistent"]


def test_divergence_needs_real_distance_not_a_band_edge():
    # 5.5 puntos de diferencia que CRUZAN un borde de banda (60.5 vs 55.0)
    # NO son inconsistencia; antes el corte por índices de banda la marcaba.
    payload = _kyc(risk_tolerance_score=7.075)  # willingness ≈ 60.5
    c = client_risk_number(
        payload, tradeoff={"wealth": 10000, "gain": 1000, "loss": 1000,
                           "certain_amount": -100.0})  # γ≈2 → 55.0
    assert c["willingness_number"] == pytest.approx(60.5, abs=0.3)
    assert c["tradeoff_number"] == pytest.approx(55.0, abs=0.5)
    assert abs(c["willingness_number"] - c["tradeoff_number"]) < 20.0
    assert not c["inconsistent"]
    assert c["divergence_bands"] == 0


# ── align_numbers ─────────────────────────────────────────────────────────────


def test_alignment_over_capacity_is_point_based():
    a = align_numbers(client_number=35.0, capacity_ceiling_number=35.0,
                      portfolio_number=75.0)
    assert a["status"] == "over_capacity"
    assert a["capacity_gap_points"] == 40.0
    assert "techo de capacidad" in a["explanation"]
    # La señal es informativa: el flag de override lo gobierna metadata (I-018).
    assert "override_required" not in a
    assert "capacity_gap_bands" not in a


def test_alignment_no_false_positive_at_band_edge():
    # 0.1 puntos por encima del techo, cruzando un borde de banda: antes
    # disparaba over_capacity; ahora queda dentro de la holgura.
    a = align_numbers(client_number=59.9, capacity_ceiling_number=59.9,
                      portfolio_number=60.0)
    assert a["status"] == "aligned"


def test_alignment_catches_within_band_excess():
    # 18.9 puntos por encima del techo DENTRO de la misma banda: antes se
    # reportaba "aligned"; ahora es over_capacity.
    a = align_numbers(client_number=61.0, capacity_ceiling_number=61.0,
                      portfolio_number=79.9)
    assert a["status"] == "over_capacity"
    assert a["capacity_gap_points"] == pytest.approx(18.9)


def test_alignment_over_tolerance_within_capacity():
    a = align_numbers(client_number=40.0, capacity_ceiling_number=90.0,
                      portfolio_number=55.0)
    assert a["status"] == "over_tolerance"
    assert a["gap_points"] == 15.0


def test_alignment_aligned_within_tolerance():
    a = align_numbers(client_number=62.0, capacity_ceiling_number=75.0,
                      portfolio_number=68.0)
    assert a["status"] == "aligned"


def test_alignment_under_tolerance_headroom_capped_by_ceiling():
    a = align_numbers(client_number=70.0, capacity_ceiling_number=75.0,
                      portfolio_number=30.0)
    assert a["status"] == "under_tolerance"
    assert a["gap_points"] == -40.0
    # El margen informado termina en min(cliente, techo) = 70 → 40 puntos.
    assert "40 puntos" in a["explanation"]


def test_alignment_under_tolerance_without_real_headroom():
    # La cartera está apenas bajo el techo: no debe invitar a subir riesgo.
    a = align_numbers(client_number=50.0, capacity_ceiling_number=32.0,
                      portfolio_number=30.0)
    assert a["status"] == "under_tolerance"
    assert "poco margen" in a["explanation"]


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
    # Cliente sin capacidad + cartera volátil → over_capacity (informativo).
    payload = _kyc(
        risk_tolerance_score=10, risk_capacity_score=1, investment_horizon_years=1,
        liquidity_need_score=8, investment_experience="ninguna",
        investment_objective="aggressive_growth")
    out = assess_risk_alignment(payload, mu_annual=0.0, sigma_annual=0.15)
    assert out["alignment"]["status"] == "over_capacity"
    assert out["alignment"]["capacity_gap_points"] > 0


def test_anchor_table_is_sorted():
    xs = [x for x, _ in DOWNSIDE_ANCHORS]
    assert xs == sorted(xs)
