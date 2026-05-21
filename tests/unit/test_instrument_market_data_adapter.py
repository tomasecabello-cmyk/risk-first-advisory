"""
Unit tests for InstrumentMarketDataAdapter.

Coverage:
  - Unsupported instrument types return None (ETF, STOCK, CEDEAR, MUTUAL_FUND, OTHER)
  - Fixed income types produce snapshots (CORPORATE_BOND, SOVEREIGN_BOND, MONEY_MARKET)
  - YTM → expected_return_annual conversion (percentage → decimal, /100)
  - coupon_rate fallback when ytm is None
  - missing_fields when neither ytm nor coupon_rate is available
  - Volatility proxy: duration-based base vs type fallback
  - Liquidity penalty
  - Rating penalties: BB, B-only, None/empty, CCC (no B)
  - Clamping: volatility [0.001, 1.0], return [-1.0, 1.0]
  - notes content: source, instrument_type, proxy_return, proxy_volatility
  - expense_ratio always 0.0
  - asset_class is enum value string
  - stale always False
  - to_many: skips None, preserves order
  - Integration: GALI28 full fixture test via CSV loader + filter
"""

from __future__ import annotations

import pytest

from risk_first_advisory.data_layer.instrument_market_data import (
    InstrumentMarketDataAdapter,
)
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.universe_layer.instruments import (
    AssetClass,
    FinancialInstrument,
    InstrumentType,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — minimal FinancialInstrument factories
# ─────────────────────────────────────────────────────────────────────────────


def _bond(
    ticker: str = "TST01",
    instrument_type: InstrumentType = InstrumentType.CORPORATE_BOND,
    asset_class: AssetClass = AssetClass.FIXED_INCOME,
    currency: str = "USD",
    country: str = "AR",
    ytm: float | None = 7.80,
    coupon_rate: float | None = 7.50,
    duration: float | None = 3.2,
    liquidity_score: float = 0.65,
    rating: str | None = "BB-",
) -> FinancialInstrument:
    return FinancialInstrument(
        ticker=ticker,
        name=f"Test Bond {ticker}",
        issuer="Test Issuer",
        instrument_type=instrument_type,
        asset_class=asset_class,
        currency=currency,
        country=country,
        sector="Financials",
        available_entities=["Balanz"],
        hard_dollar=True,
        maturity_date="2028-03-01",
        coupon_rate=coupon_rate,
        ytm=ytm,
        duration=duration,
        liquidity_score=liquidity_score,
        rating=rating,
    )


def _etf(ticker: str = "SPY") -> FinancialInstrument:
    return FinancialInstrument(
        ticker=ticker,
        name=f"Test ETF {ticker}",
        issuer="State Street",
        instrument_type=InstrumentType.ETF,
        asset_class=AssetClass.EQUITY,
        currency="USD",
        country="US",
        sector="Equity",
        available_entities=["Balanz"],
        hard_dollar=False,
        liquidity_score=0.99,
    )


def _money_market(
    ticker: str = "MM01",
    ytm: float | None = None,
    coupon_rate: float | None = None,
    duration: float | None = None,
    liquidity_score: float = 0.95,
    currency: str = "USD",
    rating: str | None = None,
) -> FinancialInstrument:
    return FinancialInstrument(
        ticker=ticker,
        name=f"Money Market {ticker}",
        issuer="Fund Manager",
        instrument_type=InstrumentType.MONEY_MARKET,
        asset_class=AssetClass.CASH,
        currency=currency,
        country="AR",
        sector="Cash",
        available_entities=["Balanz"],
        hard_dollar=True,
        liquidity_score=liquidity_score,
        ytm=ytm,
        coupon_rate=coupon_rate,
        duration=duration,
        rating=rating,
    )


def _sovereign(
    ticker: str = "SOV01",
    ytm: float | None = 14.50,
    coupon_rate: float | None = 0.50,
    duration: float | None = 4.5,
    liquidity_score: float = 0.80,
    rating: str | None = "CCC",
) -> FinancialInstrument:
    return FinancialInstrument(
        ticker=ticker,
        name=f"Sovereign Bond {ticker}",
        issuer="Republica Argentina",
        instrument_type=InstrumentType.SOVEREIGN_BOND,
        asset_class=AssetClass.FIXED_INCOME,
        currency="USD",
        country="AR",
        sector="Government",
        available_entities=["Balanz"],
        hard_dollar=True,
        maturity_date="2030-07-09",
        coupon_rate=coupon_rate,
        ytm=ytm,
        duration=duration,
        liquidity_score=liquidity_score,
        rating=rating,
    )


ADAPTER = InstrumentMarketDataAdapter()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Unsupported types return None
# ─────────────────────────────────────────────────────────────────────────────


class TestUnsupportedTypes:
    def test_etf_returns_none(self):
        assert ADAPTER.to_snapshot(_etf()) is None

    def test_stock_returns_none(self):
        inst = FinancialInstrument(
            ticker="TSLA",
            name="Tesla",
            issuer="Tesla Inc",
            instrument_type=InstrumentType.STOCK,
            asset_class=AssetClass.EQUITY,
            currency="USD",
            country="US",
            sector="Technology",
            available_entities=["PPI"],
            hard_dollar=False,
            liquidity_score=0.90,
        )
        assert ADAPTER.to_snapshot(inst) is None

    def test_cedear_returns_none(self):
        inst = FinancialInstrument(
            ticker="APBR",
            name="Petrobras CEDEAR",
            issuer="Petrobras",
            instrument_type=InstrumentType.CEDEAR,
            asset_class=AssetClass.EQUITY,
            currency="ARS",
            country="AR",
            sector="Energy",
            available_entities=["Balanz"],
            hard_dollar=False,
            liquidity_score=0.60,
        )
        assert ADAPTER.to_snapshot(inst) is None

    def test_mutual_fund_returns_none(self):
        inst = FinancialInstrument(
            ticker="FUND1",
            name="Test Fund",
            issuer="Asset Manager",
            instrument_type=InstrumentType.MUTUAL_FUND,
            asset_class=AssetClass.MULTI_ASSET,
            currency="USD",
            country="US",
            sector="Multi-Asset",
            available_entities=["PPI"],
            hard_dollar=False,
            liquidity_score=0.80,
        )
        assert ADAPTER.to_snapshot(inst) is None

    def test_other_returns_none(self):
        inst = FinancialInstrument(
            ticker="OTH1",
            name="Other Instrument",
            issuer="Issuer",
            instrument_type=InstrumentType.OTHER,
            asset_class=AssetClass.OTHER,
            currency="USD",
            country="US",
            sector="Other",
            available_entities=["Balanz"],
            hard_dollar=False,
            liquidity_score=0.50,
        )
        assert ADAPTER.to_snapshot(inst) is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Returns a MarketDataSnapshot for supported types
# ─────────────────────────────────────────────────────────────────────────────


class TestSnapshotType:
    def test_corporate_bond_returns_snapshot(self):
        snap = ADAPTER.to_snapshot(_bond())
        assert isinstance(snap, MarketDataSnapshot)

    def test_sovereign_bond_returns_snapshot(self):
        snap = ADAPTER.to_snapshot(_sovereign())
        assert isinstance(snap, MarketDataSnapshot)

    def test_money_market_returns_snapshot(self):
        snap = ADAPTER.to_snapshot(_money_market(ytm=5.0))
        assert isinstance(snap, MarketDataSnapshot)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Expected return conversion (YTM percentage → decimal)
# ─────────────────────────────────────────────────────────────────────────────


class TestExpectedReturn:
    def test_ytm_divided_by_100(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=7.80, coupon_rate=7.50))
        assert abs(snap.expected_return_annual - 0.078) < 1e-9

    def test_ytm_takes_precedence_over_coupon(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=8.00, coupon_rate=6.00))
        assert abs(snap.expected_return_annual - 0.08) < 1e-9

    def test_coupon_fallback_when_ytm_none(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=None, coupon_rate=6.00))
        assert abs(snap.expected_return_annual - 0.06) < 1e-9

    def test_zero_and_missing_fields_when_no_yield(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=None, coupon_rate=None))
        assert snap.expected_return_annual == 0.0
        assert "expected_return_annual" in snap.missing_fields

    def test_high_ytm_clamped_to_1(self):
        # YTM of 120 % would give 1.20 — must clamp to 1.0
        snap = ADAPTER.to_snapshot(_bond(ytm=120.0))
        assert snap.expected_return_annual == 1.0

    def test_sovereign_ytm_14_50(self):
        snap = ADAPTER.to_snapshot(_sovereign(ytm=14.50))
        assert abs(snap.expected_return_annual - 0.145) < 1e-9

    def test_coupon_rate_divided_by_100(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=None, coupon_rate=3.125))
        assert abs(snap.expected_return_annual - 0.03125) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# 4. Volatility proxy — base component
# ─────────────────────────────────────────────────────────────────────────────


class TestVolatilityBase:
    def test_duration_based_base_gali28(self):
        # duration=3.2 → base=max(0.01, 3.2*0.025)=0.08
        # liq=0.65 → penalty=(1-0.65)*0.03=0.0105
        # BB- → +0.02
        # total=0.08+0.0105+0.02=0.1105
        snap = ADAPTER.to_snapshot(
            _bond(duration=3.2, liquidity_score=0.65, rating="BB-")
        )
        assert abs(snap.volatility_annual - 0.1105) < 1e-9

    def test_short_duration_clamped_to_0_01_base(self):
        # duration=0.1 → 0.1*0.025=0.0025 < 0.01 → base=0.01
        snap = ADAPTER.to_snapshot(
            _bond(duration=0.1, liquidity_score=1.0, rating=None)
        )
        # base=0.01, liq_penalty=0, rating_none=0.02 → total=0.03
        assert abs(snap.volatility_annual - 0.03) < 1e-9

    def test_no_duration_money_market_fallback(self):
        # No duration → base=0.01 for MONEY_MARKET
        # liq=0.98 → penalty=0.0006; rating=None → 0.02
        snap = ADAPTER.to_snapshot(
            _money_market(duration=None, liquidity_score=0.98, ytm=4.0, rating=None)
        )
        expected = 0.01 + (1 - 0.98) * 0.03 + 0.02
        assert abs(snap.volatility_annual - expected) < 1e-9

    def test_no_duration_corporate_bond_fallback(self):
        # No duration → base=0.08 for CORPORATE_BOND
        # liq=1.0 → penalty=0; rating=None → 0.02
        snap = ADAPTER.to_snapshot(
            _bond(duration=None, liquidity_score=1.0, rating=None)
        )
        assert abs(snap.volatility_annual - (0.08 + 0.0 + 0.02)) < 1e-9

    def test_no_duration_sovereign_bond_fallback(self):
        # No duration → base=0.10 for SOVEREIGN_BOND
        # liq=1.0 → penalty=0; rating=None → 0.02
        snap = ADAPTER.to_snapshot(
            _sovereign(duration=None, liquidity_score=1.0, rating=None)
        )
        assert abs(snap.volatility_annual - (0.10 + 0.0 + 0.02)) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# 5. Volatility proxy — liquidity penalty
# ─────────────────────────────────────────────────────────────────────────────


class TestLiquidityPenalty:
    def test_perfect_liquidity_zero_penalty(self):
        snap1 = ADAPTER.to_snapshot(
            _bond(duration=2.0, liquidity_score=1.0, rating=None)
        )
        snap2 = ADAPTER.to_snapshot(
            _bond(duration=2.0, liquidity_score=0.90, rating=None)
        )
        # 10 % illiquid → 0.10 * 0.03 = 0.003 extra
        assert abs(snap2.volatility_annual - snap1.volatility_annual - 0.003) < 1e-9

    def test_zero_liquidity_max_penalty(self):
        # liquidity=0 → penalty=1.0*0.03=0.03
        snap = ADAPTER.to_snapshot(
            _bond(duration=None, liquidity_score=0.0, rating=None)
        )
        # base=0.08 (no duration, CORPORATE_BOND), penalty=0.03, rating_none=0.02
        assert abs(snap.volatility_annual - (0.08 + 0.03 + 0.02)) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# 6. Volatility proxy — rating penalty
# ─────────────────────────────────────────────────────────────────────────────


class TestRatingPenalty:
    def _base_vol(self, rating: str | None) -> float:
        """Helper: vol with duration=None (→0.08), liq=1.0, varying rating."""
        snap = ADAPTER.to_snapshot(
            _bond(duration=None, liquidity_score=1.0, rating=rating)
        )
        return snap.volatility_annual

    def test_rating_bb_minus(self):
        # "BB-" contains "BB" → penalty=0.02
        assert abs(self._base_vol("BB-") - (0.08 + 0.0 + 0.02)) < 1e-9

    def test_rating_bb(self):
        assert abs(self._base_vol("BB") - (0.08 + 0.0 + 0.02)) < 1e-9

    def test_rating_bbb(self):
        # "BBB" contains "BB" → penalty=0.02
        assert abs(self._base_vol("BBB") - (0.08 + 0.0 + 0.02)) < 1e-9

    def test_rating_b_only(self):
        # "B" contains "B" but not "BB" → penalty=0.04
        assert abs(self._base_vol("B") - (0.08 + 0.0 + 0.04)) < 1e-9

    def test_rating_b_plus(self):
        # "B+" contains "B" but not "BB" → penalty=0.04
        assert abs(self._base_vol("B+") - (0.08 + 0.0 + 0.04)) < 1e-9

    def test_rating_ccc(self):
        # "CCC" contains no "B" → penalty=0.02 (None/unknown branch)
        assert abs(self._base_vol("CCC") - (0.08 + 0.0 + 0.02)) < 1e-9

    def test_rating_none(self):
        assert abs(self._base_vol(None) - (0.08 + 0.0 + 0.02)) < 1e-9

    def test_rating_empty_string(self):
        assert abs(self._base_vol("") - (0.08 + 0.0 + 0.02)) < 1e-9

    def test_rating_a(self):
        # "A" has no "B" → penalty=0.02
        assert abs(self._base_vol("A") - (0.08 + 0.0 + 0.02)) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# 7. Volatility clamping
# ─────────────────────────────────────────────────────────────────────────────


class TestVolatilityClamping:
    def test_clamp_minimum_0_001(self):
        # Even with liquidity=1.0, rating=None, duration very small:
        # base=0.01, penalty=0, rating=0.02 → 0.03 > 0.001 — always above min
        # To test clamp_min we'd need negative components — not possible.
        # Just assert the result is at least 0.001.
        snap = ADAPTER.to_snapshot(_bond(duration=0.001, liquidity_score=1.0, rating="AA"))
        assert snap.volatility_annual >= 0.001

    def test_clamp_maximum_1_0(self):
        # Very long duration + illiquid: e.g. duration=40 → base=1.0
        # (40*0.025=1.0) + 0.03 + 0.04 > 1.0 → clamped to 1.0
        snap = ADAPTER.to_snapshot(
            _bond(duration=40.0, liquidity_score=0.0, rating="B")
        )
        assert snap.volatility_annual == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 8. Other snapshot fields
# ─────────────────────────────────────────────────────────────────────────────


class TestOtherFields:
    def test_ticker_preserved(self):
        snap = ADAPTER.to_snapshot(_bond(ticker="XTEST"))
        assert snap.ticker == "XTEST"

    def test_expense_ratio_always_zero(self):
        snap = ADAPTER.to_snapshot(_bond())
        assert snap.expense_ratio == 0.0

    def test_stale_always_false(self):
        snap = ADAPTER.to_snapshot(_bond())
        assert snap.stale is False

    def test_duration_preserved_when_present(self):
        snap = ADAPTER.to_snapshot(_bond(duration=3.2))
        assert snap.duration == 3.2

    def test_duration_none_when_absent(self):
        snap = ADAPTER.to_snapshot(_bond(duration=None))
        assert snap.duration is None

    def test_liquidity_score_preserved(self):
        snap = ADAPTER.to_snapshot(_bond(liquidity_score=0.65))
        assert snap.liquidity_score == 0.65

    def test_currency_preserved(self):
        snap = ADAPTER.to_snapshot(_bond(currency="USD"))
        assert snap.currency == "USD"

    def test_asset_class_is_enum_value_string(self):
        snap = ADAPTER.to_snapshot(_bond(asset_class=AssetClass.FIXED_INCOME))
        assert snap.asset_class == "FIXED_INCOME"

    def test_asset_class_cash_for_money_market(self):
        snap = ADAPTER.to_snapshot(
            _money_market(ytm=4.0)
        )
        assert snap.asset_class == "CASH"

    def test_is_usable_when_ytm_present(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=7.80))
        assert snap.is_usable is True

    def test_not_usable_when_missing_expected_return(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=None, coupon_rate=None))
        assert snap.is_usable is False


# ─────────────────────────────────────────────────────────────────────────────
# 9. Notes content
# ─────────────────────────────────────────────────────────────────────────────


class TestNotes:
    def test_notes_contain_source(self):
        snap = ADAPTER.to_snapshot(_bond())
        assert "source=instrument_universe_csv" in snap.notes

    def test_notes_contain_instrument_type(self):
        snap = ADAPTER.to_snapshot(_bond(instrument_type=InstrumentType.CORPORATE_BOND))
        assert "instrument_type=CORPORATE_BOND" in snap.notes

    def test_notes_contain_instrument_type_sovereign(self):
        snap = ADAPTER.to_snapshot(_sovereign())
        assert "instrument_type=SOVEREIGN_BOND" in snap.notes

    def test_notes_contain_proxy_return_ytm(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=7.80))
        assert "proxy_return=ytm" in snap.notes

    def test_notes_contain_proxy_return_coupon(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=None, coupon_rate=7.50))
        assert "proxy_return=coupon_rate" in snap.notes

    def test_notes_contain_proxy_return_unavailable(self):
        snap = ADAPTER.to_snapshot(_bond(ytm=None, coupon_rate=None))
        assert "proxy_return=unavailable" in snap.notes

    def test_notes_contain_proxy_volatility(self):
        snap = ADAPTER.to_snapshot(_bond())
        assert "proxy_volatility=duration_rating_liquidity" in snap.notes


# ─────────────────────────────────────────────────────────────────────────────
# 10. to_many
# ─────────────────────────────────────────────────────────────────────────────


class TestToMany:
    def test_empty_list(self):
        assert ADAPTER.to_many([]) == []

    def test_skips_unsupported_types(self):
        instruments = [_etf("SPY"), _bond("BOND1"), _etf("VTI")]
        snaps = ADAPTER.to_many(instruments)
        assert len(snaps) == 1
        assert snaps[0].ticker == "BOND1"

    def test_preserves_order(self):
        instruments = [
            _bond("B1", ytm=5.0),
            _bond("B2", ytm=6.0),
            _bond("B3", ytm=7.0),
        ]
        snaps = ADAPTER.to_many(instruments)
        assert [s.ticker for s in snaps] == ["B1", "B2", "B3"]

    def test_all_unsupported_returns_empty(self):
        instruments = [_etf("SPY"), _etf("VTI")]
        assert ADAPTER.to_many(instruments) == []

    def test_all_supported_converts_all(self):
        instruments = [_bond("B1"), _bond("B2"), _sovereign("S1")]
        snaps = ADAPTER.to_many(instruments)
        assert len(snaps) == 3

    def test_mixed_types_and_missing_fields(self):
        instruments = [
            _etf("SPY"),
            _bond("BOND_NO_YTM", ytm=None, coupon_rate=None),
            _money_market("MM_NO_YTM"),
        ]
        snaps = ADAPTER.to_many(instruments)
        assert len(snaps) == 2
        tickers = [s.ticker for s in snaps]
        assert "SPY" not in tickers
        assert "BOND_NO_YTM" in tickers
        assert "MM_NO_YTM" in tickers


# ─────────────────────────────────────────────────────────────────────────────
# 11. Integration — GALI28 from CSV fixture
# ─────────────────────────────────────────────────────────────────────────────


class TestGALI28Integration:
    """
    Loads the real CSV fixture, filters by Balanz + USD + Argentina +
    hard_dollar + CORPORATE_BOND + avoid Energy, then converts GALI28.
    Verifies the exact expected_return_annual and volatility_annual.
    """

    @pytest.fixture(scope="class")
    def gali28_snapshot(self) -> MarketDataSnapshot:
        from pathlib import Path

        from risk_first_advisory.universe_layer.csv_provider import (
            CSVInstrumentUniverseProvider,
        )
        from risk_first_advisory.universe_layer.instruments import InstrumentType
        from risk_first_advisory.universe_layer.preference_filter import (
            PreferenceFilterEngine,
        )

        csv_path = (
            Path(__file__).parents[2]
            / "tests"
            / "fixtures"
            / "universe"
            / "sample_instrument_universe.csv"
        )
        provider = CSVInstrumentUniverseProvider(csv_path)
        universe = provider.load()

        engine = PreferenceFilterEngine()
        preferences = {
            "entity": "Balanz",
            "currency": "USD",
            "country": "Argentina",
            "hard_dollar_only": True,
            "allowed_instrument_types": ["CORPORATE_BOND"],
            "avoid_sectors": ["Energy"],
        }
        result = engine.apply(universe, preferences)
        eligible = result.eligible_universe.instruments

        adapter = InstrumentMarketDataAdapter()
        snaps = adapter.to_many(eligible)

        # Should be exactly one instrument: GALI28
        assert len(snaps) == 1, f"Expected 1 snapshot, got {len(snaps)}: {[s.ticker for s in snaps]}"
        return snaps[0]

    def test_ticker(self, gali28_snapshot):
        assert gali28_snapshot.ticker == "GALI28"

    def test_expected_return_annual(self, gali28_snapshot):
        # ytm=7.80 → 7.80/100 = 0.078
        assert abs(gali28_snapshot.expected_return_annual - 0.078) < 1e-9

    def test_volatility_annual(self, gali28_snapshot):
        # base=max(0.01, 3.2*0.025)=0.08
        # liq_penalty=(1-0.65)*0.03=0.0105
        # rating "BB-" contains "BB" → 0.02
        # total = 0.08 + 0.0105 + 0.02 = 0.1105
        assert abs(gali28_snapshot.volatility_annual - 0.1105) < 1e-9

    def test_duration(self, gali28_snapshot):
        assert gali28_snapshot.duration == 3.2

    def test_liquidity_score(self, gali28_snapshot):
        assert gali28_snapshot.liquidity_score == 0.65

    def test_currency(self, gali28_snapshot):
        assert gali28_snapshot.currency == "USD"

    def test_asset_class(self, gali28_snapshot):
        assert gali28_snapshot.asset_class == "FIXED_INCOME"

    def test_expense_ratio(self, gali28_snapshot):
        assert gali28_snapshot.expense_ratio == 0.0

    def test_stale(self, gali28_snapshot):
        assert gali28_snapshot.stale is False

    def test_is_usable(self, gali28_snapshot):
        assert gali28_snapshot.is_usable is True

    def test_notes_source(self, gali28_snapshot):
        assert "source=instrument_universe_csv" in gali28_snapshot.notes

    def test_notes_proxy_return_ytm(self, gali28_snapshot):
        assert "proxy_return=ytm" in gali28_snapshot.notes

    def test_notes_proxy_volatility(self, gali28_snapshot):
        assert "proxy_volatility=duration_rating_liquidity" in gali28_snapshot.notes
