"""
CSVInstrumentUniverseProvider — load an InstrumentUniverse from a CSV file.

Expected CSV columns
--------------------
Required:
    ticker, name, issuer, instrument_type, asset_class, currency, country,
    sector, available_entities, hard_dollar, liquidity_score

Optional:
    maturity_date, coupon_rate, ytm, duration, min_piece, rating, notes

Parsing rules
-------------
- instrument_type / asset_class: case-insensitive enum name lookup.
- available_entities: semicolon-separated list of strings.
- hard_dollar: true/false/1/0/yes/no (case-insensitive).
- notes: semicolon-separated list of strings.
- Optional float columns: empty string → None.
- liquidity_score: required float.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from risk_first_advisory.universe_layer.instruments import (
    AssetClass,
    FinancialInstrument,
    InstrumentType,
    InstrumentUniverse,
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_COLUMNS: frozenset[str] = frozenset({
    "ticker",
    "name",
    "issuer",
    "instrument_type",
    "asset_class",
    "currency",
    "country",
    "sector",
    "available_entities",
    "hard_dollar",
    "liquidity_score",
})

_OPTIONAL_FLOAT_COLUMNS: tuple[str, ...] = (
    "coupon_rate",
    "ytm",
    "duration",
    "min_piece",
)

# ─────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_bool(value: str, field_name: str, line: int) -> bool:
    v = value.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    raise ValueError(
        f"Line {line}: cannot parse {field_name!r} as bool: {value!r}. "
        "Accepted values: true/false/1/0/yes/no."
    )


def _parse_optional_float(value: str, field_name: str, line: int) -> float | None:
    v = value.strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        raise ValueError(
            f"Line {line}: cannot parse {field_name!r} as float: {value!r}."
        ) from None


def _parse_instrument_type(value: str, line: int) -> InstrumentType:
    try:
        return InstrumentType[value.strip().upper()]
    except KeyError:
        valid = sorted(m.name for m in InstrumentType)
        raise ValueError(
            f"Line {line}: invalid instrument_type {value!r}. Valid values: {valid}."
        ) from None


def _parse_asset_class(value: str, line: int) -> AssetClass:
    try:
        return AssetClass[value.strip().upper()]
    except KeyError:
        valid = sorted(m.name for m in AssetClass)
        raise ValueError(
            f"Line {line}: invalid asset_class {value!r}. Valid values: {valid}."
        ) from None


def _parse_semicolon_list(value: str) -> list[str]:
    """Split a semicolon-separated string into a stripped list, ignoring blanks."""
    if not value.strip():
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Provider
# ─────────────────────────────────────────────────────────────────────────────


class CSVInstrumentUniverseProvider:
    """Load an InstrumentUniverse from a CSV file."""

    def __init__(self, csv_path: str | Path) -> None:
        self._path = Path(csv_path)

    def load(self) -> InstrumentUniverse:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Instrument universe CSV not found: {self._path}"
            )

        with self._path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)

            # Validate required columns
            headers: set[str] = set(reader.fieldnames or [])
            missing = _REQUIRED_COLUMNS - headers
            if missing:
                raise ValueError(
                    f"CSV is missing required columns: {sorted(missing)}"
                )

            instruments: list[FinancialInstrument] = []

            # Line 1 is the header; data rows start at line 2
            for line_num, row in enumerate(reader, start=2):
                ticker = row.get("ticker", "").strip()
                label = f"ticker={ticker!r}" if ticker else f"line {line_num}"
                try:
                    inst = _build_instrument(row, line_num)
                except ValueError as exc:
                    msg = str(exc)
                    if msg.startswith(f"Line {line_num}"):
                        raise
                    raise ValueError(f"Line {line_num} ({label}): {exc}") from exc
                except TypeError as exc:
                    raise ValueError(
                        f"Line {line_num} ({label}): {exc}"
                    ) from exc

                instruments.append(inst)

        return InstrumentUniverse(instruments=instruments)


# ─────────────────────────────────────────────────────────────────────────────
# Row builder (separated for testability)
# ─────────────────────────────────────────────────────────────────────────────


def _build_instrument(row: dict[str, Any], line_num: int) -> FinancialInstrument:
    """Construct a FinancialInstrument from a CSV DictReader row."""

    # liquidity_score is required
    liq_raw = row.get("liquidity_score", "").strip()
    try:
        liquidity_score = float(liq_raw)
    except (ValueError, TypeError):
        raise ValueError(
            f"Line {line_num}: cannot parse 'liquidity_score' as float: {liq_raw!r}."
        ) from None

    # Optional floats
    optional_floats: dict[str, float | None] = {
        col: _parse_optional_float(row.get(col, ""), col, line_num)
        for col in _OPTIONAL_FLOAT_COLUMNS
    }

    return FinancialInstrument(
        ticker=row.get("ticker", "").strip(),
        name=row.get("name", "").strip(),
        issuer=row.get("issuer", "").strip(),
        instrument_type=_parse_instrument_type(
            row.get("instrument_type", ""), line_num
        ),
        asset_class=_parse_asset_class(row.get("asset_class", ""), line_num),
        currency=row.get("currency", "").strip(),
        country=row.get("country", "").strip(),
        sector=row.get("sector", "").strip(),
        available_entities=_parse_semicolon_list(row.get("available_entities", "")),
        hard_dollar=_parse_bool(row.get("hard_dollar", ""), "hard_dollar", line_num),
        liquidity_score=liquidity_score,
        maturity_date=row.get("maturity_date", "").strip() or None,
        coupon_rate=optional_floats["coupon_rate"],
        ytm=optional_floats["ytm"],
        duration=optional_floats["duration"],
        min_piece=optional_floats["min_piece"],
        rating=row.get("rating", "").strip() or None,
        notes=_parse_semicolon_list(row.get("notes", "")),
    )
