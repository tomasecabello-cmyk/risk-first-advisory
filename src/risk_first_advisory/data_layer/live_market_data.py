"""
LiveMarketDataProvider — MarketDataSnapshot en vivo (ARG + US), mismo contrato que
MockMarketDataProvider (get_snapshot / get_many).

Usa data_layer/providers.fetch_series (data912 / Rava / yfinance) para traer la serie
de cierres, normaliza ARS→USD con usd_ars_history (CCL) cuando el activo cotiza en
pesos, y computa retorno/volatilidad anualizados + liquidez. Así el optimizador del
flujo case-scoped puede correr sobre datos reales en vez del fixture.

Determinista NO: depende de la red. Por eso en el flujo case-scoped es OPT-IN
(env RFA_LIVE_DATA); los tests y el smoke check siguen con el Mock/fixture. El
parámetro `_fetch` permite inyectar un fetcher fake en tests sin tocar internet.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pandas as pd

from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.data_layer.providers import (
    PriceSeries,
    ProviderError,
    fetch_series_cached,
    usd_ars_history,
)

_TRADING_DAYS = 252
_MIN_OBS = 40  # ONs tienen histórico corto; umbral más laxo que yfinance puro

# Vol anualizada máxima "sana" (ver data_layer/estimation.MAX_SANE_VOL). Series
# con vol por encima se asumen corruptas (ratios de CEDEAR sin ajustar, precios
# basura) y NO producen snapshot: mejor sin dato que con un dato que envenena Σ.
_MAX_SANE_VOL = 3.0


def instrument_type_to_source(instrument_type: str, country: str = "") -> str:
    """
    Mapea el instrument_type del universo del proyecto a un `source` de providers.
    US por país; ARG por tipo. Default conservador: us (yfinance).
    """
    t = (instrument_type or "").strip().upper()
    c = (country or "").strip().upper()
    if c in {"US", "USA", "EEUU", ""} and t in {"ETF", "STOCK", "EQUITY"}:
        return "us"
    if t == "CEDEAR":
        return "arg_cedear"
    if t == "SOVEREIGN_BOND":
        return "arg_bond"
    if t == "CORPORATE_BOND":
        return "arg_corp"
    if t in {"STOCK", "EQUITY"}:
        return "arg_stock"
    if t == "ETF":
        return "us"
    return "us"


class LiveMarketDataProvider:
    """
    Proveedor de MarketDataSnapshot en vivo. Mismo contrato que MockMarketDataProvider.

    Args:
        source_map:  dict ticker → source (us / arg_stock / arg_cedear / arg_bond / arg_corp).
        period:      ventana histórica para providers ("1y","3y","5y","max").
        normalize_usd: si True, convierte series ARS a USD con CCL antes de μ/σ.
        _fetch:      fetcher inyectable (ticker, source, period) -> PriceSeries (tests).
        _fx:         proveedor FX inyectable (kind, period) -> pd.Series (tests).
    """

    def __init__(
        self,
        source_map: dict[str, str],
        period: str = "3y",
        normalize_usd: bool = True,
        _fetch: Callable[[str, str, str], PriceSeries] | None = None,
        _fx: Callable[[str, str], pd.Series] | None = None,
    ) -> None:
        self._source_map = {k.strip().upper(): v for k, v in (source_map or {}).items()}
        self._period = period
        self._normalize_usd = normalize_usd
        self._fetch = _fetch or fetch_series_cached  # cache en disco (24h) por defecto
        self._fx = _fx or usd_ars_history

    def contains(self, ticker: str) -> bool:
        return ticker.strip().upper() in self._source_map

    def get_snapshot(self, ticker: str) -> MarketDataSnapshot | None:
        sym = ticker.strip().upper()
        source = self._source_map.get(sym, "us")
        try:
            ps = self._fetch(sym, source, self._period)
        except ProviderError:
            return None
        except Exception:  # noqa: BLE001 — cualquier fallo de red → sin snapshot
            return None
        if ps is None or ps.close is None or len(ps.close) == 0:
            return None

        close = ps.close
        notes = [f"source={source}", f"ccy_native={ps.currency}", f"obs={len(close)}"]

        # Normalización ARS→USD (para que la devaluación no infle retornos AR).
        if self._normalize_usd and ps.currency == "ARS":
            try:
                fx = self._fx("ccl", self._period)
                fx = fx.reindex(close.index.union(fx.index)).sort_index().ffill()
                fx = fx.reindex(close.index)
                close = (close / fx).dropna()
                notes.append("normalized=USD(CCL)")
            except Exception:  # noqa: BLE001 — sin FX, se queda en moneda nativa
                notes.append("normalized=NO(fx_unavailable)")

        daily = close.pct_change().dropna()
        if len(daily) < _MIN_OBS:
            return None

        exp_return = max(-1.0, min(1.0, float(daily.mean()) * _TRADING_DAYS))
        vol = max(0.0, float(daily.std()) * math.sqrt(_TRADING_DAYS))
        if vol > _MAX_SANE_VOL:
            # Serie corrupta: sin snapshot (mismo contrato que un fetch fallido).
            return None
        asset_class = "fixed_income" if ps.kind == "bond" else "equity"
        currency = "USD" if (self._normalize_usd and ps.currency == "ARS") else ps.currency

        return MarketDataSnapshot(
            ticker=sym,
            expected_return_annual=round(exp_return, 6),
            volatility_annual=round(vol, 6),
            liquidity_score=0.7,  # heurística neutra; data912/BYMA live podría refinarla
            expense_ratio=0.0,
            duration=None,
            asset_class=asset_class,
            currency=currency,
            stale=False,
            missing_fields=["expense_ratio"],
            notes=notes,
        )

    def get_many(self, tickers: list[str]) -> list[MarketDataSnapshot]:
        out: list[MarketDataSnapshot] = []
        for t in tickers:
            snap = self.get_snapshot(t)
            if snap is not None:
                out.append(snap)
        return out
