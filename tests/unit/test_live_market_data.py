"""
Tests de LiveMarketDataProvider — offline (fetchers inyectados, sin red).

Verifica el contrato MarketDataSnapshot, la normalización ARS→USD y el manejo de
errores/datos insuficientes. La integración real con data912/yfinance se prueba a
mano (no en CI: depende de la red).
"""

from __future__ import annotations

import pandas as pd
import pytest

from risk_first_advisory.data_layer.live_market_data import (
    LiveMarketDataProvider,
    instrument_type_to_source,
)
from risk_first_advisory.data_layer.providers import PriceSeries, ProviderError


def _series(n: int, start: float = 100.0, step: float = 0.5) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.Series([start + step * i for i in range(n)], index=idx)


def _fetch_us(sym, source, period):
    return PriceSeries(sym, "us", "USD", "equity", _series(120))


def _fetch_ars(sym, source, period):
    return PriceSeries(sym, "arg_stock", "ARS", "equity", _series(120, start=1000.0, step=5.0))


def _fx_flat(kind, period):
    # CCL constante: la normalización no debe romper ni cambiar el signo del retorno.
    idx = pd.date_range("2023-01-01", periods=600, freq="D")
    return pd.Series([1000.0] * len(idx), index=idx)


def test_us_snapshot_has_contract_fields():
    prov = LiveMarketDataProvider({"SPY": "us"}, _fetch=_fetch_us)
    s = prov.get_snapshot("SPY")
    assert s is not None
    assert s.ticker == "SPY"
    assert s.currency == "USD"
    assert s.asset_class == "equity"
    assert -1.0 <= s.expected_return_annual <= 1.0
    assert s.volatility_annual >= 0.0


def test_ars_is_normalized_to_usd():
    prov = LiveMarketDataProvider({"GGAL": "arg_stock"}, _fetch=_fetch_ars, _fx=_fx_flat)
    s = prov.get_snapshot("GGAL")
    assert s is not None
    assert s.currency == "USD"
    assert any("normalized=USD" in n for n in s.notes)


def test_bond_maps_to_fixed_income():
    def _fetch_bond(sym, source, period):
        return PriceSeries(sym, "arg_bond", "ARS", "bond", _series(120, start=50.0, step=0.1))
    prov = LiveMarketDataProvider({"GD30": "arg_bond"}, _fetch=_fetch_bond, _fx=_fx_flat)
    s = prov.get_snapshot("GD30")
    assert s is not None and s.asset_class == "fixed_income"


def test_too_few_observations_returns_none():
    def _short(sym, source, period):
        return PriceSeries(sym, "us", "USD", "equity", _series(10))
    prov = LiveMarketDataProvider({"X": "us"}, _fetch=_short)
    assert prov.get_snapshot("X") is None


def test_provider_error_returns_none():
    def _boom(sym, source, period):
        raise ProviderError("down")
    prov = LiveMarketDataProvider({"X": "us"}, _fetch=_boom)
    assert prov.get_snapshot("X") is None


def test_absurd_volatility_returns_none():
    # Serie corrupta (saltos de ratio estilo CEDEAR): vol anualizada absurda.
    # No debe producir snapshot — un dato así envenena Σ y rompe el optimizador.
    def _corrupt(sym, source, period):
        idx = pd.date_range("2024-01-01", periods=120, freq="D")
        prices = [100.0 * (50.0 if i % 2 else 1.0) for i in range(120)]
        return PriceSeries(sym, "us", "USD", "equity", pd.Series(prices, index=idx))
    prov = LiveMarketDataProvider({"ETHA": "us"}, _fetch=_corrupt)
    assert prov.get_snapshot("ETHA") is None


def test_get_many_skips_failures():
    def _mixed(sym, source, period):
        if sym == "BAD":
            raise ProviderError("no data")
        return PriceSeries(sym, "us", "USD", "equity", _series(120))
    prov = LiveMarketDataProvider({"GOOD": "us", "BAD": "us"}, _fetch=_mixed)
    out = prov.get_many(["GOOD", "BAD"])
    assert [s.ticker for s in out] == ["GOOD"]


def test_fetch_series_cached_hits_disk_cache(tmp_path, monkeypatch):
    # La segunda llamada (mismo symbol/source/period) NO debe re-fetchear: lee disco.
    from risk_first_advisory.data_layer import providers
    calls = {"n": 0}

    def _fake(sym, source, period):
        calls["n"] += 1
        return PriceSeries(sym, source, "USD", "equity", _series(60))

    monkeypatch.setattr(providers, "fetch_series", _fake)
    ps1 = providers.fetch_series_cached("SPY", "us", "1y", cache_dir=tmp_path)
    ps2 = providers.fetch_series_cached("SPY", "us", "1y", cache_dir=tmp_path)
    assert calls["n"] == 1  # la segunda salió del cache
    assert len(ps1.close) == len(ps2.close) == 60


def test_fetch_series_cached_expired_refetches(tmp_path, monkeypatch):
    from risk_first_advisory.data_layer import providers
    calls = {"n": 0}

    def _fake(sym, source, period):
        calls["n"] += 1
        return PriceSeries(sym, source, "USD", "equity", _series(60))

    monkeypatch.setattr(providers, "fetch_series", _fake)
    providers.fetch_series_cached("SPY", "us", "1y", cache_dir=tmp_path, ttl=0)
    providers.fetch_series_cached("SPY", "us", "1y", cache_dir=tmp_path, ttl=0)
    assert calls["n"] == 2  # ttl=0 → siempre re-fetch


@pytest.mark.parametrize("itype,country,expected", [
    ("ETF", "US", "us"),
    ("STOCK", "US", "us"),
    ("CEDEAR", "AR", "arg_cedear"),
    ("SOVEREIGN_BOND", "AR", "arg_bond"),
    ("CORPORATE_BOND", "AR", "arg_corp"),
    ("STOCK", "AR", "arg_stock"),
])
def test_instrument_type_to_source(itype, country, expected):
    assert instrument_type_to_source(itype, country) == expected
