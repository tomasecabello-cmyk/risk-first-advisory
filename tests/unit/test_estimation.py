"""
Tests de data_layer/estimation — Ledoit-Wolf + Black-Litterman + estimador
conjunto. Offline (fetchers/FX inyectados, sin red), series sintéticas con
seed fija.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from risk_first_advisory.data_layer.estimation import (
    EstimationError,
    black_litterman_returns,
    estimate_joint_moments,
    implied_equilibrium_returns,
    ledoit_wolf_covariance,
)
from risk_first_advisory.data_layer.providers import PriceSeries, ProviderError

_RNG = np.random.default_rng(7)
_TRADING_DAYS = 252


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: series sintéticas
# ─────────────────────────────────────────────────────────────────────────────


def _random_walk(n: int, drift: float = 0.0005, vol: float = 0.02,
                 start: float = 100.0, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, size=n)
    prices = start * np.cumprod(1.0 + rets)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.Series(prices, index=idx)


def _fetch_factory(specs: dict[str, dict]) -> callable:
    """specs: ticker → kwargs de _random_walk + currency/kind opcionales."""
    def _fetch(sym: str, source: str, period: str) -> PriceSeries:
        spec = specs.get(sym)
        if spec is None:
            raise ProviderError(f"sin datos para {sym}")
        kw = {k: v for k, v in spec.items() if k not in ("currency", "kind")}
        return PriceSeries(
            symbol=sym, source=source,
            currency=spec.get("currency", "USD"),
            kind=spec.get("kind", "equity"),
            close=_random_walk(**kw),
        )
    return _fetch


def _fx_flat(kind: str, period: str) -> pd.Series:
    idx = pd.bdate_range("2022-01-03", periods=900)
    return pd.Series(1000.0, index=idx)


# ─────────────────────────────────────────────────────────────────────────────
# Ledoit-Wolf
# ─────────────────────────────────────────────────────────────────────────────


def test_lw_shrinkage_in_unit_interval_and_symmetric_pd():
    x = _RNG.normal(0.0, 0.02, size=(120, 6))
    sigma, lam = ledoit_wolf_covariance(x)
    assert 0.0 <= lam <= 1.0
    assert np.allclose(sigma, sigma.T)
    eigvals = np.linalg.eigvalsh(sigma)
    assert eigvals.min() > 0.0  # bien condicionada: el shrinkage garantiza PD


def test_lw_shrinks_offdiagonal_toward_zero_vs_sample():
    # Con pocas observaciones y muchas dimensiones el shrinkage debe ser fuerte
    # y los términos fuera de la diagonal deben achicarse respecto a la muestral.
    x = _RNG.normal(0.0, 0.02, size=(50, 20))
    sigma, lam = ledoit_wolf_covariance(x)
    xc = x - x.mean(axis=0)
    sample = (xc.T @ xc) / x.shape[0]
    off = ~np.eye(20, dtype=bool)
    assert lam > 0.1
    assert np.abs(sigma[off]).sum() < np.abs(sample[off]).sum()


def test_lw_lambda_decreases_with_more_observations():
    # Con Σ verdadera ≠ m·I (vols heterogéneas + factor común), más datos deben
    # implicar menos shrinkage hacia el target. (Con ruido iid de varianzas
    # iguales λ→1 en ambos casos porque el target ES la verdad — degenerado.)
    rng = np.random.default_rng(3)
    vols = np.linspace(0.01, 0.05, 8)

    def _draw(t: int) -> np.ndarray:
        factor = rng.normal(0.0, 0.02, size=(t, 1))
        idio = rng.normal(0.0, 1.0, size=(t, 8)) * vols
        return factor + idio

    _, lam_short = ledoit_wolf_covariance(_draw(60))
    _, lam_long = ledoit_wolf_covariance(_draw(2000))
    assert lam_long < lam_short  # más datos → menos shrinkage


def test_lw_rejects_bad_shapes():
    with pytest.raises(ValueError):
        ledoit_wolf_covariance(np.zeros(5))
    with pytest.raises(ValueError):
        ledoit_wolf_covariance(np.zeros((1, 3)))


# ─────────────────────────────────────────────────────────────────────────────
# Black-Litterman
# ─────────────────────────────────────────────────────────────────────────────


def _toy_sigma() -> np.ndarray:
    vols = np.array([0.10, 0.20, 0.30])
    corr = np.array([[1.0, 0.3, 0.2], [0.3, 1.0, 0.5], [0.2, 0.5, 1.0]])
    return corr * np.outer(vols, vols)


def test_bl_posterior_between_equilibrium_and_history():
    sigma = _toy_sigma()
    mu_hist = np.array([0.40, 0.35, 0.50])  # medias infladas estilo post-rally
    rf = 0.04
    pi = implied_equilibrium_returns(sigma, np.full(3, 1 / 3)) + rf
    mu_bl = black_litterman_returns(sigma, mu_hist, rf=rf)
    for i in range(3):
        lo, hi = sorted((pi[i], mu_hist[i]))
        assert lo - 1e-9 <= mu_bl[i] <= hi + 1e-9
        # y estrictamente MÁS CERCA del equilibrio que la media histórica cruda
        assert abs(mu_bl[i] - pi[i]) < abs(mu_hist[i] - pi[i])


def test_bl_high_confidence_converges_to_history():
    sigma = _toy_sigma()
    mu_hist = np.array([0.12, 0.08, 0.15])
    mu_bl = black_litterman_returns(sigma, mu_hist, rf=0.04, view_confidence=1e9)
    assert np.allclose(mu_bl, mu_hist, atol=1e-4)


def test_bl_low_confidence_converges_to_equilibrium():
    sigma = _toy_sigma()
    mu_hist = np.array([0.12, 0.08, 0.15])
    rf = 0.04
    pi = implied_equilibrium_returns(sigma, np.full(3, 1 / 3)) + rf
    mu_bl = black_litterman_returns(sigma, mu_hist, rf=rf, view_confidence=1e-9)
    assert np.allclose(mu_bl, pi, atol=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# Estimador conjunto
# ─────────────────────────────────────────────────────────────────────────────


def _base_specs() -> dict[str, dict]:
    return {
        "SPY":  {"n": 500, "drift": 0.0004, "vol": 0.010, "seed": 11},
        "GGAL": {"n": 500, "drift": 0.0008, "vol": 0.030, "seed": 22,
                 "currency": "ARS"},
        "GD30": {"n": 500, "drift": 0.0006, "vol": 0.015, "seed": 33,
                 "currency": "ARS", "kind": "bond"},
    }


def _sources() -> dict[str, str]:
    return {"SPY": "us", "GGAL": "arg_stock", "GD30": "arg_bond"}


def test_joint_moments_contract_and_alignment():
    est = estimate_joint_moments(
        _sources(), _fetch=_fetch_factory(_base_specs()), _fx=_fx_flat)
    assert sorted(est.tickers) == ["GD30", "GGAL", "SPY"]
    # Alineación estricta: covariance.tickers == tickers, μ/σ indexados igual.
    assert est.covariance.tickers == est.tickers
    assert set(est.mu) == set(est.vol) == set(est.tickers)
    assert 0.0 <= est.shrinkage <= 1.0
    for t in est.tickers:
        assert -1.0 <= est.mu[t] <= 1.0
        assert est.vol[t] >= 0.0
        # σ es la diagonal de Σ
        assert est.vol[t] == pytest.approx(
            est.covariance.get_covariance(t, t) ** 0.5, rel=1e-9)
    # Correlación con diagonal exactamente 1.0 (contrato CovarianceMatrix).
    for i in range(len(est.tickers)):
        assert est.covariance.correlation[i][i] == 1.0


def test_joint_moments_mu_is_shrunk_toward_equilibrium():
    est = estimate_joint_moments(
        _sources(), _fetch=_fetch_factory(_base_specs()), _fx=_fx_flat)
    # GGAL tiene drift alto (≈22% anual de media histórica): BL debe moderarlo.
    assert est.mu_hist["GGAL"] > 0.15
    assert est.mu["GGAL"] < est.mu_hist["GGAL"]


def test_joint_moments_drops_absurd_volatility_series():
    specs = _base_specs()
    specs["ETHA"] = {"n": 500, "drift": 0.0, "vol": 0.60, "seed": 44}  # ~950% anual
    sources = {**_sources(), "ETHA": "arg_cedear"}
    # ETHA cotiza en USD acá para aislar el sanity bound del path FX.
    est = estimate_joint_moments(
        sources, _fetch=_fetch_factory(specs), _fx=_fx_flat)
    assert "ETHA" not in est.tickers
    reasons = {d["ticker"]: d["reason"] for d in est.dropped}
    assert "ETHA" in reasons and "volatility_absurd" in reasons["ETHA"]


def test_joint_moments_drops_failed_and_short_series_with_reasons():
    specs = _base_specs()
    specs["SHORTY"] = {"n": 10, "seed": 55}
    sources = {**_sources(), "SHORTY": "us", "BOOM": "us"}
    est = estimate_joint_moments(
        sources, _fetch=_fetch_factory(specs), _fx=_fx_flat)
    reasons = {d["ticker"]: d["reason"] for d in est.dropped}
    assert "short_history" in reasons["SHORTY"]
    assert "provider_error" in reasons["BOOM"]
    assert sorted(est.tickers) == ["GD30", "GGAL", "SPY"]


def test_joint_moments_ars_without_fx_is_dropped():
    def _fx_boom(kind: str, period: str) -> pd.Series:
        raise ProviderError("FX caído")
    est = estimate_joint_moments(
        {**_sources(), "IVV": "us"},
        _fetch=_fetch_factory({**_base_specs(),
                               "IVV": {"n": 500, "vol": 0.012, "seed": 66}}),
        _fx=_fx_boom)
    assert sorted(est.tickers) == ["IVV", "SPY"]
    reasons = {d["ticker"]: d["reason"] for d in est.dropped}
    assert reasons["GGAL"] == "ars_without_fx"
    assert reasons["GD30"] == "ars_without_fx"


def test_joint_moments_explicit_view_pulls_mu_toward_view():
    """Con una view explícita (p.ej. YTM de un bono), la view de BL para ese
    ticker deja de ser la media histórica: μ posterior queda MÁS CERCA de la
    view que en la corrida base, y el resto no usa view explícita."""
    base = estimate_joint_moments(
        _sources(), _fetch=_fetch_factory(_base_specs()), _fx=_fx_flat)
    ytm = 0.09
    est = estimate_joint_moments(
        _sources(), views={"GD30": ytm},
        _fetch=_fetch_factory(_base_specs()), _fx=_fx_flat)
    assert abs(est.mu["GD30"] - ytm) < abs(base.mu["GD30"] - ytm)
    assert est.meta["GD30"]["view"] == "explicit"
    assert est.meta["SPY"]["view"] == "hist_mean"
    # μ del resto casi no cambia (P=I: cada view es por-ticker; el efecto
    # cruzado entra solo vía Σ y debe ser de segundo orden).
    assert est.mu["SPY"] == pytest.approx(base.mu["SPY"], abs=0.02)
    # mu_hist sigue siendo la media histórica (trazabilidad intacta).
    assert est.mu_hist["GD30"] == pytest.approx(base.mu_hist["GD30"])
    assert any("views=explicit" in n for n in est.notes)


def test_joint_moments_view_for_unknown_ticker_is_ignored():
    est = estimate_joint_moments(
        _sources(), views={"NOPE": 0.10, "GD30": None},  # type: ignore[dict-item]
        _fetch=_fetch_factory(_base_specs()), _fx=_fx_flat)
    assert sorted(est.tickers) == ["GD30", "GGAL", "SPY"]
    assert all(est.meta[t]["view"] == "hist_mean" for t in est.tickers)
    assert not any("views=explicit" in n for n in est.notes)


def test_joint_moments_raises_when_less_than_two_series():
    with pytest.raises(EstimationError):
        estimate_joint_moments(
            {"SPY": "us", "BOOM": "us"},
            _fetch=_fetch_factory({"SPY": {"n": 500, "seed": 11}}),
            _fx=_fx_flat)


def test_joint_moments_optimizer_roundtrip():
    """La salida se enchufa tal cual al PortfolioOptimizer (orden incluido)."""
    from risk_first_advisory.data_layer.return_estimator import ReturnEstimate
    from risk_first_advisory.models.risk_budget import RiskBudget
    from risk_first_advisory.portfolio_layer.optimizer import (
        OptimizationInput,
        OptimizationObjective,
        PortfolioOptimizer,
    )

    est = estimate_joint_moments(
        _sources(), _fetch=_fetch_factory(_base_specs()), _fx=_fx_flat)
    estimates = [
        ReturnEstimate(
            ticker=t, raw_expected_return_annual=est.mu[t], expense_ratio=0.0,
            esg_adjustment=0.0, data_quality_adjustment=0.0,
            adjusted_expected_return_annual=est.mu[t], reason_codes=[], notes=[],
        )
        for t in est.tickers
    ]
    rb = RiskBudget(
        profile_name="test", target_volatility=0.30, max_volatility=0.60,
        max_drawdown=-0.9, min_liquidity=0.0, max_equity=1.0, max_high_yield=1.0,
        max_single_asset=0.60, max_sector_exposure=1.0, max_duration=99.0,
        complex_products_allowed=True, preferred_currency="USD",
    )
    result = PortfolioOptimizer().optimize(OptimizationInput(
        return_estimates=estimates, covariance_matrix=est.covariance,
        risk_budget=rb, objective=OptimizationObjective.MIN_VARIANCE,
    ))
    assert result.constraints_satisfied
    assert abs(sum(result.weights.values()) - 1.0) < 1e-4
