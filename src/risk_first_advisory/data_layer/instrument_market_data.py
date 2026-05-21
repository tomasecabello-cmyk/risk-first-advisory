"""
InstrumentMarketDataAdapter — bridge between InstrumentUniverse and MarketDataSnapshot.

Converts FinancialInstrument (universe_layer domain) into MarketDataSnapshot
(data_layer contract) using deterministic proxy estimates for return and
volatility. No market data downloads, no external services, no randomness.

Supported instrument types (produce a snapshot):
    CORPORATE_BOND, SOVEREIGN_BOND, MONEY_MARKET

Unsupported types (to_snapshot returns None):
    ETF, STOCK, CEDEAR, MUTUAL_FUND, OTHER

Return proxy (in order of precedence):
    1. ytm  — stored as percentage in CSV (e.g. 7.80 → 0.078 after /100)
    2. coupon_rate — same percentage → decimal conversion
    3. 0.0  — "expected_return_annual" added to missing_fields

Volatility proxy:
    base = max(0.01, duration * 0.025)           if duration is available
    base = type-specific fallback                 otherwise
    liquidity_penalty = (1 - liquidity_score) * 0.03
    rating_penalty: "BB" in rating → 0.02
                    "B" in rating (no "BB") → 0.04
                    None / empty → 0.02
    volatility = clamp(base + liquidity_penalty + rating_penalty, 0.001, 1.0)

expense_ratio is always 0.0 (not available in the universe CSV).
asset_class is the enum value string (e.g. "FIXED_INCOME", "CASH").
"""

from __future__ import annotations

from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.universe_layer.instruments import (
    FinancialInstrument,
    InstrumentType,
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_FIXED_INCOME_TYPES: frozenset[InstrumentType] = frozenset(
    {
        InstrumentType.CORPORATE_BOND,
        InstrumentType.SOVEREIGN_BOND,
        InstrumentType.MONEY_MARKET,
    }
)

# Volatility base when no duration is available
_VOLATILITY_NO_DURATION: dict[InstrumentType, float] = {
    InstrumentType.MONEY_MARKET:   0.01,
    InstrumentType.CORPORATE_BOND: 0.08,
    InstrumentType.SOVEREIGN_BOND: 0.10,
}

_DURATION_VOL_FACTOR:   float = 0.025  # annualised vol per year of duration
_LIQUIDITY_VOL_FACTOR:  float = 0.03   # penalty per unit of (1 - liquidity)

_RATING_PENALTY_BB:     float = 0.02   # rating string contains "BB"
_RATING_PENALTY_B_ONLY: float = 0.04   # rating string contains "B" but not "BB"
_RATING_PENALTY_NONE:   float = 0.02   # rating is None or empty

_VOL_CLAMP_MIN: float = 0.001
_VOL_CLAMP_MAX: float = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────────────


class InstrumentMarketDataAdapter:
    """
    Stateless adapter that converts a FinancialInstrument into a
    MarketDataSnapshot using deterministic proxy logic.

    This adapter does NOT generate portfolios, does NOT call any AI
    service, and does NOT download market data.

    Usage::

        adapter = InstrumentMarketDataAdapter()

        snap = adapter.to_snapshot(instrument)   # None if unsupported type
        snaps = adapter.to_many(instruments)     # skips unsupported types
    """

    # ── public API ────────────────────────────────────────────────────────────

    def to_snapshot(self, instrument: FinancialInstrument) -> MarketDataSnapshot | None:
        """
        Convert *instrument* to a MarketDataSnapshot.

        Returns ``None`` for ETF, STOCK, CEDEAR, MUTUAL_FUND, and OTHER —
        those instrument types are not handled by this adapter.
        """
        if instrument.instrument_type not in _FIXED_INCOME_TYPES:
            return None

        itype = instrument.instrument_type
        missing_fields: list[str] = []
        notes: list[str] = [
            "source=instrument_universe_csv",
            f"instrument_type={itype.value}",
        ]

        expected_return = self._compute_expected_return(instrument, missing_fields, notes)
        volatility = self._compute_volatility(instrument, itype)
        notes.append("proxy_volatility=duration_rating_liquidity")

        return MarketDataSnapshot(
            ticker=instrument.ticker,
            expected_return_annual=expected_return,
            volatility_annual=volatility,
            liquidity_score=instrument.liquidity_score,
            expense_ratio=0.0,
            duration=instrument.duration,
            asset_class=instrument.asset_class.value,
            currency=instrument.currency,
            stale=False,
            missing_fields=missing_fields,
            notes=notes,
        )

    def to_many(
        self, instruments: list[FinancialInstrument]
    ) -> list[MarketDataSnapshot]:
        """
        Convert a list of FinancialInstruments to MarketDataSnapshots.

        Instruments with unsupported types are silently omitted.
        Insertion order is preserved among the accepted instruments.
        """
        result: list[MarketDataSnapshot] = []
        for instrument in instruments:
            snap = self.to_snapshot(instrument)
            if snap is not None:
                result.append(snap)
        return result

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _compute_expected_return(
        instrument: FinancialInstrument,
        missing_fields: list[str],
        notes: list[str],
    ) -> float:
        """
        Derive expected_return_annual from ytm or coupon_rate (both stored
        as percentages in the CSV, e.g. 7.80 means 7.80 %).

        Falls back to 0.0 and records "expected_return_annual" in
        missing_fields when neither field is available.
        """
        if instrument.ytm is not None:
            raw = instrument.ytm / 100.0
            notes.append("proxy_return=ytm")
        elif instrument.coupon_rate is not None:
            raw = instrument.coupon_rate / 100.0
            notes.append("proxy_return=coupon_rate")
        else:
            missing_fields.append("expected_return_annual")
            notes.append("proxy_return=unavailable")
            return 0.0

        # Safety clamp — YTM/coupon should never exceed 100 % in practice
        return max(-1.0, min(1.0, raw))

    @staticmethod
    def _compute_volatility(
        instrument: FinancialInstrument,
        itype: InstrumentType,
    ) -> float:
        """
        Estimate annualised volatility using a deterministic proxy.

        Formula:
            base             = max(0.01, duration * 0.025)   if duration present
                             = type-specific fallback         otherwise
            liquidity_penalty = (1 - liquidity_score) * 0.03
            rating_penalty    = f(rating)
            volatility        = clamp(base + penalties, 0.001, 1.0)
        """
        # Base component
        if instrument.duration is not None:
            base = max(0.01, instrument.duration * _DURATION_VOL_FACTOR)
        else:
            base = _VOLATILITY_NO_DURATION[itype]

        # Liquidity penalty
        liquidity_penalty = (1.0 - instrument.liquidity_score) * _LIQUIDITY_VOL_FACTOR

        # Rating penalty
        rating = instrument.rating or ""
        if "BB" in rating:
            rating_penalty = _RATING_PENALTY_BB
        elif "B" in rating:
            rating_penalty = _RATING_PENALTY_B_ONLY
        else:
            rating_penalty = _RATING_PENALTY_NONE

        total = base + liquidity_penalty + rating_penalty
        vol = max(_VOL_CLAMP_MIN, min(_VOL_CLAMP_MAX, total))

        # note is appended to the outer notes list by the caller via to_snapshot
        return vol
