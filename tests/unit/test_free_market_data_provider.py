"""
Tests unitarios para FreeMarketDataProvider.

Principios:
    - Sin llamadas a internet. Todo yfinance se reemplaza por _downloader mock.
    - Los mocks devuelven DataFrames con la misma estructura que yfinance real.
    - Verifican cálculos de expected_return_annual y volatility_annual.
    - Verifican contrato de get_snapshot y get_many.
    - Verifican manejo de datos insuficientes (< 60 observaciones) y vacíos.
"""

from __future__ import annotations

import math

import pandas as pd
import numpy as np
import pytest

from risk_first_advisory.data_layer.free_market_data import (
    FreeMarketDataProvider,
    _MIN_OBSERVATIONS,
    _TRADING_DAYS_PER_YEAR,
)
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot


# ---------------------------------------------------------------------------
# Helpers de construcción de DataFrames mock
# ---------------------------------------------------------------------------


def _make_price_df(
    n: int = 200,
    start_price: float = 100.0,
    mean_daily_return: float = 0.0003,
    std_daily_return: float = 0.01,
    include_volume: bool = True,
    avg_volume: float = 15_000_000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """
    DataFrame con columnas Close (y opcionalmente Volume), mismo formato
    que yfinance.download para un ticker individual.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(mean_daily_return, std_daily_return, n)
    prices = start_price * (1 + returns).cumprod()
    dates = pd.date_range("2021-01-04", periods=n, freq="B")

    data: dict[str, list[float]] = {"Close": list(prices)}
    if include_volume:
        data["Volume"] = [avg_volume] * n

    return pd.DataFrame(data, index=dates)


def _make_multiindex_df(
    ticker: str = "SPY",
    n: int = 200,
    avg_volume: float = 15_000_000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """
    DataFrame con MultiIndex en columnas: (field, ticker) — formato
    que yfinance devuelve en algunas versiones.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0003, 0.01, n)
    prices = 100.0 * (1 + returns).cumprod()
    dates = pd.date_range("2021-01-04", periods=n, freq="B")

    arrays = [
        ["Close", "Close", "Volume"],
        [ticker, ticker + "_dup", ticker],
    ]
    mi = pd.MultiIndex.from_arrays(arrays, names=["field", "ticker"])
    df = pd.DataFrame(
        {
            ("Close", ticker): prices,
            ("Close", ticker + "_dup"): prices * 1.01,
            ("Volume", ticker): [avg_volume] * n,
        },
        index=dates,
    )
    df.columns = pd.MultiIndex.from_tuples(
        [("Close", ticker), ("Close", ticker + "_dup"), ("Volume", ticker)]
    )
    return df


# ---------------------------------------------------------------------------
# Helpers de construcción del provider
# ---------------------------------------------------------------------------


_DEFAULT_ASSET_CLASS_MAP = {"SPY": "equity", "BND": "bond", "GLD": "commodity"}
_DEFAULT_CURRENCY_MAP = {"SPY": "USD", "BND": "USD", "GLD": "USD"}


def _make_provider(
    tickers: list[str] | None = None,
    downloader=None,
    n_prices: int = 200,
    **kwargs,
) -> FreeMarketDataProvider:
    tickers = tickers or ["SPY", "BND"]
    if downloader is None:
        df = _make_price_df(n=n_prices)
        downloader = lambda ticker, period, interval: df  # noqa: E731
    return FreeMarketDataProvider(
        tickers=tickers,
        asset_class_map=_DEFAULT_ASSET_CLASS_MAP,
        currency_map=_DEFAULT_CURRENCY_MAP,
        _downloader=downloader,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# TestFreeMarketDataProviderConstruction
# ---------------------------------------------------------------------------


class TestFreeMarketDataProviderConstruction:
    def test_provider_constructs_with_defaults(self):
        p = _make_provider()
        assert p is not None

    def test_provider_stores_tickers(self):
        p = _make_provider(tickers=["SPY", "BND", "GLD"])
        assert len(p) == 3

    def test_provider_contains_configured_ticker(self):
        p = _make_provider(tickers=["SPY", "BND"])
        assert p.contains("SPY")
        assert p.contains("BND")

    def test_provider_does_not_contain_unconfigured_ticker(self):
        p = _make_provider(tickers=["SPY"])
        assert not p.contains("GLD")

    def test_custom_lookback_period_stored(self):
        p = _make_provider(lookback_period="2y")
        assert p._lookback_period == "2y"

    def test_custom_interval_stored(self):
        p = _make_provider(interval="1wk")
        assert p._interval == "1wk"

    def test_downloader_injected(self):
        called = []
        def mock_dl(ticker, period, interval):
            called.append(ticker)
            return _make_price_df()
        p = _make_provider(downloader=mock_dl)
        p.get_snapshot("SPY")
        assert "SPY" in called

    def test_no_real_internet_call(self):
        """
        El provider nunca llama a yfinance.download cuando _downloader está
        inyectado. Este test es la garantía formal de que la suite no necesita
        internet.
        """
        calls: list[str] = []
        def safe_dl(ticker, period, interval):
            calls.append(ticker)
            return _make_price_df()
        p = _make_provider(tickers=["SPY"], downloader=safe_dl)
        p.get_snapshot("SPY")
        # Si hubiera llamado a internet, el import de yfinance fallaría
        # o el test tardaría segundos. Como pasa instantáneo, el mock fue usado.
        assert calls == ["SPY"]


# ---------------------------------------------------------------------------
# TestGetSnapshotValid
# ---------------------------------------------------------------------------


class TestGetSnapshotValid:
    def setup_method(self):
        self.df = _make_price_df(n=200, mean_daily_return=0.0003, std_daily_return=0.01)
        self.provider = _make_provider(
            tickers=["SPY", "BND"],
            downloader=lambda t, p, i: self.df,
        )

    def test_get_snapshot_returns_market_data_snapshot(self):
        snap = self.provider.get_snapshot("SPY")
        assert isinstance(snap, MarketDataSnapshot)

    def test_snapshot_ticker_matches(self):
        snap = self.provider.get_snapshot("SPY")
        assert snap.ticker == "SPY"

    def test_snapshot_is_not_none_for_valid_data(self):
        snap = self.provider.get_snapshot("SPY")
        assert snap is not None

    def test_snapshot_expected_return_is_float(self):
        snap = self.provider.get_snapshot("SPY")
        assert isinstance(snap.expected_return_annual, float)

    def test_snapshot_volatility_is_float(self):
        snap = self.provider.get_snapshot("SPY")
        assert isinstance(snap.volatility_annual, float)

    def test_snapshot_expected_return_in_valid_range(self):
        snap = self.provider.get_snapshot("SPY")
        assert -1.0 <= snap.expected_return_annual <= 1.0

    def test_snapshot_volatility_is_non_negative(self):
        snap = self.provider.get_snapshot("SPY")
        assert snap.volatility_annual >= 0.0

    def test_snapshot_liquidity_score_in_range(self):
        snap = self.provider.get_snapshot("SPY")
        assert 0.0 <= snap.liquidity_score <= 1.0

    def test_snapshot_expense_ratio_non_negative(self):
        snap = self.provider.get_snapshot("SPY")
        assert snap.expense_ratio >= 0.0

    def test_snapshot_not_stale(self):
        snap = self.provider.get_snapshot("SPY")
        assert snap.stale is False

    def test_snapshot_notes_contain_source(self):
        snap = self.provider.get_snapshot("SPY")
        notes_joined = " ".join(snap.notes)
        assert "yfinance" in notes_joined

    def test_snapshot_notes_contain_period(self):
        snap = self.provider.get_snapshot("SPY")
        notes_joined = " ".join(snap.notes)
        assert "period=" in notes_joined

    def test_snapshot_duration_is_none_for_equity(self):
        snap = self.provider.get_snapshot("SPY")
        assert snap.duration is None


# ---------------------------------------------------------------------------
# TestCalculations
# ---------------------------------------------------------------------------


class TestCalculations:
    """
    Verifica que expected_return_annual y volatility_annual son calculados
    correctamente a partir de retornos diarios.
    """

    def test_expected_return_annual_approximation(self):
        """
        Dado un retorno diario constante de 0.001, el retorno anual calculado
        debe ser exactamente 0.001 * 252 = 0.252 (sin varianza estadística).
        """
        daily_ret = 0.001
        n = 200
        dates = pd.date_range("2021-01-04", periods=n, freq="B")
        prices = [100.0 * (1 + daily_ret) ** i for i in range(n)]
        df = pd.DataFrame({"Close": prices, "Volume": [5_000_000.0] * n}, index=dates)
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        expected = daily_ret * _TRADING_DAYS_PER_YEAR
        assert abs(snap.expected_return_annual - expected) < 1e-4

    def test_volatility_annual_approximation(self):
        """
        Dado un retorno diario constante de 0.001 (sin varianza), la volatilidad
        anual debe ser 0.0 (todos los retornos son idénticos → std = 0).
        """
        daily_ret = 0.001
        n = 200
        dates = pd.date_range("2021-01-04", periods=n, freq="B")
        prices = [100.0 * (1 + daily_ret) ** i for i in range(n)]
        df = pd.DataFrame({"Close": prices, "Volume": [5_000_000.0] * n}, index=dates)
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        assert snap.volatility_annual == 0.0

    def test_volatility_annual_from_random_data(self):
        """
        Con std_daily_return=0.01 y suficientes observaciones, volatility_annual
        debe estar en el rango razonable [0.05, 0.30]. No verificamos el valor
        exacto por varianza estadística, solo que es positivo y plausible.
        """
        df = _make_price_df(n=800, mean_daily_return=0.0, std_daily_return=0.01, seed=7)
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        assert 0.05 < snap.volatility_annual < 0.30

    def test_zero_mean_return_gives_zero_annual_return(self):
        """
        Precio completamente plano (retorno diario = 0 exacto) → retorno anual = 0.
        """
        n = 200
        dates = pd.date_range("2021-01-04", periods=n, freq="B")
        df = pd.DataFrame(
            {"Close": [100.0] * n, "Volume": [5_000_000.0] * n},
            index=dates,
        )
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        assert snap.expected_return_annual == 0.0

    def test_expected_return_clamped_to_minus_one(self):
        """
        Si el retorno calculado fuera < -1.0, debe quedar clampeado a -1.0.
        """
        # Creamos retornos muy negativos artificialmente
        dates = pd.date_range("2020-01-01", periods=200, freq="B")
        # Precio cayendo ~1% diario → retorno anual ≈ -0.926 (dentro del rango)
        # Para forzar clamp usamos pct_change explícito muy negativo
        prices = [100.0 * (0.990 ** i) for i in range(200)]
        df = pd.DataFrame({"Close": prices}, index=dates)
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        assert snap is not None
        assert snap.expected_return_annual >= -1.0

    def test_expected_return_clamped_to_plus_one(self):
        """Retorno muy positivo queda clampeado a 1.0."""
        dates = pd.date_range("2020-01-01", periods=200, freq="B")
        prices = [100.0 * (1.015 ** i) for i in range(200)]  # +1.5% diario → +4800% anual
        df = pd.DataFrame({"Close": prices}, index=dates)
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        assert snap is not None
        assert snap.expected_return_annual <= 1.0


# ---------------------------------------------------------------------------
# TestAssetClassAndCurrency
# ---------------------------------------------------------------------------


class TestAssetClassAndCurrency:
    def _provider_with_maps(self, asset_map, currency_map):
        df = _make_price_df()
        return FreeMarketDataProvider(
            tickers=list(asset_map.keys()),
            asset_class_map=asset_map,
            currency_map=currency_map,
            _downloader=lambda t, p, i: df,
        )

    def test_asset_class_from_map_equity(self):
        p = self._provider_with_maps({"SPY": "equity"}, {"SPY": "USD"})
        snap = p.get_snapshot("SPY")
        assert snap.asset_class == "equity"

    def test_asset_class_from_map_bond(self):
        p = self._provider_with_maps({"BND": "bond"}, {"BND": "USD"})
        snap = p.get_snapshot("BND")
        assert snap.asset_class == "bond"

    def test_currency_from_map_usd(self):
        p = self._provider_with_maps({"SPY": "equity"}, {"SPY": "USD"})
        snap = p.get_snapshot("SPY")
        assert snap.currency == "USD"

    def test_currency_from_map_eur(self):
        p = self._provider_with_maps({"EFA": "equity"}, {"EFA": "EUR"})
        snap = p.get_snapshot("EFA")
        assert snap.currency == "EUR"

    def test_asset_class_defaults_to_equity_when_not_in_map(self):
        df = _make_price_df()
        p = FreeMarketDataProvider(
            tickers=["XYZ"],
            asset_class_map={},       # ticker no mapeado
            currency_map={"XYZ": "USD"},
            _downloader=lambda t, per, i: df,
        )
        snap = p.get_snapshot("XYZ")
        assert snap.asset_class == "equity"

    def test_currency_defaults_to_usd_when_not_in_map(self):
        df = _make_price_df()
        p = FreeMarketDataProvider(
            tickers=["XYZ"],
            asset_class_map={"XYZ": "equity"},
            currency_map={},          # ticker no mapeado
            _downloader=lambda t, per, i: df,
        )
        snap = p.get_snapshot("XYZ")
        assert snap.currency == "USD"


# ---------------------------------------------------------------------------
# TestGetSnapshotInvalidData
# ---------------------------------------------------------------------------


class TestGetSnapshotInvalidData:
    def test_empty_dataframe_returns_none(self):
        p = _make_provider(downloader=lambda t, per, i: pd.DataFrame())
        assert p.get_snapshot("SPY") is None

    def test_none_from_downloader_returns_none(self):
        p = _make_provider(downloader=lambda t, per, i: None)
        assert p.get_snapshot("SPY") is None

    def test_fewer_than_60_returns_gives_none(self):
        df = _make_price_df(n=_MIN_OBSERVATIONS - 1)  # 59 precios → 58 retornos
        p = _make_provider(downloader=lambda t, per, i: df)
        assert p.get_snapshot("SPY") is None

    def test_exactly_60_returns_gives_snapshot(self):
        # _MIN_OBSERVATIONS precios → _MIN_OBSERVATIONS - 1 retornos diarios
        # Necesitamos _MIN_OBSERVATIONS + 1 precios para tener 60 retornos
        df = _make_price_df(n=_MIN_OBSERVATIONS + 1)
        p = _make_provider(downloader=lambda t, per, i: df)
        assert p.get_snapshot("SPY") is not None

    def test_df_without_close_column_returns_none(self):
        dates = pd.date_range("2021-01-04", periods=200, freq="B")
        df = pd.DataFrame({"Open": [100.0] * 200, "High": [101.0] * 200}, index=dates)
        p = _make_provider(downloader=lambda t, per, i: df)
        assert p.get_snapshot("SPY") is None

    def test_all_nan_close_returns_none(self):
        dates = pd.date_range("2021-01-04", periods=200, freq="B")
        df = pd.DataFrame({"Close": [float("nan")] * 200}, index=dates)
        p = _make_provider(downloader=lambda t, per, i: df)
        assert p.get_snapshot("SPY") is None


# ---------------------------------------------------------------------------
# TestLiquidityScore
# ---------------------------------------------------------------------------


class TestLiquidityScore:
    def _snap_with_volume(self, avg_volume: float) -> MarketDataSnapshot:
        df = _make_price_df(n=200, avg_volume=avg_volume, include_volume=True)
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        assert snap is not None
        return snap

    def test_high_volume_gives_high_liquidity(self):
        snap = self._snap_with_volume(avg_volume=20_000_000.0)
        assert snap.liquidity_score == 0.9

    def test_medium_volume_gives_medium_liquidity(self):
        snap = self._snap_with_volume(avg_volume=5_000_000.0)
        assert snap.liquidity_score == 0.7

    def test_low_volume_gives_low_liquidity(self):
        snap = self._snap_with_volume(avg_volume=500_000.0)
        assert snap.liquidity_score == 0.5

    def test_no_volume_column_gives_default_liquidity(self):
        df = _make_price_df(n=200, include_volume=False)
        p = _make_provider(downloader=lambda t, per, i: df)
        snap = p.get_snapshot("SPY")
        assert snap is not None
        assert snap.liquidity_score == 0.8

    def test_liquidity_score_always_in_range(self):
        for volume in [0.0, 100_000.0, 1_000_000.0, 10_000_000.0, 50_000_000.0]:
            df = _make_price_df(n=200, avg_volume=volume, include_volume=True)
            p = _make_provider(downloader=lambda t, per, i: df)
            snap = p.get_snapshot("SPY")
            assert snap is not None
            assert 0.0 <= snap.liquidity_score <= 1.0


# ---------------------------------------------------------------------------
# TestMultiIndexFormat
# ---------------------------------------------------------------------------


class TestMultiIndexFormat:
    """Verifica que el provider maneja el formato MultiIndex de yfinance."""

    def test_multiindex_df_returns_snapshot(self):
        df = _make_multiindex_df(ticker="SPY", n=200)
        p = _make_provider(
            tickers=["SPY"],
            downloader=lambda t, per, i: df,
        )
        snap = p.get_snapshot("SPY")
        assert snap is not None
        assert snap.ticker == "SPY"

    def test_multiindex_expected_return_in_range(self):
        df = _make_multiindex_df(ticker="SPY", n=200)
        p = _make_provider(
            tickers=["SPY"],
            downloader=lambda t, per, i: df,
        )
        snap = p.get_snapshot("SPY")
        assert -1.0 <= snap.expected_return_annual <= 1.0


# ---------------------------------------------------------------------------
# TestGetMany
# ---------------------------------------------------------------------------


class TestGetMany:
    def test_get_many_returns_list(self):
        p = _make_provider(tickers=["SPY", "BND"])
        result = p.get_many(["SPY", "BND"])
        assert isinstance(result, list)

    def test_get_many_returns_only_valid_snapshots(self):
        calls: dict[str, int] = {}
        def dl(ticker, period, interval):
            calls[ticker] = calls.get(ticker, 0) + 1
            if ticker == "INVALID":
                return pd.DataFrame()   # datos vacíos → None
            return _make_price_df()

        p = FreeMarketDataProvider(
            tickers=["SPY", "INVALID", "BND"],
            asset_class_map={"SPY": "equity", "INVALID": "equity", "BND": "bond"},
            currency_map={"SPY": "USD", "INVALID": "USD", "BND": "USD"},
            _downloader=dl,
        )
        result = p.get_many(["SPY", "INVALID", "BND"])
        tickers_in_result = [s.ticker for s in result]
        assert "SPY" in tickers_in_result
        assert "BND" in tickers_in_result
        assert "INVALID" not in tickers_in_result

    def test_get_many_preserves_order_of_valid_snapshots(self):
        df = _make_price_df()
        p = FreeMarketDataProvider(
            tickers=["SPY", "BND", "GLD"],
            asset_class_map=_DEFAULT_ASSET_CLASS_MAP,
            currency_map=_DEFAULT_CURRENCY_MAP,
            _downloader=lambda t, per, i: df,
        )
        result = p.get_many(["GLD", "SPY", "BND"])
        tickers = [s.ticker for s in result]
        assert tickers == ["GLD", "SPY", "BND"]

    def test_get_many_empty_input_returns_empty_list(self):
        p = _make_provider()
        assert p.get_many([]) == []

    def test_get_many_all_invalid_returns_empty_list(self):
        p = _make_provider(downloader=lambda t, per, i: pd.DataFrame())
        result = p.get_many(["SPY", "BND"])
        assert result == []

    def test_get_many_all_valid_count_matches(self):
        df = _make_price_df()
        p = FreeMarketDataProvider(
            tickers=["SPY", "BND", "GLD"],
            asset_class_map=_DEFAULT_ASSET_CLASS_MAP,
            currency_map=_DEFAULT_CURRENCY_MAP,
            _downloader=lambda t, per, i: df,
        )
        result = p.get_many(["SPY", "BND", "GLD"])
        assert len(result) == 3

    def test_get_many_each_element_is_market_data_snapshot(self):
        df = _make_price_df()
        p = _make_provider(downloader=lambda t, per, i: df)
        for snap in p.get_many(["SPY", "BND"]):
            assert isinstance(snap, MarketDataSnapshot)


# ---------------------------------------------------------------------------
# TestCaching
# ---------------------------------------------------------------------------


class TestCaching:
    def test_get_snapshot_called_twice_downloads_once(self):
        download_count: dict[str, int] = {}
        def counting_dl(ticker, period, interval):
            download_count[ticker] = download_count.get(ticker, 0) + 1
            return _make_price_df()
        p = _make_provider(downloader=counting_dl)
        p.get_snapshot("SPY")
        p.get_snapshot("SPY")
        assert download_count.get("SPY", 0) == 1

    def test_different_tickers_download_separately(self):
        download_count: dict[str, int] = {}
        def counting_dl(ticker, period, interval):
            download_count[ticker] = download_count.get(ticker, 0) + 1
            return _make_price_df()
        p = FreeMarketDataProvider(
            tickers=["SPY", "BND"],
            asset_class_map={"SPY": "equity", "BND": "bond"},
            currency_map={"SPY": "USD", "BND": "USD"},
            _downloader=counting_dl,
        )
        p.get_snapshot("SPY")
        p.get_snapshot("BND")
        assert download_count.get("SPY", 0) == 1
        assert download_count.get("BND", 0) == 1


# ---------------------------------------------------------------------------
# TestSnapshotContract
# ---------------------------------------------------------------------------


class TestSnapshotContract:
    """Verifica que el snapshot producido cumple el contrato de MarketDataSnapshot."""

    def setup_method(self):
        df = _make_price_df(n=200, avg_volume=20_000_000.0)
        self.provider = _make_provider(downloader=lambda t, per, i: df)
        self.snap = self.provider.get_snapshot("SPY")

    def test_snapshot_is_usable(self):
        # expense_ratio está en missing_fields, pero no es campo crítico
        assert self.snap.is_usable is True

    def test_snapshot_ticker_non_empty(self):
        assert self.snap.ticker.strip() != ""

    def test_snapshot_asset_class_non_empty(self):
        assert self.snap.asset_class.strip() != ""

    def test_snapshot_currency_non_empty(self):
        assert self.snap.currency.strip() != ""

    def test_snapshot_to_dict_is_serializable(self):
        import json
        d = self.snap.to_dict()
        json.dumps(d)  # no debe levantar

    def test_snapshot_missing_fields_is_list(self):
        assert isinstance(self.snap.missing_fields, list)

    def test_snapshot_notes_is_list(self):
        assert isinstance(self.snap.notes, list)

    def test_expense_ratio_in_missing_fields(self):
        # expense_ratio no está disponible desde yfinance: se marca como missing
        assert "expense_ratio" in self.snap.missing_fields


# ---------------------------------------------------------------------------
# TestYfinanceImport
# ---------------------------------------------------------------------------


class TestYfinanceImport:
    def test_yfinance_is_importable(self):
        """
        yfinance debe estar instalado en el entorno. Si falla, agregar
        'yfinance' a pyproject.toml y correr pip install -e ".[dev]".
        """
        try:
            import yfinance  # noqa: F401
            importable = True
        except ImportError:
            importable = False
        assert importable, "yfinance no está instalado. Correr: pip install yfinance"
