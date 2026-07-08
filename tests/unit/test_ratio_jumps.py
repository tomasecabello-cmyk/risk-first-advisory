"""
Tests de providers.adjust_ratio_jumps — corrección de saltos de ratio de
CEDEARs (DD-014, segunda parte) — y su integración con el estimador conjunto
y LiveMarketDataProvider. Offline, series sintéticas con seed fija.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from risk_first_advisory.data_layer.estimation import estimate_joint_moments
from risk_first_advisory.data_layer.live_market_data import LiveMarketDataProvider
from risk_first_advisory.data_layer.providers import (
    PriceSeries,
    adjust_ratio_jumps,
)

_TRADING_DAYS = 252


def _walk(n: int, vol: float = 0.02, drift: float = 0.0004,
          start: float = 100.0, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, size=n)
    prices = start * np.cumprod(1.0 + rets)
    return pd.Series(prices, index=pd.bdate_range("2023-01-02", periods=n))


def _with_jump(base: pd.Series, at: int, factor: float) -> pd.Series:
    """Simula un rebasing: desde la posición `at` los precios quedan × factor."""
    values = base.to_numpy(dtype=float).copy()
    values[at:] *= factor
    return pd.Series(values, index=base.index)


def _annual_vol(close: pd.Series) -> float:
    return float(close.pct_change().dropna().std()) * float(np.sqrt(_TRADING_DAYS))


# ─────────────────────────────────────────────────────────────────────────────
# Función pura
# ─────────────────────────────────────────────────────────────────────────────


def test_clean_series_untouched():
    s = _walk(400, seed=5)
    adj = adjust_ratio_jumps(s)
    assert adj.n_jumps == 0 and not adj.suspect and adj.notes == []
    pd.testing.assert_series_equal(adj.close, s)


def test_isolated_down_jump_adjusted_and_vol_restored():
    base = _walk(400, seed=7)
    jumped = _with_jump(base, at=200, factor=1 / 2.2)  # ratio 1:2.2 → −55% aislado
    assert _annual_vol(jumped) > 1.5 * _annual_vol(base)  # el salto infla σ

    adj = adjust_ratio_jumps(jumped)
    assert adj.n_jumps == 1 and not adj.suspect
    assert len(adj.notes) == 1 and "ratio_jump_adjusted" in adj.notes[0]
    # σ vuelve al rango de la serie limpia (el día del salto queda en r=0).
    assert _annual_vol(adj.close) < 1.1 * _annual_vol(base)
    # Los retornos fuera del salto no cambian.
    r_orig = jumped.pct_change().dropna().to_numpy()
    r_adj = adj.close.pct_change().dropna().to_numpy()
    mask = np.ones(len(r_orig), dtype=bool)
    mask[199] = False  # el retorno del salto (posición 200 de la serie)
    assert np.allclose(r_orig[mask], r_adj[mask])
    assert abs(r_adj[199]) < 1e-9


def test_isolated_up_jump_adjusted():
    jumped = _with_jump(_walk(400, seed=9), at=120, factor=3.0)  # +200% aislado
    adj = adjust_ratio_jumps(jumped)
    assert adj.n_jumps == 1 and not adj.suspect
    assert _annual_vol(adj.close) < 0.5


def test_genuine_crash_with_rebound_untouched():
    # −45% seguido de +40%: días grandes CONTIGUOS = crash real, no ratio.
    base = _walk(400, seed=11)
    values = base.to_numpy(dtype=float).copy()
    values[200] *= 0.55
    values[201:] *= 0.55 * 1.40 / 0.55  # el resto sigue desde el rebote
    crashed = pd.Series(values, index=base.index)
    adj = adjust_ratio_jumps(crashed)
    assert adj.n_jumps == 0 and not adj.suspect
    pd.testing.assert_series_equal(adj.close, crashed)


def test_too_many_jumps_marks_suspect_without_adjusting():
    base = _walk(400, seed=13)
    s = base
    for at in (50, 100, 150, 200, 250, 350):  # 6 saltos aislados > max_jumps=5
        s = _with_jump(s, at=at, factor=0.5 if at % 100 else 2.0)
    adj = adjust_ratio_jumps(s)
    assert adj.suspect and adj.n_jumps == 6
    assert any("ratio_jumps_excessive" in n for n in adj.notes)
    pd.testing.assert_series_equal(adj.close, s)  # no se toca


def test_jump_at_last_observation_adjusts_prefix():
    base = _walk(300, seed=17)
    jumped = _with_jump(base, at=299, factor=0.4)
    adj = adjust_ratio_jumps(jumped)
    assert adj.n_jumps == 1
    assert _annual_vol(adj.close) < 0.5


def test_short_series_passthrough():
    s = pd.Series([100.0, 101.0], index=pd.bdate_range("2024-01-01", periods=2))
    adj = adjust_ratio_jumps(s)
    assert adj.n_jumps == 0 and not adj.suspect


# ─────────────────────────────────────────────────────────────────────────────
# Integración: estimador conjunto
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_factory(series: dict[str, pd.Series]):
    def _fetch(sym: str, source: str, period: str) -> PriceSeries:
        return PriceSeries(symbol=sym, source=source, currency="USD",
                           kind="equity", close=series[sym])
    return _fetch


def _fx_flat(kind: str, period: str) -> pd.Series:
    return pd.Series(1000.0, index=pd.bdate_range("2022-01-03", periods=900))


def test_joint_moments_keeps_and_adjusts_jumped_series():
    """Una serie tipo IBM/NFLX (salto de ratio bajo el sanity bound) debe
    quedar EN la estimación con σ razonable y nota auditada en `adjusted`,
    en vez de inflar σ silenciosamente."""
    clean_a = _walk(500, seed=21)
    clean_b = _walk(500, seed=22)
    jumped = _with_jump(_walk(500, vol=0.018, seed=23), at=250, factor=1 / 2.5)
    # σ inflada pero bajo MAX_SANE_VOL: el sanity bound NO la ataja.
    assert 0.45 < _annual_vol(jumped) < 3.0

    est = estimate_joint_moments(
        {"AAA": "us", "BBB": "us", "JMP": "us"},
        _fetch=_fetch_factory({"AAA": clean_a, "BBB": clean_b, "JMP": jumped}),
        _fx=_fx_flat,
    )
    assert "JMP" in est.tickers
    assert est.vol["JMP"] < 0.4  # σ de equity normal, sin el salto
    adj_tickers = {a["ticker"] for a in est.adjusted}
    assert adj_tickers == {"JMP"}
    assert all("ratio_jump_adjusted" in a["note"] for a in est.adjusted)


def test_joint_moments_drops_suspect_series():
    clean_a = _walk(500, seed=31)
    clean_b = _walk(500, seed=32)
    trash = _walk(500, seed=33)
    for at in (50, 100, 150, 200, 250, 350):
        trash = _with_jump(trash, at=at, factor=0.5 if at % 100 else 2.0)

    est = estimate_joint_moments(
        {"AAA": "us", "BBB": "us", "TRASH": "us"},
        _fetch=_fetch_factory({"AAA": clean_a, "BBB": clean_b, "TRASH": trash}),
        _fx=_fx_flat,
    )
    assert "TRASH" not in est.tickers
    reasons = {d["ticker"]: d["reason"] for d in est.dropped}
    assert "ratio_jumps_excessive" in reasons["TRASH"]


# ─────────────────────────────────────────────────────────────────────────────
# Integración: LiveMarketDataProvider
# ─────────────────────────────────────────────────────────────────────────────


def test_live_provider_snapshot_adjusts_jump_and_notes_it():
    jumped = _with_jump(_walk(300, vol=0.018, seed=41), at=150, factor=1 / 2.5)

    def _fetch(sym, source, period):
        return PriceSeries(sym, "us", "USD", "equity", jumped)

    prov = LiveMarketDataProvider({"JMP": "us"}, _fetch=_fetch)
    snap = prov.get_snapshot("JMP")
    assert snap is not None
    assert snap.volatility_annual < 0.6
    assert any("ratio_jump_adjusted" in n for n in snap.notes)


def test_live_provider_suspect_series_returns_none():
    trash = _walk(300, seed=43)
    for at in (40, 80, 120, 160, 200, 280):
        trash = _with_jump(trash, at=at, factor=0.5 if at % 80 else 2.0)

    def _fetch(sym, source, period):
        return PriceSeries(sym, "us", "USD", "equity", trash)

    prov = LiveMarketDataProvider({"TRASH": "us"}, _fetch=_fetch)
    assert prov.get_snapshot("TRASH") is None
