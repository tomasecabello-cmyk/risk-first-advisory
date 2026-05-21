"""
Financial instrument domain model.

InstrumentType  — enum of supported instrument categories.
AssetClass      — enum of broad asset classes.
FinancialInstrument — immutable-ish dataclass for a single instrument.
InstrumentUniverse  — collection of instruments with chainable filters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class InstrumentType(str, Enum):
    ETF            = "ETF"
    CORPORATE_BOND = "CORPORATE_BOND"
    SOVEREIGN_BOND = "SOVEREIGN_BOND"
    STOCK          = "STOCK"
    CEDEAR         = "CEDEAR"
    MUTUAL_FUND    = "MUTUAL_FUND"
    MONEY_MARKET   = "MONEY_MARKET"
    OTHER          = "OTHER"


class AssetClass(str, Enum):
    CASH         = "CASH"
    FIXED_INCOME = "FIXED_INCOME"
    EQUITY       = "EQUITY"
    HIGH_YIELD   = "HIGH_YIELD"
    COMMODITY    = "COMMODITY"
    MULTI_ASSET  = "MULTI_ASSET"
    OTHER        = "OTHER"


# ─────────────────────────────────────────────────────────────────────────────
# FinancialInstrument
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class FinancialInstrument:
    """Single financial instrument with metadata for filtering and suitability."""

    ticker:             str
    name:               str
    issuer:             str
    instrument_type:    InstrumentType
    asset_class:        AssetClass
    currency:           str
    country:            str
    sector:             str
    available_entities: list[str]
    hard_dollar:        bool

    # Optional fixed-income fields
    maturity_date:  str | None   = None
    coupon_rate:    float | None = None
    ytm:            float | None = None
    duration:       float | None = None

    # Operational fields
    liquidity_score: float       = 0.0
    min_piece:       float | None = None
    rating:          str | None  = None
    notes:           list[str]   = field(default_factory=list)

    # ── validation ──────────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        # Non-empty string fields
        for attr in ("ticker", "name", "issuer", "currency", "country", "sector"):
            val = getattr(self, attr)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(
                    f"FinancialInstrument.{attr} must be a non-empty string, got {val!r}."
                )

        # Enum types
        if not isinstance(self.instrument_type, InstrumentType):
            raise TypeError(
                f"instrument_type must be InstrumentType, "
                f"got {type(self.instrument_type).__name__!r}."
            )
        if not isinstance(self.asset_class, AssetClass):
            raise TypeError(
                f"asset_class must be AssetClass, "
                f"got {type(self.asset_class).__name__!r}."
            )

        # available_entities
        if not isinstance(self.available_entities, list) or not all(
            isinstance(e, str) for e in self.available_entities
        ):
            raise TypeError("available_entities must be a list[str].")

        # hard_dollar
        if not isinstance(self.hard_dollar, bool):
            raise TypeError(
                f"hard_dollar must be bool, got {type(self.hard_dollar).__name__!r}."
            )

        # liquidity_score range
        if not (0.0 <= self.liquidity_score <= 1.0):
            raise ValueError(
                f"liquidity_score must be in [0.0, 1.0], got {self.liquidity_score!r}."
            )

        # Optional non-negative floats
        for attr in ("coupon_rate", "ytm", "duration", "min_piece"):
            val = getattr(self, attr)
            if val is not None and val < 0.0:
                raise ValueError(
                    f"{attr} must be >= 0.0 when provided, got {val!r}."
                )

        # notes
        if not isinstance(self.notes, list) or not all(
            isinstance(n, str) for n in self.notes
        ):
            raise TypeError("notes must be a list[str].")

    # ── serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker":             self.ticker,
            "name":               self.name,
            "issuer":             self.issuer,
            "instrument_type":    self.instrument_type.value,
            "asset_class":        self.asset_class.value,
            "currency":           self.currency,
            "country":            self.country,
            "sector":             self.sector,
            "available_entities": list(self.available_entities),
            "hard_dollar":        self.hard_dollar,
            "maturity_date":      self.maturity_date,
            "coupon_rate":        self.coupon_rate,
            "ytm":                self.ytm,
            "duration":           self.duration,
            "liquidity_score":    self.liquidity_score,
            "min_piece":          self.min_piece,
            "rating":             self.rating,
            "notes":              list(self.notes),
        }

    # ── helpers ──────────────────────────────────────────────────────────────

    def is_available_at(self, entity: str) -> bool:
        """Case-insensitive entity lookup."""
        needle = entity.strip().lower()
        return any(e.strip().lower() == needle for e in self.available_entities)

    @property
    def is_usd(self) -> bool:
        return self.currency.strip().upper() == "USD"

    @property
    def is_argentina(self) -> bool:
        return self.country.strip().upper() in {"AR", "ARG", "ARGENTINA"}


# ─────────────────────────────────────────────────────────────────────────────
# InstrumentUniverse
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class InstrumentUniverse:
    """Ordered collection of FinancialInstruments with chainable filter methods."""

    instruments: list[FinancialInstrument]

    def __post_init__(self) -> None:
        if not isinstance(self.instruments, list):
            raise TypeError("instruments must be a list[FinancialInstrument].")

        tickers = [i.ticker for i in self.instruments]
        seen: set[str] = set()
        duplicates: set[str] = set()
        for t in tickers:
            if t in seen:
                duplicates.add(t)
            seen.add(t)
        if duplicates:
            raise ValueError(
                f"InstrumentUniverse: duplicate tickers found: {sorted(duplicates)}"
            )

    def __len__(self) -> int:
        return len(self.instruments)

    @property
    def tickers(self) -> list[str]:
        return [i.ticker for i in self.instruments]

    def to_dict(self) -> dict[str, Any]:
        return {"instruments": [i.to_dict() for i in self.instruments]}

    # ── filters (all preserve insertion order) ───────────────────────────────

    def filter_by_entity(self, entity: str) -> "InstrumentUniverse":
        return InstrumentUniverse(
            instruments=[i for i in self.instruments if i.is_available_at(entity)]
        )

    def filter_by_currency(self, currency: str) -> "InstrumentUniverse":
        upper = currency.strip().upper()
        return InstrumentUniverse(
            instruments=[
                i for i in self.instruments
                if i.currency.strip().upper() == upper
            ]
        )

    def filter_by_country(self, country: str) -> "InstrumentUniverse":
        upper = country.strip().upper()
        return InstrumentUniverse(
            instruments=[
                i for i in self.instruments
                if i.country.strip().upper() == upper
            ]
        )

    def filter_by_instrument_type(
        self, types: list[InstrumentType]
    ) -> "InstrumentUniverse":
        type_set = set(types)
        return InstrumentUniverse(
            instruments=[i for i in self.instruments if i.instrument_type in type_set]
        )

    def filter_hard_dollar_only(self) -> "InstrumentUniverse":
        return InstrumentUniverse(
            instruments=[i for i in self.instruments if i.hard_dollar]
        )

    def filter_min_liquidity(self, min_liquidity: float) -> "InstrumentUniverse":
        return InstrumentUniverse(
            instruments=[
                i for i in self.instruments if i.liquidity_score >= min_liquidity
            ]
        )
