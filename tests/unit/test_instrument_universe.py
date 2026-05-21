"""
Tests for the universe_layer: instruments.py and csv_provider.py.

Coverage
--------
FinancialInstrument:
    - valid construction
    - empty string validation
    - invalid enum types
    - liquidity_score out of range
    - negative optional floats
    - to_dict serializable
    - is_available_at (case-insensitive)
    - is_usd
    - is_argentina

InstrumentUniverse:
    - valid construction
    - duplicate tickers raise ValueError
    - __len__
    - tickers property
    - to_dict serializable
    - filter_by_entity preserves order
    - filter_by_currency
    - filter_by_country
    - filter_by_instrument_type
    - filter_hard_dollar_only
    - filter_min_liquidity
    - chained filters

CSVInstrumentUniverseProvider:
    - loads fixture successfully
    - FileNotFoundError on missing file
    - ValueError on missing required column
    - ValueError on invalid enum string
    - bool parsing (all variants)
    - available_entities semicolon parsing
    - optional floats empty → None
    - notes semicolon parsing
    - fixture contains AR hard-dollar corporate bonds
    - combined filter: Balanz + USD + hard_dollar + CORPORATE_BOND
"""

from __future__ import annotations

import csv
import io
import textwrap
from pathlib import Path

import pytest

from risk_first_advisory.universe_layer.instruments import (
    AssetClass,
    FinancialInstrument,
    InstrumentType,
    InstrumentUniverse,
)
from risk_first_advisory.universe_layer.csv_provider import (
    CSVInstrumentUniverseProvider,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixture path
# ─────────────────────────────────────────────────────────────────────────────

FIXTURE_CSV = (
    Path(__file__).parent.parent
    / "fixtures"
    / "universe"
    / "sample_instrument_universe.csv"
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_HEADER = (
    "ticker,name,issuer,instrument_type,asset_class,currency,country,"
    "sector,available_entities,hard_dollar,liquidity_score"
)


def _make_instrument(**overrides: object) -> FinancialInstrument:
    """Return a valid FinancialInstrument, with optional field overrides."""
    defaults: dict = {
        "ticker": "SPY",
        "name": "SPDR S&P 500 ETF Trust",
        "issuer": "State Street",
        "instrument_type": InstrumentType.ETF,
        "asset_class": AssetClass.EQUITY,
        "currency": "USD",
        "country": "US",
        "sector": "Equity",
        "available_entities": ["Balanz", "PPI"],
        "hard_dollar": False,
        "liquidity_score": 0.99,
    }
    defaults.update(overrides)
    return FinancialInstrument(**defaults)  # type: ignore[arg-type]


def _make_universe(*tickers: str, **overrides: object) -> InstrumentUniverse:
    """Return an InstrumentUniverse with one instrument per ticker."""
    instruments = [
        _make_instrument(ticker=t, **overrides) for t in tickers
    ]
    return InstrumentUniverse(instruments=instruments)


def _write_csv(tmp_path: Path, content: str, filename: str = "test.csv") -> Path:
    """Write CSV content to a temp file and return the path."""
    p = tmp_path / filename
    p.write_text(textwrap.dedent(content).strip(), encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# FinancialInstrument tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFinancialInstrumentConstruction:
    def test_valid_construction_minimal(self) -> None:
        inst = _make_instrument()
        assert inst.ticker == "SPY"
        assert inst.instrument_type == InstrumentType.ETF
        assert inst.asset_class == AssetClass.EQUITY
        assert inst.hard_dollar is False
        assert inst.maturity_date is None
        assert inst.coupon_rate is None
        assert inst.notes == []

    def test_valid_construction_full(self) -> None:
        inst = _make_instrument(
            ticker="YCPDO",
            name="YPF ON 2026",
            issuer="YPF",
            instrument_type=InstrumentType.CORPORATE_BOND,
            asset_class=AssetClass.FIXED_INCOME,
            currency="USD",
            country="AR",
            sector="Energy",
            available_entities=["Balanz", "PPI"],
            hard_dollar=True,
            maturity_date="2026-06-15",
            coupon_rate=6.95,
            ytm=7.20,
            duration=1.8,
            liquidity_score=0.70,
            min_piece=1000.0,
            rating="B+",
            notes=["ON hard dollar", "vto 2026"],
        )
        assert inst.ticker == "YCPDO"
        assert inst.hard_dollar is True
        assert inst.coupon_rate == pytest.approx(6.95)
        assert inst.notes == ["ON hard dollar", "vto 2026"]


class TestFinancialInstrumentValidation:
    @pytest.mark.parametrize("field_name", [
        "ticker", "name", "issuer", "currency", "country", "sector",
    ])
    def test_empty_string_raises(self, field_name: str) -> None:
        with pytest.raises(ValueError, match=field_name):
            _make_instrument(**{field_name: ""})

    @pytest.mark.parametrize("field_name", [
        "ticker", "name", "issuer", "currency", "country", "sector",
    ])
    def test_whitespace_only_raises(self, field_name: str) -> None:
        with pytest.raises(ValueError, match=field_name):
            _make_instrument(**{field_name: "   "})

    def test_instrument_type_wrong_type_raises(self) -> None:
        with pytest.raises(TypeError, match="instrument_type"):
            _make_instrument(instrument_type="ETF")  # str, not enum

    def test_asset_class_wrong_type_raises(self) -> None:
        with pytest.raises(TypeError, match="asset_class"):
            _make_instrument(asset_class="EQUITY")  # str, not enum

    def test_available_entities_not_list_raises(self) -> None:
        with pytest.raises(TypeError, match="available_entities"):
            _make_instrument(available_entities="Balanz;PPI")  # str, not list

    def test_available_entities_list_of_nonstrings_raises(self) -> None:
        with pytest.raises(TypeError, match="available_entities"):
            _make_instrument(available_entities=[1, 2])  # type: ignore[list-item]

    def test_hard_dollar_not_bool_raises(self) -> None:
        with pytest.raises(TypeError, match="hard_dollar"):
            _make_instrument(hard_dollar=1)  # int, not bool

    def test_liquidity_score_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="liquidity_score"):
            _make_instrument(liquidity_score=1.01)

    def test_liquidity_score_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="liquidity_score"):
            _make_instrument(liquidity_score=-0.01)

    def test_liquidity_score_zero_allowed(self) -> None:
        inst = _make_instrument(liquidity_score=0.0)
        assert inst.liquidity_score == 0.0

    def test_liquidity_score_one_allowed(self) -> None:
        inst = _make_instrument(liquidity_score=1.0)
        assert inst.liquidity_score == 1.0

    @pytest.mark.parametrize("attr", ["coupon_rate", "ytm", "duration", "min_piece"])
    def test_negative_optional_float_raises(self, attr: str) -> None:
        with pytest.raises(ValueError, match=attr):
            _make_instrument(**{attr: -0.01})

    @pytest.mark.parametrize("attr", ["coupon_rate", "ytm", "duration", "min_piece"])
    def test_zero_optional_float_allowed(self, attr: str) -> None:
        inst = _make_instrument(**{attr: 0.0})
        assert getattr(inst, attr) == 0.0

    def test_notes_not_list_raises(self) -> None:
        with pytest.raises(TypeError, match="notes"):
            _make_instrument(notes="single note")  # str, not list

    def test_notes_list_of_nonstrings_raises(self) -> None:
        with pytest.raises(TypeError, match="notes"):
            _make_instrument(notes=[1, 2, 3])  # type: ignore[list-item]


class TestFinancialInstrumentMethods:
    def test_to_dict_has_all_keys(self) -> None:
        inst = _make_instrument()
        d = inst.to_dict()
        expected_keys = {
            "ticker", "name", "issuer", "instrument_type", "asset_class",
            "currency", "country", "sector", "available_entities", "hard_dollar",
            "maturity_date", "coupon_rate", "ytm", "duration", "liquidity_score",
            "min_piece", "rating", "notes",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_uses_enum_values(self) -> None:
        inst = _make_instrument(
            instrument_type=InstrumentType.CORPORATE_BOND,
            asset_class=AssetClass.FIXED_INCOME,
        )
        d = inst.to_dict()
        assert d["instrument_type"] == "CORPORATE_BOND"
        assert d["asset_class"] == "FIXED_INCOME"

    def test_to_dict_serializable_with_json(self) -> None:
        import json
        inst = _make_instrument(coupon_rate=5.0, notes=["note 1", "note 2"])
        json_str = json.dumps(inst.to_dict())
        loaded = json.loads(json_str)
        assert loaded["ticker"] == "SPY"
        assert loaded["notes"] == ["note 1", "note 2"]

    def test_is_available_at_exact_match(self) -> None:
        inst = _make_instrument(available_entities=["Balanz", "PPI"])
        assert inst.is_available_at("Balanz") is True
        assert inst.is_available_at("PPI") is True

    def test_is_available_at_case_insensitive(self) -> None:
        inst = _make_instrument(available_entities=["Balanz", "PPI"])
        assert inst.is_available_at("balanz") is True
        assert inst.is_available_at("BALANZ") is True
        assert inst.is_available_at("ppi") is True

    def test_is_available_at_missing_entity(self) -> None:
        inst = _make_instrument(available_entities=["Balanz"])
        assert inst.is_available_at("Cocos") is False
        assert inst.is_available_at("") is False

    def test_is_usd_true(self) -> None:
        assert _make_instrument(currency="USD").is_usd is True

    def test_is_usd_false(self) -> None:
        assert _make_instrument(currency="ARS").is_usd is False

    def test_is_usd_case_insensitive(self) -> None:
        assert _make_instrument(currency="usd").is_usd is True

    def test_is_argentina_ar(self) -> None:
        assert _make_instrument(country="AR").is_argentina is True

    def test_is_argentina_arg(self) -> None:
        assert _make_instrument(country="ARG").is_argentina is True

    def test_is_argentina_full_name(self) -> None:
        assert _make_instrument(country="Argentina").is_argentina is True

    def test_is_argentina_false(self) -> None:
        assert _make_instrument(country="US").is_argentina is False

    def test_is_argentina_case_insensitive(self) -> None:
        assert _make_instrument(country="argentina").is_argentina is True


# ─────────────────────────────────────────────────────────────────────────────
# InstrumentUniverse tests
# ─────────────────────────────────────────────────────────────────────────────


class TestInstrumentUniverseConstruction:
    def test_valid_construction_empty(self) -> None:
        u = InstrumentUniverse(instruments=[])
        assert len(u) == 0

    def test_valid_construction_multiple(self) -> None:
        u = _make_universe("SPY", "VTI", "GLD")
        assert len(u) == 3

    def test_duplicate_tickers_raise(self) -> None:
        insts = [_make_instrument(ticker="SPY"), _make_instrument(ticker="SPY")]
        with pytest.raises(ValueError, match="duplicate"):
            InstrumentUniverse(instruments=insts)

    def test_instruments_not_list_raises(self) -> None:
        with pytest.raises(TypeError, match="list"):
            InstrumentUniverse(instruments="not a list")  # type: ignore[arg-type]


class TestInstrumentUniverseProperties:
    def test_len(self) -> None:
        assert len(_make_universe("A", "B", "C")) == 3
        assert len(_make_universe()) == 0

    def test_tickers_preserves_order(self) -> None:
        u = _make_universe("VTI", "SPY", "GLD")
        assert u.tickers == ["VTI", "SPY", "GLD"]

    def test_to_dict_serializable(self) -> None:
        import json
        u = _make_universe("SPY", "VTI")
        d = u.to_dict()
        assert "instruments" in d
        assert len(d["instruments"]) == 2
        # Must be JSON-serializable
        json_str = json.dumps(d)
        loaded = json.loads(json_str)
        assert loaded["instruments"][0]["ticker"] == "SPY"


class TestInstrumentUniverseFilters:
    def _universe_with_entities(self) -> InstrumentUniverse:
        """Build a mini universe with varied entity coverage."""
        return InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", available_entities=["Balanz", "PPI"]),
            _make_instrument(ticker="B", available_entities=["PPI", "Cocos"]),
            _make_instrument(ticker="C", available_entities=["Balanz"]),
            _make_instrument(ticker="D", available_entities=["Cocos"]),
        ])

    def test_filter_by_entity_preserves_order(self) -> None:
        u = self._universe_with_entities()
        result = u.filter_by_entity("Balanz")
        assert result.tickers == ["A", "C"]

    def test_filter_by_entity_case_insensitive(self) -> None:
        u = self._universe_with_entities()
        result = u.filter_by_entity("balanz")
        assert result.tickers == ["A", "C"]

    def test_filter_by_entity_no_match(self) -> None:
        u = self._universe_with_entities()
        result = u.filter_by_entity("Nonexistent")
        assert len(result) == 0

    def test_filter_by_entity_returns_new_universe(self) -> None:
        u = self._universe_with_entities()
        result = u.filter_by_entity("Balanz")
        assert result is not u

    def test_filter_by_currency_usd(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", currency="USD"),
            _make_instrument(ticker="B", currency="ARS"),
            _make_instrument(ticker="C", currency="USD"),
        ])
        result = u.filter_by_currency("USD")
        assert result.tickers == ["A", "C"]

    def test_filter_by_currency_case_insensitive(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", currency="USD"),
            _make_instrument(ticker="B", currency="ars"),
        ])
        assert u.filter_by_currency("usd").tickers == ["A"]

    def test_filter_by_country_ar(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", country="AR"),
            _make_instrument(ticker="B", country="US"),
            _make_instrument(ticker="C", country="AR"),
        ])
        result = u.filter_by_country("AR")
        assert result.tickers == ["A", "C"]

    def test_filter_by_instrument_type_single(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", instrument_type=InstrumentType.ETF),
            _make_instrument(ticker="B", instrument_type=InstrumentType.CORPORATE_BOND),
            _make_instrument(ticker="C", instrument_type=InstrumentType.ETF),
        ])
        result = u.filter_by_instrument_type([InstrumentType.ETF])
        assert result.tickers == ["A", "C"]

    def test_filter_by_instrument_type_multiple(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", instrument_type=InstrumentType.ETF),
            _make_instrument(ticker="B", instrument_type=InstrumentType.CORPORATE_BOND),
            _make_instrument(ticker="C", instrument_type=InstrumentType.SOVEREIGN_BOND),
            _make_instrument(ticker="D", instrument_type=InstrumentType.CEDEAR),
        ])
        result = u.filter_by_instrument_type(
            [InstrumentType.CORPORATE_BOND, InstrumentType.SOVEREIGN_BOND]
        )
        assert result.tickers == ["B", "C"]

    def test_filter_hard_dollar_only(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", hard_dollar=True),
            _make_instrument(ticker="B", hard_dollar=False),
            _make_instrument(ticker="C", hard_dollar=True),
        ])
        result = u.filter_hard_dollar_only()
        assert result.tickers == ["A", "C"]

    def test_filter_min_liquidity(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", liquidity_score=0.90),
            _make_instrument(ticker="B", liquidity_score=0.50),
            _make_instrument(ticker="C", liquidity_score=0.75),
        ])
        result = u.filter_min_liquidity(0.75)
        assert result.tickers == ["A", "C"]

    def test_filter_min_liquidity_boundary_included(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(ticker="A", liquidity_score=0.75),
        ])
        assert u.filter_min_liquidity(0.75).tickers == ["A"]

    def test_chained_filters(self) -> None:
        u = InstrumentUniverse(instruments=[
            _make_instrument(
                ticker="A", currency="USD", hard_dollar=True, liquidity_score=0.80,
                available_entities=["Balanz"], instrument_type=InstrumentType.CORPORATE_BOND,
            ),
            _make_instrument(
                ticker="B", currency="ARS", hard_dollar=False, liquidity_score=0.95,
                available_entities=["Balanz"], instrument_type=InstrumentType.ETF,
            ),
            _make_instrument(
                ticker="C", currency="USD", hard_dollar=True, liquidity_score=0.60,
                available_entities=["PPI"], instrument_type=InstrumentType.CORPORATE_BOND,
            ),
            _make_instrument(
                ticker="D", currency="USD", hard_dollar=True, liquidity_score=0.90,
                available_entities=["Balanz"], instrument_type=InstrumentType.CORPORATE_BOND,
            ),
        ])
        result = (
            u
            .filter_by_entity("Balanz")
            .filter_by_currency("USD")
            .filter_hard_dollar_only()
            .filter_by_instrument_type([InstrumentType.CORPORATE_BOND])
        )
        assert result.tickers == ["A", "D"]

    def test_filter_returns_independent_universe(self) -> None:
        u = _make_universe("SPY", "VTI", "GLD")
        result = u.filter_by_currency("USD")
        assert result is not u
        assert len(u) == 3  # original unchanged


# ─────────────────────────────────────────────────────────────────────────────
# CSVInstrumentUniverseProvider tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCSVProviderFixture:
    def test_loads_fixture_successfully(self) -> None:
        provider = CSVInstrumentUniverseProvider(FIXTURE_CSV)
        universe = provider.load()
        assert len(universe) >= 12

    def test_fixture_tickers_unique(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        assert len(universe.tickers) == len(set(universe.tickers))

    def test_fixture_contains_etfs(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        etfs = universe.filter_by_instrument_type([InstrumentType.ETF])
        assert "SPY" in etfs.tickers
        assert "VTI" in etfs.tickers
        assert "GLD" in etfs.tickers

    def test_fixture_contains_ar_hard_dollar_corporate_bonds(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        ar_hd_corps = (
            universe
            .filter_by_country("AR")
            .filter_hard_dollar_only()
            .filter_by_instrument_type([InstrumentType.CORPORATE_BOND])
        )
        assert len(ar_hd_corps) >= 3

    def test_fixture_contains_sovereign_bonds(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        sovs = universe.filter_by_instrument_type([InstrumentType.SOVEREIGN_BOND])
        assert "GD30" in sovs.tickers
        assert "AL35" in sovs.tickers

    def test_fixture_contains_money_market(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        mm = universe.filter_by_instrument_type([InstrumentType.MONEY_MARKET])
        assert len(mm) >= 2

    def test_fixture_contains_cedear(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        cedears = universe.filter_by_instrument_type([InstrumentType.CEDEAR])
        assert len(cedears) >= 1

    def test_combined_filter_balanz_usd_harddollar_corporate(self) -> None:
        """Balanz + USD + hard_dollar + CORPORATE_BOND → only eligible ONs."""
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        result = (
            universe
            .filter_by_entity("Balanz")
            .filter_by_currency("USD")
            .filter_hard_dollar_only()
            .filter_by_instrument_type([InstrumentType.CORPORATE_BOND])
        )
        # Fixture: YCPDO (Balanz;PPI), GALI28 (Balanz), PAMP27 (Balanz;Cocos)
        # MELI30 is CORPORATE_BOND + USD + hard_dollar but available at PPI;Cocos only
        assert len(result) == 3
        assert set(result.tickers) == {"YCPDO", "GALI28", "PAMP27"}

    def test_fixture_order_preserved(self) -> None:
        """Tickers in the universe should match CSV row order."""
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        tickers = universe.tickers
        assert tickers[0] == "SPY"
        assert tickers[1] == "VTI"
        assert tickers[2] == "GLD"

    def test_fixture_gd30_is_usd_argentina(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        gd30 = next(i for i in universe.instruments if i.ticker == "GD30")
        assert gd30.is_usd is True
        assert gd30.is_argentina is True

    def test_fixture_spy_not_argentina(self) -> None:
        universe = CSVInstrumentUniverseProvider(FIXTURE_CSV).load()
        spy = next(i for i in universe.instruments if i.ticker == "SPY")
        assert spy.is_argentina is False


class TestCSVProviderErrorHandling:
    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        provider = CSVInstrumentUniverseProvider(tmp_path / "nonexistent.csv")
        with pytest.raises(FileNotFoundError, match="nonexistent.csv"):
            provider.load()

    def test_missing_required_column_raises(self, tmp_path: Path) -> None:
        # Omit 'hard_dollar' from the header
        content = (
            "ticker,name,issuer,instrument_type,asset_class,currency,country,"
            "sector,available_entities,liquidity_score\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        with pytest.raises(ValueError, match="hard_dollar"):
            CSVInstrumentUniverseProvider(p).load()

    def test_multiple_missing_columns_error_lists_them(self, tmp_path: Path) -> None:
        content = "ticker,name\nSPY,SPDR\n"
        p = _write_csv(tmp_path, content)
        with pytest.raises(ValueError, match="missing required columns"):
            CSVInstrumentUniverseProvider(p).load()

    def test_invalid_instrument_type_raises(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,UNKNOWN_TYPE,EQUITY,USD,US,Equity,Balanz,false,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        with pytest.raises(ValueError, match="instrument_type"):
            CSVInstrumentUniverseProvider(p).load()

    def test_invalid_asset_class_raises(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,ETF,UNKNOWN_CLASS,USD,US,Equity,Balanz,false,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        with pytest.raises(ValueError, match="asset_class"):
            CSVInstrumentUniverseProvider(p).load()

    def test_error_includes_line_number(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "GOOD,Good Instrument,Issuer,ETF,EQUITY,USD,US,Equity,Balanz,false,0.90\n"
            "BAD,Bad Instrument,Issuer,ETF,EQUITY,USD,US,Equity,Balanz,NOTBOOL,0.90\n"
        )
        p = _write_csv(tmp_path, content)
        with pytest.raises(ValueError, match="Line 3"):
            CSVInstrumentUniverseProvider(p).load()


class TestCSVProviderBoolParsing:
    @pytest.mark.parametrize("bool_str,expected", [
        ("true",  True),
        ("True",  True),
        ("TRUE",  True),
        ("1",     True),
        ("yes",   True),
        ("Yes",   True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0",     False),
        ("no",    False),
        ("No",    False),
    ])
    def test_valid_bool_strings(
        self, tmp_path: Path, bool_str: str, expected: bool
    ) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            f"SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,{bool_str},0.99\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].hard_dollar == expected

    def test_invalid_bool_raises(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,maybe,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        with pytest.raises(ValueError, match="hard_dollar"):
            CSVInstrumentUniverseProvider(p).load()


class TestCSVProviderFieldParsing:
    def test_available_entities_semicolon_split(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz;PPI;Cocos,false,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].available_entities == ["Balanz", "PPI", "Cocos"]

    def test_available_entities_single(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,false,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].available_entities == ["Balanz"]

    def test_available_entities_empty(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,,false,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].available_entities == []

    def test_optional_floats_empty_become_none(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER},maturity_date,coupon_rate,ytm,duration,min_piece,rating,notes\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,false,0.99,,,,,,,"
            "\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        inst = universe.instruments[0]
        assert inst.coupon_rate is None
        assert inst.ytm is None
        assert inst.duration is None
        assert inst.min_piece is None

    def test_optional_floats_with_values(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER},coupon_rate,ytm,duration,min_piece\n"
            "BOND,Corp Bond,Issuer,CORPORATE_BOND,FIXED_INCOME,USD,US,Financials,"
            "Balanz,true,0.70,6.5,7.0,2.5,1000.0\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        inst = universe.instruments[0]
        assert inst.coupon_rate == pytest.approx(6.5)
        assert inst.ytm == pytest.approx(7.0)
        assert inst.duration == pytest.approx(2.5)
        assert inst.min_piece == pytest.approx(1000.0)

    def test_notes_semicolon_split(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER},notes\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,false,0.99,"
            "First note;Second note;Third note\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].notes == [
            "First note", "Second note", "Third note"
        ]

    def test_notes_empty_is_empty_list(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER},notes\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,false,0.99,\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].notes == []

    def test_instrument_type_case_insensitive(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,etf,equity,USD,US,Equity,Balanz,false,0.99\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].instrument_type == InstrumentType.ETF
        assert universe.instruments[0].asset_class == AssetClass.EQUITY

    def test_maturity_date_optional(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER},maturity_date\n"
            "BOND,Corp Bond,Issuer,CORPORATE_BOND,FIXED_INCOME,USD,US,"
            "Financials,Balanz,true,0.70,2030-01-15\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].maturity_date == "2030-01-15"

    def test_maturity_date_empty_is_none(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER},maturity_date\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,false,0.99,\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].maturity_date is None

    def test_rating_empty_is_none(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER},rating\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,false,0.99,\n"
        )
        p = _write_csv(tmp_path, content)
        universe = CSVInstrumentUniverseProvider(p).load()
        assert universe.instruments[0].rating is None

    def test_duplicate_tickers_in_csv_raise(self, tmp_path: Path) -> None:
        content = (
            f"{_REQUIRED_HEADER}\n"
            "SPY,SPDR,SS,ETF,EQUITY,USD,US,Equity,Balanz,false,0.99\n"
            "SPY,SPDR Copy,SS,ETF,EQUITY,USD,US,Equity,PPI,false,0.95\n"
        )
        p = _write_csv(tmp_path, content)
        with pytest.raises(ValueError, match="duplicate"):
            CSVInstrumentUniverseProvider(p).load()
