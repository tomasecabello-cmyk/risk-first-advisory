"""
Unit tests for PreferenceFilterEngine, InstrumentExclusion, PreferenceFilterResult.

Coverage:
    - InstrumentExclusion validation and serialisation
    - PreferenceFilterResult validation and serialisation
    - PreferenceFilterEngine: each filter type independently
    - Multiple exclusion reasons accumulated per instrument
    - Chained filters (entity + type + currency + country + hard_dollar + avoid_sectors)
    - prefer_* keys produce warnings, not exclusions
    - Unknown preference keys produce warnings, not errors
    - Order preservation for both eligible_universe and exclusions
    - _validate_preferences raises ValueError on invalid values
    - max_maturity_year: missing-maturity warning
    - country alias matching (Argentina / AR / ARG)
"""

from __future__ import annotations

import pathlib
import pytest

from risk_first_advisory.universe_layer.instruments import (
    AssetClass,
    FinancialInstrument,
    InstrumentType,
    InstrumentUniverse,
)
from risk_first_advisory.universe_layer.preference_filter import (
    InstrumentExclusion,
    PreferenceFilterEngine,
    PreferenceFilterResult,
)
from risk_first_advisory.universe_layer.csv_provider import (
    CSVInstrumentUniverseProvider,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers — instrument builders
# ─────────────────────────────────────────────────────────────────────────────

_FIXTURE_CSV = (
    pathlib.Path(__file__).parent.parent
    / "fixtures"
    / "universe"
    / "sample_instrument_universe.csv"
)


def _inst(
    ticker: str,
    instrument_type: InstrumentType = InstrumentType.ETF,
    currency: str = "USD",
    country: str = "US",
    sector: str = "Equity",
    entities: list[str] | None = None,
    hard_dollar: bool = False,
    liquidity_score: float = 0.80,
    maturity_date: str | None = None,
    issuer: str = "Issuer Corp",
    asset_class: AssetClass = AssetClass.EQUITY,
) -> FinancialInstrument:
    return FinancialInstrument(
        ticker=ticker,
        name=f"{ticker} Name",
        issuer=issuer,
        instrument_type=instrument_type,
        asset_class=asset_class,
        currency=currency,
        country=country,
        sector=sector,
        available_entities=entities if entities is not None else ["Balanz", "PPI"],
        hard_dollar=hard_dollar,
        liquidity_score=liquidity_score,
        maturity_date=maturity_date,
    )


def _universe(*instruments: FinancialInstrument) -> InstrumentUniverse:
    return InstrumentUniverse(instruments=list(instruments))


@pytest.fixture()
def engine() -> PreferenceFilterEngine:
    return PreferenceFilterEngine()


@pytest.fixture(scope="module")
def full_universe() -> InstrumentUniverse:
    """Load the 12-instrument sample CSV fixture."""
    return CSVInstrumentUniverseProvider(_FIXTURE_CSV).load()


# ─────────────────────────────────────────────────────────────────────────────
# InstrumentExclusion
# ─────────────────────────────────────────────────────────────────────────────


class TestInstrumentExclusion:
    def test_valid_construction(self) -> None:
        exc = InstrumentExclusion(ticker="SPY", reasons=["reason_a", "reason_b"])
        assert exc.ticker == "SPY"
        assert exc.reasons == ["reason_a", "reason_b"]

    def test_empty_ticker_raises(self) -> None:
        with pytest.raises(ValueError, match="ticker"):
            InstrumentExclusion(ticker="   ", reasons=["r"])

    def test_non_string_ticker_raises(self) -> None:
        with pytest.raises(ValueError, match="ticker"):
            InstrumentExclusion(ticker=None, reasons=["r"])  # type: ignore[arg-type]

    def test_empty_reasons_list_raises(self) -> None:
        with pytest.raises(ValueError, match="reasons"):
            InstrumentExclusion(ticker="SPY", reasons=[])

    def test_non_list_reasons_raises(self) -> None:
        with pytest.raises(ValueError, match="reasons"):
            InstrumentExclusion(ticker="SPY", reasons="reason")  # type: ignore[arg-type]

    def test_to_dict_structure(self) -> None:
        exc = InstrumentExclusion(ticker="SPY", reasons=["r1", "r2"])
        d = exc.to_dict()
        assert d == {"ticker": "SPY", "reasons": ["r1", "r2"]}

    def test_to_dict_returns_copy(self) -> None:
        exc = InstrumentExclusion(ticker="SPY", reasons=["r1"])
        d = exc.to_dict()
        d["reasons"].append("mutated")
        assert exc.reasons == ["r1"]


# ─────────────────────────────────────────────────────────────────────────────
# PreferenceFilterResult
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterResult:
    def test_valid_construction(self) -> None:
        universe = _universe(_inst("A"))
        result = PreferenceFilterResult(
            eligible_universe=universe,
            exclusions=[],
            applied_filters=["currency:USD"],
            warnings=[],
        )
        assert len(result.eligible_universe) == 1
        assert result.applied_filters == ["currency:USD"]

    def test_wrong_universe_type_raises(self) -> None:
        with pytest.raises(TypeError, match="eligible_universe"):
            PreferenceFilterResult(
                eligible_universe={"not": "a universe"},  # type: ignore[arg-type]
                exclusions=[],
                applied_filters=[],
                warnings=[],
            )

    def test_wrong_exclusions_type_raises(self) -> None:
        with pytest.raises(TypeError, match="exclusions"):
            PreferenceFilterResult(
                eligible_universe=_universe(_inst("A")),
                exclusions="bad",  # type: ignore[arg-type]
                applied_filters=[],
                warnings=[],
            )

    def test_wrong_applied_filters_type_raises(self) -> None:
        with pytest.raises(TypeError, match="applied_filters"):
            PreferenceFilterResult(
                eligible_universe=_universe(_inst("A")),
                exclusions=[],
                applied_filters=None,  # type: ignore[arg-type]
                warnings=[],
            )

    def test_wrong_warnings_type_raises(self) -> None:
        with pytest.raises(TypeError, match="warnings"):
            PreferenceFilterResult(
                eligible_universe=_universe(_inst("A")),
                exclusions=[],
                applied_filters=[],
                warnings=None,  # type: ignore[arg-type]
            )

    def test_to_dict_structure(self) -> None:
        a = _inst("A")
        exc = InstrumentExclusion(ticker="B", reasons=["r"])
        result = PreferenceFilterResult(
            eligible_universe=_universe(a),
            exclusions=[exc],
            applied_filters=["entity:Balanz"],
            warnings=["warn1"],
        )
        d = result.to_dict()
        assert "eligible_universe" in d
        assert "instruments" in d["eligible_universe"]
        assert d["exclusions"] == [{"ticker": "B", "reasons": ["r"]}]
        assert d["applied_filters"] == ["entity:Balanz"]
        assert d["warnings"] == ["warn1"]


# ─────────────────────────────────────────────────────────────────────────────
# Engine — empty preferences (pass-through)
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineEmptyPreferences:
    def test_all_instruments_eligible(self, engine: PreferenceFilterEngine) -> None:
        uni = _universe(_inst("A"), _inst("B"), _inst("C"))
        result = engine.apply(uni, {})
        assert result.eligible_universe.tickers == ["A", "B", "C"]

    def test_no_exclusions(self, engine: PreferenceFilterEngine) -> None:
        uni = _universe(_inst("A"), _inst("B"))
        result = engine.apply(uni, {})
        assert result.exclusions == []

    def test_no_applied_filters(self, engine: PreferenceFilterEngine) -> None:
        uni = _universe(_inst("A"))
        result = engine.apply(uni, {})
        assert result.applied_filters == []

    def test_no_warnings(self, engine: PreferenceFilterEngine) -> None:
        uni = _universe(_inst("A"))
        result = engine.apply(uni, {})
        assert result.warnings == []


# ─────────────────────────────────────────────────────────────────────────────
# Engine — entity filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineEntity:
    def test_excludes_instruments_not_at_entity(
        self, engine: PreferenceFilterEngine
    ) -> None:
        a = _inst("A", entities=["Balanz", "PPI"])
        b = _inst("B", entities=["PPI"])
        c = _inst("C", entities=["Balanz"])
        result = engine.apply(_universe(a, b, c), {"entity": "Balanz"})
        assert result.eligible_universe.tickers == ["A", "C"]
        assert len(result.exclusions) == 1
        assert result.exclusions[0].ticker == "B"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        b = _inst("B", entities=["PPI"])
        result = engine.apply(_universe(b), {"entity": "Balanz"})
        assert result.exclusions[0].reasons == ["not_available_at_entity:Balanz"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(_universe(_inst("A")), {"entity": "Balanz"})
        assert "entity:Balanz" in result.applied_filters

    def test_entity_case_insensitive(self, engine: PreferenceFilterEngine) -> None:
        a = _inst("A", entities=["balanz"])
        result = engine.apply(_universe(a), {"entity": "BALANZ"})
        assert result.eligible_universe.tickers == ["A"]

    def test_entity_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        # GLD is only at PPI;Cocos — not Balanz
        # MELI30 is only at PPI;Cocos — not Balanz
        # BONO0 is only at PPI — not Balanz
        result = engine.apply(full_universe, {"entity": "Balanz"})
        excluded_tickers = {e.ticker for e in result.exclusions}
        assert "GLD" in excluded_tickers
        assert "MELI30" in excluded_tickers
        assert "BONO0" in excluded_tickers
        assert "SPY" not in excluded_tickers  # SPY is at Balanz


# ─────────────────────────────────────────────────────────────────────────────
# Engine — allowed_instrument_types filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineAllowedInstrumentTypes:
    def test_excludes_wrong_types(self, engine: PreferenceFilterEngine) -> None:
        etf = _inst("E", instrument_type=InstrumentType.ETF)
        cb = _inst("C", instrument_type=InstrumentType.CORPORATE_BOND)
        result = engine.apply(
            _universe(etf, cb), {"allowed_instrument_types": ["CORPORATE_BOND"]}
        )
        assert result.eligible_universe.tickers == ["C"]
        assert result.exclusions[0].ticker == "E"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        etf = _inst("E", instrument_type=InstrumentType.ETF)
        result = engine.apply(
            _universe(etf), {"allowed_instrument_types": ["CORPORATE_BOND"]}
        )
        assert result.exclusions[0].reasons == ["instrument_type_not_allowed:ETF"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(
            _universe(_inst("A")), {"allowed_instrument_types": ["ETF"]}
        )
        label = result.applied_filters[0]
        assert "allowed_instrument_types" in label
        assert "ETF" in label

    def test_case_insensitive_allowed_types(
        self, engine: PreferenceFilterEngine
    ) -> None:
        etf = _inst("E", instrument_type=InstrumentType.ETF)
        result = engine.apply(_universe(etf), {"allowed_instrument_types": ["etf"]})
        # ETF matches lowercase input
        assert result.eligible_universe.tickers == ["E"]
        assert result.exclusions == []

    def test_empty_list_no_filter(self, engine: PreferenceFilterEngine) -> None:
        etf = _inst("E", instrument_type=InstrumentType.ETF)
        result = engine.apply(_universe(etf), {"allowed_instrument_types": []})
        assert result.eligible_universe.tickers == ["E"]


# ─────────────────────────────────────────────────────────────────────────────
# Engine — excluded_instrument_types filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineExcludedInstrumentTypes:
    def test_excludes_listed_types(self, engine: PreferenceFilterEngine) -> None:
        etf = _inst("E", instrument_type=InstrumentType.ETF)
        cb = _inst("C", instrument_type=InstrumentType.CORPORATE_BOND)
        result = engine.apply(
            _universe(etf, cb), {"excluded_instrument_types": ["ETF"]}
        )
        assert result.eligible_universe.tickers == ["C"]
        assert result.exclusions[0].ticker == "E"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        etf = _inst("E", instrument_type=InstrumentType.ETF)
        result = engine.apply(
            _universe(etf), {"excluded_instrument_types": ["ETF"]}
        )
        assert result.exclusions[0].reasons == ["instrument_type_excluded:ETF"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(
            _universe(_inst("A")), {"excluded_instrument_types": ["ETF"]}
        )
        assert any("excluded_instrument_types" in f for f in result.applied_filters)

    def test_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"excluded_instrument_types": ["ETF"]})
        excluded = {e.ticker for e in result.exclusions}
        assert excluded == {"SPY", "VTI", "GLD"}


# ─────────────────────────────────────────────────────────────────────────────
# Engine — currency filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineCurrency:
    def test_excludes_wrong_currency(self, engine: PreferenceFilterEngine) -> None:
        usd = _inst("U", currency="USD")
        ars = _inst("A", currency="ARS")
        result = engine.apply(_universe(usd, ars), {"currency": "USD"})
        assert result.eligible_universe.tickers == ["U"]
        assert result.exclusions[0].ticker == "A"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        ars = _inst("A", currency="ARS")
        result = engine.apply(_universe(ars), {"currency": "USD"})
        assert result.exclusions[0].reasons == ["currency_mismatch:ARS"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(_universe(_inst("A")), {"currency": "USD"})
        assert "currency:USD" in result.applied_filters

    def test_currency_case_insensitive(self, engine: PreferenceFilterEngine) -> None:
        usd = _inst("U", currency="usd")
        result = engine.apply(_universe(usd), {"currency": "USD"})
        assert result.eligible_universe.tickers == ["U"]

    def test_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"currency": "USD"})
        excluded = {e.ticker for e in result.exclusions}
        # FIMA (ARS) and APBR (ARS) should be excluded
        assert "FIMA" in excluded
        assert "APBR" in excluded
        assert "SPY" not in excluded


# ─────────────────────────────────────────────────────────────────────────────
# Engine — country filter (with alias matching)
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineCountry:
    def test_excludes_wrong_country(self, engine: PreferenceFilterEngine) -> None:
        ar = _inst("AR_INST", country="AR")
        us = _inst("US_INST", country="US")
        result = engine.apply(_universe(ar, us), {"country": "AR"})
        assert result.eligible_universe.tickers == ["AR_INST"]
        assert result.exclusions[0].ticker == "US_INST"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        us = _inst("U", country="US")
        result = engine.apply(_universe(us), {"country": "Argentina"})
        assert result.exclusions[0].reasons == ["country_mismatch:US"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(_universe(_inst("A", country="AR")), {"country": "AR"})
        assert "country:AR" in result.applied_filters

    def test_argentina_matches_ar(self, engine: PreferenceFilterEngine) -> None:
        ar = _inst("A", country="AR")
        result = engine.apply(_universe(ar), {"country": "Argentina"})
        assert result.eligible_universe.tickers == ["A"]
        assert result.exclusions == []

    def test_argentina_matches_arg(self, engine: PreferenceFilterEngine) -> None:
        arg = _inst("A", country="ARG")
        result = engine.apply(_universe(arg), {"country": "Argentina"})
        assert result.eligible_universe.tickers == ["A"]
        assert result.exclusions == []

    def test_ar_matches_arg(self, engine: PreferenceFilterEngine) -> None:
        arg = _inst("A", country="ARG")
        result = engine.apply(_universe(arg), {"country": "AR"})
        assert result.eligible_universe.tickers == ["A"]
        assert result.exclusions == []

    def test_full_name_case_insensitive(self, engine: PreferenceFilterEngine) -> None:
        ar = _inst("A", country="AR")
        result = engine.apply(_universe(ar), {"country": "argentina"})
        assert result.eligible_universe.tickers == ["A"]

    def test_from_full_fixture_argentina(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"country": "Argentina"})
        excluded = {e.ticker for e in result.exclusions}
        # US instruments excluded
        assert "SPY" in excluded
        assert "VTI" in excluded
        assert "GLD" in excluded
        # AR instruments pass
        assert "YCPDO" not in excluded
        assert "GD30" not in excluded


# ─────────────────────────────────────────────────────────────────────────────
# Engine — hard_dollar_only filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineHardDollar:
    def test_excludes_non_hard_dollar(self, engine: PreferenceFilterEngine) -> None:
        hd = _inst("HD", hard_dollar=True)
        soft = _inst("SD", hard_dollar=False)
        result = engine.apply(_universe(hd, soft), {"hard_dollar_only": True})
        assert result.eligible_universe.tickers == ["HD"]
        assert result.exclusions[0].ticker == "SD"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        soft = _inst("S", hard_dollar=False)
        result = engine.apply(_universe(soft), {"hard_dollar_only": True})
        assert result.exclusions[0].reasons == ["not_hard_dollar"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(_universe(_inst("A")), {"hard_dollar_only": True})
        assert "hard_dollar_only:true" in result.applied_filters

    def test_false_does_not_filter(self, engine: PreferenceFilterEngine) -> None:
        soft = _inst("S", hard_dollar=False)
        result = engine.apply(_universe(soft), {"hard_dollar_only": False})
        assert result.eligible_universe.tickers == ["S"]
        assert result.exclusions == []
        assert result.applied_filters == []

    def test_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"hard_dollar_only": True})
        excluded = {e.ticker for e in result.exclusions}
        # SPY, VTI, GLD, FIMA, APBR are not hard_dollar
        assert {"SPY", "VTI", "GLD", "FIMA", "APBR"}.issubset(excluded)
        # hard_dollar instruments remain
        assert "YCPDO" not in excluded
        assert "GD30" not in excluded


# ─────────────────────────────────────────────────────────────────────────────
# Engine — avoid_sectors filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineAvoidSectors:
    def test_excludes_avoided_sector(self, engine: PreferenceFilterEngine) -> None:
        energy = _inst("E", sector="Energy")
        tech = _inst("T", sector="Technology")
        result = engine.apply(_universe(energy, tech), {"avoid_sectors": ["Energy"]})
        assert result.eligible_universe.tickers == ["T"]
        assert result.exclusions[0].ticker == "E"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        energy = _inst("E", sector="Energy")
        result = engine.apply(_universe(energy), {"avoid_sectors": ["Energy"]})
        assert result.exclusions[0].reasons == ["sector_avoided:Energy"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(_universe(_inst("A")), {"avoid_sectors": ["Energy"]})
        assert any("avoid_sectors" in f for f in result.applied_filters)

    def test_case_insensitive_sector(self, engine: PreferenceFilterEngine) -> None:
        energy = _inst("E", sector="Energy")
        result = engine.apply(_universe(energy), {"avoid_sectors": ["energy"]})
        assert result.exclusions[0].ticker == "E"

    def test_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"avoid_sectors": ["Energy"]})
        excluded = {e.ticker for e in result.exclusions}
        # YCPDO (Energy), PAMP27 (Energy), APBR (Energy)
        assert "YCPDO" in excluded
        assert "PAMP27" in excluded
        assert "APBR" in excluded
        assert "GALI28" not in excluded  # Financials


# ─────────────────────────────────────────────────────────────────────────────
# Engine — avoid_issuers filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineAvoidIssuers:
    def test_excludes_avoided_issuer(self, engine: PreferenceFilterEngine) -> None:
        ypf = _inst("YCPDO", issuer="YPF")
        other = _inst("OTHER", issuer="Galicia")
        result = engine.apply(_universe(ypf, other), {"avoid_issuers": ["YPF"]})
        assert result.eligible_universe.tickers == ["OTHER"]
        assert result.exclusions[0].ticker == "YCPDO"

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        ypf = _inst("Y", issuer="YPF")
        result = engine.apply(_universe(ypf), {"avoid_issuers": ["YPF"]})
        assert result.exclusions[0].reasons == ["issuer_avoided:YPF"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(_universe(_inst("A")), {"avoid_issuers": ["YPF"]})
        assert any("avoid_issuers" in f for f in result.applied_filters)

    def test_case_insensitive_issuer(self, engine: PreferenceFilterEngine) -> None:
        ypf = _inst("Y", issuer="YPF")
        result = engine.apply(_universe(ypf), {"avoid_issuers": ["ypf"]})
        assert result.exclusions[0].ticker == "Y"

    def test_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"avoid_issuers": ["YPF"]})
        excluded = {e.ticker for e in result.exclusions}
        assert "YCPDO" in excluded
        assert "GALI28" not in excluded


# ─────────────────────────────────────────────────────────────────────────────
# Engine — min_liquidity_score filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineMinLiquidity:
    def test_excludes_below_min(self, engine: PreferenceFilterEngine) -> None:
        hi = _inst("H", liquidity_score=0.80)
        lo = _inst("L", liquidity_score=0.50)
        result = engine.apply(_universe(hi, lo), {"min_liquidity_score": 0.70})
        assert result.eligible_universe.tickers == ["H"]
        assert result.exclusions[0].ticker == "L"

    def test_at_exact_boundary_passes(self, engine: PreferenceFilterEngine) -> None:
        exact = _inst("E", liquidity_score=0.70)
        result = engine.apply(_universe(exact), {"min_liquidity_score": 0.70})
        assert result.eligible_universe.tickers == ["E"]
        assert result.exclusions == []

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        lo = _inst("L", liquidity_score=0.50)
        result = engine.apply(_universe(lo), {"min_liquidity_score": 0.70})
        assert result.exclusions[0].reasons == ["liquidity_below_min:0.5"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(
            _universe(_inst("A")), {"min_liquidity_score": 0.70}
        )
        assert any("min_liquidity_score" in f for f in result.applied_filters)

    def test_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"min_liquidity_score": 0.70})
        excluded = {e.ticker for e in result.exclusions}
        # GALI28 (0.65), MELI30 (0.60), APBR (0.60) are below 0.70
        assert "GALI28" in excluded
        assert "MELI30" in excluded
        assert "APBR" in excluded
        assert "YCPDO" not in excluded  # exactly 0.70, passes


# ─────────────────────────────────────────────────────────────────────────────
# Engine — max_maturity_year filter
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineMaxMaturity:
    def test_excludes_after_max_year(self, engine: PreferenceFilterEngine) -> None:
        early = _inst("E", maturity_date="2025-06-01")
        late = _inst("L", maturity_date="2035-01-01")
        result = engine.apply(_universe(early, late), {"max_maturity_year": 2027})
        assert result.eligible_universe.tickers == ["E"]
        assert result.exclusions[0].ticker == "L"

    def test_at_boundary_year_passes(self, engine: PreferenceFilterEngine) -> None:
        exact = _inst("E", maturity_date="2027-12-31")
        result = engine.apply(_universe(exact), {"max_maturity_year": 2027})
        assert result.eligible_universe.tickers == ["E"]
        assert result.exclusions == []

    def test_exclusion_reason_code(self, engine: PreferenceFilterEngine) -> None:
        late = _inst("L", maturity_date="2035-01-01")
        result = engine.apply(_universe(late), {"max_maturity_year": 2027})
        assert result.exclusions[0].reasons == ["maturity_after_max_year:2035"]

    def test_applied_filter_label(self, engine: PreferenceFilterEngine) -> None:
        result = engine.apply(
            _universe(_inst("A", maturity_date="2025-01-01")),
            {"max_maturity_year": 2027},
        )
        assert any("max_maturity_year" in f for f in result.applied_filters)

    def test_missing_maturity_date_generates_warning(
        self, engine: PreferenceFilterEngine
    ) -> None:
        no_date = _inst("N")  # maturity_date=None by default
        result = engine.apply(_universe(no_date), {"max_maturity_year": 2027})
        assert any("maturity_date_missing_for:N" in w for w in result.warnings)

    def test_missing_maturity_not_excluded(
        self, engine: PreferenceFilterEngine
    ) -> None:
        no_date = _inst("N")
        result = engine.apply(_universe(no_date), {"max_maturity_year": 2027})
        # Not excluded — just warned
        assert result.eligible_universe.tickers == ["N"]
        assert result.exclusions == []

    def test_from_full_fixture(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        result = engine.apply(full_universe, {"max_maturity_year": 2028})
        excluded = {e.ticker for e in result.exclusions}
        # MELI30 (2030), GD30 (2030), AL35 (2035) are after 2028
        assert "MELI30" in excluded
        assert "GD30" in excluded
        assert "AL35" in excluded
        assert "YCPDO" not in excluded   # 2026 ≤ 2028
        assert "GALI28" not in excluded  # 2028 ≤ 2028
        assert "PAMP27" not in excluded  # 2027 ≤ 2028


# ─────────────────────────────────────────────────────────────────────────────
# Engine — multiple exclusion reasons per instrument
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineMultipleReasons:
    def test_accumulates_multiple_reasons(
        self, engine: PreferenceFilterEngine
    ) -> None:
        # ARS + Energy sector → two reasons on the same instrument
        inst = _inst("X", currency="ARS", sector="Energy")
        result = engine.apply(
            _universe(inst),
            {"currency": "USD", "avoid_sectors": ["Energy"]},
        )
        assert len(result.exclusions) == 1
        reasons = result.exclusions[0].reasons
        assert any("currency_mismatch" in r for r in reasons)
        assert any("sector_avoided" in r for r in reasons)

    def test_only_one_exclusion_entry_per_ticker(
        self, engine: PreferenceFilterEngine
    ) -> None:
        inst = _inst("X", currency="ARS", sector="Energy")
        result = engine.apply(
            _universe(inst),
            {"currency": "USD", "avoid_sectors": ["Energy"]},
        )
        assert len(result.exclusions) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Engine — order preservation
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineOrderPreservation:
    def test_eligible_preserves_universe_order(
        self, engine: PreferenceFilterEngine
    ) -> None:
        a = _inst("A", currency="USD")
        b = _inst("B", currency="ARS")
        c = _inst("C", currency="USD")
        d = _inst("D", currency="ARS")
        e = _inst("E", currency="USD")
        result = engine.apply(_universe(a, b, c, d, e), {"currency": "USD"})
        assert result.eligible_universe.tickers == ["A", "C", "E"]

    def test_exclusions_follow_universe_order(
        self, engine: PreferenceFilterEngine
    ) -> None:
        a = _inst("A", currency="USD")
        b = _inst("B", currency="ARS")
        c = _inst("C", currency="USD")
        d = _inst("D", currency="ARS")
        result = engine.apply(_universe(a, b, c, d), {"currency": "USD"})
        assert [e.ticker for e in result.exclusions] == ["B", "D"]


# ─────────────────────────────────────────────────────────────────────────────
# Engine — prefer_* warnings (not filters)
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEnginePreferKeys:
    def test_prefer_sectors_generates_warning(
        self, engine: PreferenceFilterEngine
    ) -> None:
        energy = _inst("E", sector="Energy")
        result = engine.apply(
            _universe(energy), {"prefer_sectors": ["Energy"]}
        )
        assert any("prefer_sectors" in w for w in result.warnings)

    def test_prefer_sectors_does_not_exclude(
        self, engine: PreferenceFilterEngine
    ) -> None:
        a = _inst("A", sector="Energy")
        b = _inst("B", sector="Technology")
        result = engine.apply(
            _universe(a, b), {"prefer_sectors": ["Energy"]}
        )
        assert result.eligible_universe.tickers == ["A", "B"]
        assert result.exclusions == []

    def test_prefer_issuers_generates_warning(
        self, engine: PreferenceFilterEngine
    ) -> None:
        result = engine.apply(
            _universe(_inst("A")), {"prefer_issuers": ["YPF"]}
        )
        assert any("prefer_issuers" in w for w in result.warnings)

    def test_prefer_issuers_does_not_exclude(
        self, engine: PreferenceFilterEngine
    ) -> None:
        a = _inst("A", issuer="YPF")
        b = _inst("B", issuer="Galicia")
        result = engine.apply(
            _universe(a, b), {"prefer_issuers": ["YPF"]}
        )
        assert result.eligible_universe.tickers == ["A", "B"]
        assert result.exclusions == []


# ─────────────────────────────────────────────────────────────────────────────
# Engine — unknown preference keys produce warnings
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineUnknownKeys:
    def test_unknown_key_generates_warning(
        self, engine: PreferenceFilterEngine
    ) -> None:
        result = engine.apply(
            _universe(_inst("A")), {"totally_unknown_key": "value"}
        )
        assert any("unknown_preference_key:totally_unknown_key" in w for w in result.warnings)

    def test_unknown_key_does_not_exclude(
        self, engine: PreferenceFilterEngine
    ) -> None:
        result = engine.apply(
            _universe(_inst("A")), {"totally_unknown_key": "value"}
        )
        assert result.eligible_universe.tickers == ["A"]
        assert result.exclusions == []

    def test_multiple_unknown_keys_all_warned(
        self, engine: PreferenceFilterEngine
    ) -> None:
        result = engine.apply(
            _universe(_inst("A")), {"foo": 1, "bar": 2}
        )
        warning_str = " ".join(result.warnings)
        assert "unknown_preference_key:foo" in warning_str
        assert "unknown_preference_key:bar" in warning_str


# ─────────────────────────────────────────────────────────────────────────────
# Engine — _validate_preferences raises ValueError on bad inputs
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineValidation:
    def test_invalid_allowed_instrument_type_raises(
        self, engine: PreferenceFilterEngine
    ) -> None:
        with pytest.raises(ValueError, match="invalid instrument type"):
            engine.apply(
                _universe(_inst("A")),
                {"allowed_instrument_types": ["NOT_A_TYPE"]},
            )

    def test_invalid_excluded_instrument_type_raises(
        self, engine: PreferenceFilterEngine
    ) -> None:
        with pytest.raises(ValueError, match="invalid instrument type"):
            engine.apply(
                _universe(_inst("A")),
                {"excluded_instrument_types": ["RUBBISH"]},
            )

    def test_min_liquidity_above_one_raises(
        self, engine: PreferenceFilterEngine
    ) -> None:
        with pytest.raises(ValueError, match="min_liquidity_score"):
            engine.apply(_universe(_inst("A")), {"min_liquidity_score": 1.5})

    def test_min_liquidity_below_zero_raises(
        self, engine: PreferenceFilterEngine
    ) -> None:
        with pytest.raises(ValueError, match="min_liquidity_score"):
            engine.apply(_universe(_inst("A")), {"min_liquidity_score": -0.1})

    def test_min_liquidity_non_numeric_raises(
        self, engine: PreferenceFilterEngine
    ) -> None:
        with pytest.raises(ValueError, match="min_liquidity_score"):
            engine.apply(_universe(_inst("A")), {"min_liquidity_score": "high"})

    def test_max_maturity_year_not_int_raises(
        self, engine: PreferenceFilterEngine
    ) -> None:
        with pytest.raises(ValueError, match="max_maturity_year"):
            engine.apply(_universe(_inst("A")), {"max_maturity_year": "2030"})

    def test_max_maturity_year_below_1900_raises(
        self, engine: PreferenceFilterEngine
    ) -> None:
        with pytest.raises(ValueError, match="max_maturity_year"):
            engine.apply(_universe(_inst("A")), {"max_maturity_year": 1800})

    def test_validation_happens_before_filtering(
        self, engine: PreferenceFilterEngine
    ) -> None:
        # Even with a valid entity, invalid type should still raise before any filtering
        with pytest.raises(ValueError):
            engine.apply(
                _universe(_inst("A")),
                {"entity": "Balanz", "allowed_instrument_types": ["FAKE"]},
            )


# ─────────────────────────────────────────────────────────────────────────────
# Engine — chained filters (full fixture integration)
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineChained:
    """
    Apply multiple filters simultaneously on the 12-instrument fixture:
        entity=Balanz
        allowed_instrument_types=[CORPORATE_BOND]
        currency=USD
        country=Argentina
        hard_dollar_only=True
        avoid_sectors=[Energy]

    Expected eligible: GALI28 only
    """

    def test_only_gali28_eligible(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        prefs = {
            "entity": "Balanz",
            "allowed_instrument_types": ["CORPORATE_BOND"],
            "currency": "USD",
            "country": "Argentina",
            "hard_dollar_only": True,
            "avoid_sectors": ["Energy"],
        }
        result = engine.apply(full_universe, prefs)
        assert result.eligible_universe.tickers == ["GALI28"]

    def test_all_twelve_instruments_accounted_for(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        prefs = {
            "entity": "Balanz",
            "allowed_instrument_types": ["CORPORATE_BOND"],
            "currency": "USD",
            "country": "Argentina",
            "hard_dollar_only": True,
            "avoid_sectors": ["Energy"],
        }
        result = engine.apply(full_universe, prefs)
        all_tickers = result.eligible_universe.tickers + [
            e.ticker for e in result.exclusions
        ]
        assert set(all_tickers) == set(full_universe.tickers)
        assert len(all_tickers) == len(full_universe.tickers)

    def test_multiple_applied_filters_recorded(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        prefs = {
            "entity": "Balanz",
            "allowed_instrument_types": ["CORPORATE_BOND"],
            "currency": "USD",
            "country": "Argentina",
            "hard_dollar_only": True,
            "avoid_sectors": ["Energy"],
        }
        result = engine.apply(full_universe, prefs)
        filters = result.applied_filters
        assert any("entity" in f for f in filters)
        assert any("allowed_instrument_types" in f for f in filters)
        assert any("currency" in f for f in filters)
        assert any("country" in f for f in filters)
        assert any("hard_dollar_only" in f for f in filters)
        assert any("avoid_sectors" in f for f in filters)

    def test_ycpdo_excluded_for_energy_sector(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        prefs = {
            "entity": "Balanz",
            "allowed_instrument_types": ["CORPORATE_BOND"],
            "currency": "USD",
            "country": "Argentina",
            "hard_dollar_only": True,
            "avoid_sectors": ["Energy"],
        }
        result = engine.apply(full_universe, prefs)
        ycpdo_exc = next(e for e in result.exclusions if e.ticker == "YCPDO")
        assert any("sector_avoided" in r for r in ycpdo_exc.reasons)

    def test_meli30_excluded_for_entity(
        self, engine: PreferenceFilterEngine, full_universe: InstrumentUniverse
    ) -> None:
        prefs = {
            "entity": "Balanz",
            "allowed_instrument_types": ["CORPORATE_BOND"],
            "currency": "USD",
            "country": "Argentina",
            "hard_dollar_only": True,
            "avoid_sectors": ["Energy"],
        }
        result = engine.apply(full_universe, prefs)
        meli_exc = next(e for e in result.exclusions if e.ticker == "MELI30")
        assert any("not_available_at_entity" in r for r in meli_exc.reasons)


# ─────────────────────────────────────────────────────────────────────────────
# Engine — to_dict round-trip
# ─────────────────────────────────────────────────────────────────────────────


class TestPreferenceFilterEngineToDict:
    def test_result_to_dict_is_serialisable(
        self, engine: PreferenceFilterEngine
    ) -> None:
        import json
        uni = _universe(_inst("A", currency="USD"), _inst("B", currency="ARS"))
        result = engine.apply(uni, {"currency": "USD"})
        d = result.to_dict()
        # Should be fully JSON-serialisable
        serialised = json.dumps(d)
        loaded = json.loads(serialised)
        assert loaded["exclusions"][0]["ticker"] == "B"
        assert loaded["applied_filters"] == ["currency:USD"]
