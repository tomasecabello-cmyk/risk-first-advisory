"""
PreferenceFilterEngine — applies structured AI-extracted preferences to InstrumentUniverse.

Deterministic, zero AI calls. Takes an InstrumentUniverse and a preferences dict
(as returned by OpenAIProfileClient.extract_investment_preferences) and returns a
PreferenceFilterResult with:
    - eligible_universe : InstrumentUniverse of instruments passing all active filters
    - exclusions        : list[InstrumentExclusion] with per-ticker reasons
    - applied_filters   : human-readable list of filters that were evaluated
    - warnings          : advisory messages (prefer_* hints, missing data, unknown keys)

Design constraints:
    - Deterministic and pure — same inputs → same output, no side effects.
    - Preserves original universe order in both eligible_universe and exclusions.
    - Unknown preference keys are ignored with a warning, never raise.
    - Only allowed_instrument_types / min_liquidity_score / max_maturity_year raise
      ValueError on invalid values (they reach our code before the AI validated them).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from risk_first_advisory.universe_layer.instruments import (
    InstrumentType,
    InstrumentUniverse,
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_VALID_INSTRUMENT_TYPE_VALUES: frozenset[str] = frozenset(
    t.value for t in InstrumentType
)

# Keys that come from the AI response schema — recognised but not all are filters.
_KNOWN_PREFERENCE_KEYS: frozenset[str] = frozenset({
    "allowed_instrument_types",
    "excluded_instrument_types",
    "currency",
    "country",
    "entity",
    "hard_dollar_only",
    "avoid_sectors",
    "prefer_sectors",
    "avoid_issuers",
    "prefer_issuers",
    "min_liquidity_score",
    "max_maturity_year",
    # AI metadata — known but not used as filters
    "hard_constraints",
    "soft_preferences",
    "unparsed_preferences",
    "confidence",
    "advisor_notes",
})

# Country alias groups: any member of a group is considered the same country.
_COUNTRY_ALIAS_GROUPS: list[frozenset[str]] = [
    frozenset({"AR", "ARG", "ARGENTINA"}),
    frozenset({"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}),
    frozenset({"BR", "BRA", "BRAZIL", "BRASIL"}),
    frozenset({"MX", "MEX", "MEXICO", "MÉXICO"}),
    frozenset({"CL", "CHL", "CHILE"}),
    frozenset({"CO", "COL", "COLOMBIA"}),
    frozenset({"PE", "PER", "PERU", "PERÚ"}),
]


# ─────────────────────────────────────────────────────────────────────────────
# Country normalisation helper
# ─────────────────────────────────────────────────────────────────────────────

def _country_matches(pref_country: str, inst_country: str) -> bool:
    """
    Return True if pref_country and inst_country refer to the same country.

    Case-insensitive. Also resolves common ISO-2, ISO-3, and full-name aliases
    (e.g. "Argentina" == "AR" == "ARG").
    """
    a = pref_country.strip().upper()
    b = inst_country.strip().upper()
    if a == b:
        return True
    for group in _COUNTRY_ALIAS_GROUPS:
        if a in group and b in group:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class InstrumentExclusion:
    """Records why a specific instrument was excluded from the eligible universe."""

    ticker: str
    reasons: list[str]

    def __post_init__(self) -> None:
        if not isinstance(self.ticker, str) or not self.ticker.strip():
            raise ValueError(
                "InstrumentExclusion.ticker must be a non-empty string."
            )
        if not isinstance(self.reasons, list) or not self.reasons:
            raise ValueError(
                "InstrumentExclusion.reasons must be a non-empty list[str]."
            )

    def to_dict(self) -> dict[str, Any]:
        return {"ticker": self.ticker, "reasons": list(self.reasons)}


@dataclass
class PreferenceFilterResult:
    """Output of PreferenceFilterEngine.apply()."""

    eligible_universe: InstrumentUniverse
    exclusions:        list[InstrumentExclusion]
    applied_filters:   list[str]
    warnings:          list[str]

    def __post_init__(self) -> None:
        if not isinstance(self.eligible_universe, InstrumentUniverse):
            raise TypeError(
                "eligible_universe must be an InstrumentUniverse instance."
            )
        if not isinstance(self.exclusions, list):
            raise TypeError("exclusions must be a list.")
        if not isinstance(self.applied_filters, list):
            raise TypeError("applied_filters must be a list.")
        if not isinstance(self.warnings, list):
            raise TypeError("warnings must be a list.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible_universe": self.eligible_universe.to_dict(),
            "exclusions":        [e.to_dict() for e in self.exclusions],
            "applied_filters":   list(self.applied_filters),
            "warnings":          list(self.warnings),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


class PreferenceFilterEngine:
    """
    Applies structured investment preferences to an InstrumentUniverse.

    All filters are deterministic and independent: each preference key is
    evaluated over the full original universe, and an instrument is excluded
    if it fails *any* active filter. Multiple failure reasons are accumulated
    per ticker.

    Usage::

        engine = PreferenceFilterEngine()
        result = engine.apply(universe, preferences)
        eligible = result.eligible_universe
    """

    def apply(
        self,
        universe: InstrumentUniverse,
        preferences: dict[str, Any],
    ) -> PreferenceFilterResult:
        """
        Apply preferences to universe and return a PreferenceFilterResult.

        Args:
            universe    : InstrumentUniverse to filter.
            preferences : dict with the same schema as AIInvestmentPreferencesResponse.
                          Unknown keys are tolerated with a warning.

        Returns:
            PreferenceFilterResult with eligible instruments, exclusions, filters applied,
            and advisory warnings.

        Raises:
            ValueError: if preferences contains structurally invalid values
                        (invalid instrument type, out-of-range liquidity, bad year).
        """
        # ── 0. Validate before touching the universe ──────────────────────────
        self._validate_preferences(preferences)

        warnings: list[str] = []
        applied_filters: list[str] = []

        # ── 1. Warn on unknown keys ───────────────────────────────────────────
        for key in preferences:
            if key not in _KNOWN_PREFERENCE_KEYS:
                warnings.append(f"unknown_preference_key:{key}")

        # ── 2. prefer_* — not enforced, generate warnings ────────────────────
        if preferences.get("prefer_sectors"):
            warnings.append(
                "prefer_sectors is not enforced in M1 preference filter"
            )
        if preferences.get("prefer_issuers"):
            warnings.append(
                "prefer_issuers is not enforced in M1 preference filter"
            )

        # Accumulate exclusion reasons per ticker (preserving first-seen order).
        exclusion_reasons: dict[str, list[str]] = {}

        def _exclude(ticker: str, reason: str) -> None:
            if ticker not in exclusion_reasons:
                exclusion_reasons[ticker] = []
            exclusion_reasons[ticker].append(reason)

        # ── 3. entity ─────────────────────────────────────────────────────────
        entity: str | None = preferences.get("entity")
        if entity:
            applied_filters.append(f"entity:{entity}")
            for inst in universe.instruments:
                if not inst.is_available_at(entity):
                    _exclude(inst.ticker, f"not_available_at_entity:{entity}")

        # ── 4. allowed_instrument_types ───────────────────────────────────────
        allowed_types: list[str] = preferences.get("allowed_instrument_types") or []
        if allowed_types:
            allowed_set = {t.upper() for t in allowed_types}
            applied_filters.append(f"allowed_instrument_types:{sorted(allowed_set)}")
            for inst in universe.instruments:
                if inst.instrument_type.value not in allowed_set:
                    _exclude(
                        inst.ticker,
                        f"instrument_type_not_allowed:{inst.instrument_type.value}",
                    )

        # ── 5. excluded_instrument_types ──────────────────────────────────────
        excluded_types: list[str] = preferences.get("excluded_instrument_types") or []
        if excluded_types:
            excluded_set = {t.upper() for t in excluded_types}
            applied_filters.append(
                f"excluded_instrument_types:{sorted(excluded_set)}"
            )
            for inst in universe.instruments:
                if inst.instrument_type.value in excluded_set:
                    _exclude(
                        inst.ticker,
                        f"instrument_type_excluded:{inst.instrument_type.value}",
                    )

        # ── 6. currency ───────────────────────────────────────────────────────
        currency: str | None = preferences.get("currency")
        if currency:
            currency_upper = currency.strip().upper()
            applied_filters.append(f"currency:{currency}")
            for inst in universe.instruments:
                if inst.currency.strip().upper() != currency_upper:
                    _exclude(inst.ticker, f"currency_mismatch:{inst.currency}")

        # ── 7. country ────────────────────────────────────────────────────────
        country: str | None = preferences.get("country")
        if country:
            applied_filters.append(f"country:{country}")
            for inst in universe.instruments:
                if not _country_matches(country, inst.country):
                    _exclude(inst.ticker, f"country_mismatch:{inst.country}")

        # ── 8. hard_dollar_only ───────────────────────────────────────────────
        hard_dollar_only = preferences.get("hard_dollar_only")
        if hard_dollar_only is True:
            applied_filters.append("hard_dollar_only:true")
            for inst in universe.instruments:
                if not inst.hard_dollar:
                    _exclude(inst.ticker, "not_hard_dollar")

        # ── 9. avoid_sectors ──────────────────────────────────────────────────
        avoid_sectors: list[str] = preferences.get("avoid_sectors") or []
        if avoid_sectors:
            avoid_sectors_lower = {s.strip().lower() for s in avoid_sectors}
            applied_filters.append(f"avoid_sectors:{sorted(avoid_sectors)}")
            for inst in universe.instruments:
                if inst.sector.strip().lower() in avoid_sectors_lower:
                    _exclude(inst.ticker, f"sector_avoided:{inst.sector}")

        # ── 10. avoid_issuers ─────────────────────────────────────────────────
        avoid_issuers: list[str] = preferences.get("avoid_issuers") or []
        if avoid_issuers:
            avoid_issuers_lower = {i.strip().lower() for i in avoid_issuers}
            applied_filters.append(f"avoid_issuers:{sorted(avoid_issuers)}")
            for inst in universe.instruments:
                if inst.issuer.strip().lower() in avoid_issuers_lower:
                    _exclude(inst.ticker, f"issuer_avoided:{inst.issuer}")

        # ── 11. min_liquidity_score ───────────────────────────────────────────
        min_liq: float | None = preferences.get("min_liquidity_score")
        if min_liq is not None:
            applied_filters.append(f"min_liquidity_score:{min_liq}")
            for inst in universe.instruments:
                if inst.liquidity_score < min_liq:
                    _exclude(
                        inst.ticker, f"liquidity_below_min:{inst.liquidity_score}"
                    )

        # ── 12. max_maturity_year ─────────────────────────────────────────────
        max_year: int | None = preferences.get("max_maturity_year")
        if max_year is not None:
            applied_filters.append(f"max_maturity_year:{max_year}")
            for inst in universe.instruments:
                if inst.maturity_date is None:
                    warnings.append(f"maturity_date_missing_for:{inst.ticker}")
                else:
                    try:
                        inst_year = int(inst.maturity_date.split("-")[0])
                    except (ValueError, IndexError):
                        warnings.append(
                            f"maturity_date_unparseable_for:{inst.ticker}"
                        )
                        continue
                    if inst_year > max_year:
                        _exclude(
                            inst.ticker, f"maturity_after_max_year:{inst_year}"
                        )

        # ── Build result — preserve original universe order ───────────────────
        excluded_tickers = set(exclusion_reasons.keys())
        eligible = InstrumentUniverse(
            instruments=[
                i for i in universe.instruments if i.ticker not in excluded_tickers
            ]
        )
        # Exclusions in the order their ticker first appears in universe.instruments
        ticker_order = {inst.ticker: idx for idx, inst in enumerate(universe.instruments)}
        exclusions = [
            InstrumentExclusion(ticker=t, reasons=r)
            for t, r in sorted(
                exclusion_reasons.items(), key=lambda kv: ticker_order.get(kv[0], 9999)
            )
        ]

        return PreferenceFilterResult(
            eligible_universe=eligible,
            exclusions=exclusions,
            applied_filters=applied_filters,
            warnings=warnings,
        )

    # ── Input validation ──────────────────────────────────────────────────────

    @staticmethod
    def _validate_preferences(preferences: dict[str, Any]) -> None:
        """
        Raise ValueError on structurally invalid preference values.

        Does NOT raise on unknown keys — those get warnings instead.
        """
        # allowed / excluded instrument types
        for key in ("allowed_instrument_types", "excluded_instrument_types"):
            val = preferences.get(key)
            if val:
                for item in val:
                    if str(item).upper() not in _VALID_INSTRUMENT_TYPE_VALUES:
                        raise ValueError(
                            f"preferences['{key}'] contains invalid instrument type: "
                            f"{item!r}. Valid values: {sorted(_VALID_INSTRUMENT_TYPE_VALUES)}"
                        )

        # min_liquidity_score
        min_liq = preferences.get("min_liquidity_score")
        if min_liq is not None:
            try:
                liq_f = float(min_liq)
            except (TypeError, ValueError):
                raise ValueError(
                    f"preferences['min_liquidity_score'] must be numeric, got {min_liq!r}."
                )
            if not 0.0 <= liq_f <= 1.0:
                raise ValueError(
                    f"preferences['min_liquidity_score'] must be in [0.0, 1.0], "
                    f"got {min_liq!r}."
                )

        # max_maturity_year
        max_year = preferences.get("max_maturity_year")
        if max_year is not None:
            if not isinstance(max_year, int) or max_year < 1900:
                raise ValueError(
                    f"preferences['max_maturity_year'] must be an int >= 1900, "
                    f"got {max_year!r}."
                )
