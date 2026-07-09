"""
Tests de providers.fetch_series — cadena de fallbacks para CEDEARs/acciones ARG
(data912 → yfinance .BA → US proxy), offline vía monkeypatch.

Motivación (2026-07-08): VIST/XLB no tienen histórico en data912 y yfinance
.BA devolvía 1 obs (solo hoy), que se aceptaba y quedaba cacheada 24h — la
serie degenerada terminaba excluida de la estimación con `short_history`.
Ahora el fallback .BA exige >= 30 obs y los CEDEARs tienen un último recurso:
el subyacente US en yfinance como proxy auditado (source=arg_cedear>us_proxy).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from risk_first_advisory.data_layer import providers
from risk_first_advisory.data_layer.providers import ProviderError, fetch_series


def _series(n: int, start: float = 100.0, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    prices = start * np.cumprod(1.0 + rng.normal(0.0005, 0.02, size=n))
    return pd.Series(prices, index=pd.bdate_range("2024-01-02", periods=n))


def _install(monkeypatch: pytest.MonkeyPatch, *, d912, yf) -> None:
    """d912/yf: callables o excepciones a lanzar."""
    def _d912(symbol: str, category: str, period: str) -> pd.Series:
        if isinstance(d912, Exception):
            raise d912
        return d912(symbol)

    def _yf(symbol: str, period: str) -> pd.Series:
        if isinstance(yf, Exception):
            raise yf
        return yf(symbol)

    monkeypatch.setattr(providers, "data912_history", _d912)
    monkeypatch.setattr(providers, "yfinance_history", _yf)


def test_d912_ok_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, d912=lambda s: _series(200),
             yf=ProviderError("no debería llamarse"))
    ps = fetch_series("GGAL", "arg_cedear", "3y")
    assert ps.source == "arg_cedear" and ps.currency == "ARS"
    assert len(ps.close) == 200


def test_ba_fallback_when_d912_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, d912=ProviderError("sin histórico"),
             yf=lambda s: _series(150))
    ps = fetch_series("KO", "arg_cedear", "3y")
    assert ps.source == "arg_cedear" and ps.currency == "ARS"
    assert len(ps.close) == 150


def test_degenerate_ba_falls_through_to_us_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso VIST/XLB: d912 sin histórico, .BA con 1 obs → proxy US."""
    def _yf(symbol: str) -> pd.Series:
        if symbol.endswith(".BA"):
            return _series(1)          # yfinance "tiene" el .BA pero sin barras
        return _series(500)            # subyacente US con historia completa

    _install(monkeypatch, d912=ProviderError("sin histórico"), yf=_yf)
    ps = fetch_series("VIST", "arg_cedear", "3y")
    assert ps.source == "arg_cedear>us_proxy"
    assert ps.currency == "USD"        # proxy: ya en USD, sin conversión CCL
    assert len(ps.close) == 500


def test_all_paths_short_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, d912=ProviderError("sin histórico"),
             yf=lambda s: _series(1))
    with pytest.raises(ProviderError):
        fetch_series("VIST", "arg_cedear", "3y")


def test_arg_stock_has_no_us_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """El proxy US es SOLO para CEDEARs: una acción ARG no cotiza en US."""
    calls: list[str] = []

    def _yf(symbol: str) -> pd.Series:
        calls.append(symbol)
        return _series(1)

    _install(monkeypatch, d912=ProviderError("sin histórico"), yf=_yf)
    with pytest.raises(ProviderError):
        fetch_series("GGAL", "arg_stock", "3y")
    assert calls == ["GGAL.BA"]        # nunca intenta "GGAL" a secas
