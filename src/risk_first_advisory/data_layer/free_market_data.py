"""
FreeMarketDataProvider — descarga datos históricos de yfinance y los convierte
al contrato MarketDataSnapshot que usa el pipeline cuantitativo.

Diseñado para prototipo local. NO usar en producción sin revisar:
    - Rate limits de Yahoo Finance.
    - Calidad y frescura de los datos.
    - Ausencia de SLA.

Contratos respetados:
    - get_snapshot(ticker) -> MarketDataSnapshot | None
    - get_many(tickers)    -> list[MarketDataSnapshot]
    (Mismo contrato que MockMarketDataProvider.)

Extensibilidad:
    El parámetro _downloader permite inyectar una función de descarga
    alternativa en tests, sin llamar a internet.
    Firma: (ticker: str, period: str, interval: str) -> pd.DataFrame | None
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pandas as pd

from risk_first_advisory.data_layer.market_data import MarketDataSnapshot

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MIN_OBSERVATIONS: int = 60          # mínimo de retornos diarios requeridos
_TRADING_DAYS_PER_YEAR: int = 252

# Umbrales de volumen para heurística de liquidez
_VOL_HIGH: float = 10_000_000.0      # → liquidity_score = 0.9
_VOL_MED: float = 1_000_000.0       # → liquidity_score = 0.7
_VOL_LOW: float = 0.0               # → liquidity_score = 0.5
_LIQUIDITY_DEFAULT: float = 0.8     # cuando no hay datos de volumen


# ---------------------------------------------------------------------------
# FreeMarketDataProvider
# ---------------------------------------------------------------------------


class FreeMarketDataProvider:
    """
    Proveedor de MarketDataSnapshot basado en datos históricos de yfinance.

    Args:
        tickers:          Lista de tickers a cubrir.
        asset_class_map:  Mapa ticker → asset_class (ej. "equity", "bond").
        currency_map:     Mapa ticker → moneda (ej. "USD").
        lookback_period:  Período histórico para yfinance (ej. "3y", "2y", "1y").
        interval:         Frecuencia de datos (ej. "1d", "1wk").
        _downloader:      Función de descarga inyectable para tests.
                          Si None, se usa yfinance.download.

    Contrato de _downloader:
        (ticker: str, period: str, interval: str) -> pd.DataFrame | None
        Debe devolver un DataFrame con columna "Close" (o "Adj Close")
        indexado por fecha, o None / DataFrame vacío si no hay datos.
    """

    def __init__(
        self,
        tickers: list[str],
        asset_class_map: dict[str, str],
        currency_map: dict[str, str],
        lookback_period: str = "3y",
        interval: str = "1d",
        _downloader: Callable[[str, str, str], pd.DataFrame | None] | None = None,
    ) -> None:
        self._tickers: list[str] = list(tickers)
        self._asset_class_map: dict[str, str] = dict(asset_class_map)
        self._currency_map: dict[str, str] = dict(currency_map)
        self._lookback_period: str = lookback_period
        self._interval: str = interval
        self._downloader = _downloader
        # Cache de resultados: evita descargas repetidas en la misma sesión.
        self._cache: dict[str, MarketDataSnapshot | None] = {}

    # ── descarga interna ──────────────────────────────────────────────────────

    def _download(self, ticker: str) -> pd.DataFrame | None:
        """Descarga precios para un ticker. Usa _downloader inyectado si existe."""
        if self._downloader is not None:
            return self._downloader(ticker, self._lookback_period, self._interval)
        import yfinance as yf  # import diferido: no requerido si solo se usan mocks
        df = yf.download(
            ticker,
            period=self._lookback_period,
            interval=self._interval,
            progress=False,
            auto_adjust=True,
        )
        return df if not df.empty else None

    # ── extracción de serie de cierre ─────────────────────────────────────────

    @staticmethod
    def _extract_close(df: pd.DataFrame, ticker: str) -> pd.Series | None:
        """
        Extrae la serie de precios de cierre del DataFrame de yfinance.

        Maneja tanto columnas simples como MultiIndex (yfinance >= 0.2 puede
        devolver cualquiera de los dos formatos según la versión).
        """
        cols = df.columns

        # MultiIndex: (field, ticker) — ej. ("Close", "SPY")
        if isinstance(cols, pd.MultiIndex):
            for field_name in ("Close", "Adj Close"):
                if field_name in cols.get_level_values(0):
                    level = df[field_name]
                    if ticker in level.columns:
                        return level[ticker].dropna()
                    # Un solo ticker → primera columna
                    return level.iloc[:, 0].dropna()
            return None

        # Columnas simples
        for field_name in ("Close", "Adj Close"):
            if field_name in cols:
                return df[field_name].dropna()

        return None

    # ── cálculo de snapshot ───────────────────────────────────────────────────

    def _compute_snapshot(self, ticker: str) -> MarketDataSnapshot | None:
        """
        Descarga precios y construye un MarketDataSnapshot.
        Devuelve None si los datos son insuficientes o inválidos.
        """
        df = self._download(ticker)
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            return None

        close = self._extract_close(df, ticker)
        if close is None or len(close) == 0:
            return None

        daily_returns = close.pct_change().dropna()
        if len(daily_returns) < _MIN_OBSERVATIONS:
            return None

        # Estadísticas anualizadas
        mean_daily = float(daily_returns.mean())
        std_daily = float(daily_returns.std())

        expected_return = mean_daily * _TRADING_DAYS_PER_YEAR
        volatility = std_daily * math.sqrt(_TRADING_DAYS_PER_YEAR)

        # Clamp expected_return al rango aceptado por MarketDataSnapshot
        expected_return = max(-1.0, min(1.0, expected_return))

        # volatility no puede ser negativo (por construcción std >= 0, pero defensivo)
        volatility = max(0.0, volatility)

        liquidity = self._compute_liquidity(ticker, df)
        asset_class = self._asset_class_map.get(ticker, "equity")
        currency = self._currency_map.get(ticker, "USD")

        return MarketDataSnapshot(
            ticker=ticker,
            expected_return_annual=round(expected_return, 6),
            volatility_annual=round(volatility, 6),
            liquidity_score=liquidity,
            expense_ratio=0.0,   # yfinance no expone expense_ratio de forma fiable
            duration=None,       # solo relevante para renta fija; no disponible en yfinance
            asset_class=asset_class,
            currency=currency,
            stale=False,
            missing_fields=["expense_ratio"],  # marcado como faltante para DataQualityGate
            notes=[
                "source=yfinance",
                f"period={self._lookback_period}",
                f"interval={self._interval}",
                f"observations={len(daily_returns)}",
            ],
        )

    # ── heurística de liquidez ────────────────────────────────────────────────

    @staticmethod
    def _compute_liquidity(ticker: str, df: pd.DataFrame) -> float:
        """
        Estima liquidity_score en [0.0, 1.0] a partir del volumen promedio.

        Si no hay datos de volumen, devuelve _LIQUIDITY_DEFAULT (0.8),
        razonable para ETFs cotizados en mercados organizados.
        """
        # Intentar extraer columna Volume
        vol_series: pd.Series | None = None
        cols = df.columns

        if isinstance(cols, pd.MultiIndex):
            if "Volume" in cols.get_level_values(0):
                vol_block = df["Volume"]
                vol_series = (
                    vol_block[ticker]
                    if ticker in vol_block.columns
                    else vol_block.iloc[:, 0]
                )
        elif "Volume" in cols:
            vol_series = df["Volume"]

        if vol_series is None or vol_series.empty:
            return _LIQUIDITY_DEFAULT

        avg_volume = float(vol_series.mean())
        if avg_volume >= _VOL_HIGH:
            return 0.9
        if avg_volume >= _VOL_MED:
            return 0.7
        if avg_volume > _VOL_LOW:
            return 0.5
        return _LIQUIDITY_DEFAULT

    # ── interfaz pública ──────────────────────────────────────────────────────

    def get_snapshot(self, ticker: str) -> MarketDataSnapshot | None:
        """
        Devuelve el MarketDataSnapshot para un ticker, usando caché interno.
        Devuelve None si los datos son insuficientes o el ticker no existe.
        """
        if ticker not in self._cache:
            self._cache[ticker] = self._compute_snapshot(ticker)
        return self._cache[ticker]

    def get_many(self, tickers: list[str]) -> list[MarketDataSnapshot]:
        """
        Devuelve snapshots válidos para la lista de tickers, en el orden pedido.
        Tickers sin datos suficientes se OMITEN (no se devuelve None).
        """
        result: list[MarketDataSnapshot] = []
        for t in tickers:
            snap = self.get_snapshot(t)
            if snap is not None:
                result.append(snap)
        return result

    def contains(self, ticker: str) -> bool:
        """True si el ticker está en la lista configurada."""
        return ticker in self._tickers

    def __len__(self) -> int:
        return len(self._tickers)
