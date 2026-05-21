"""
Integration tests for POST /universe/filter-demo.

Uses FastAPI TestClient — no real network calls, no OpenAI, no DB writes.
The endpoint loads tests/fixtures/universe/sample_instrument_universe.csv and
applies PreferenceFilterEngine deterministically.

Fixture snapshot (12 instruments):
    ETF        : SPY (Balanz;PPI;Cocos), VTI (Balanz;PPI), GLD (PPI;Cocos)  — USD / US
    CORP_BOND  : YCPDO (Balanz;PPI / Energy / 2026), GALI28 (Balanz / Financials / 2028),
                 PAMP27 (Balanz;Cocos / Energy / 2027), MELI30 (PPI;Cocos / Technology / 2030)
    SOV_BOND   : GD30 (Balanz;PPI;Cocos / 2030), AL35 (Balanz;Cocos / 2035)
    MONEY_MKT  : FIMA (Balanz / ARS), BONO0 (PPI / USD)
    CEDEAR     : APBR (Balanz;PPI / ARS / Energy)

All instruments are AR except SPY, VTI, GLD (US).
hard_dollar=true : YCPDO, GALI28, PAMP27, MELI30, GD30, AL35, BONO0
hard_dollar=false: SPY, VTI, GLD, FIMA, APBR
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from risk_first_advisory.api_layer.main import app

_CLIENT = TestClient(app, raise_server_exceptions=False)

_URL = "/universe/filter-demo"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _post(body: dict) -> "requests.Response":  # type: ignore[name-defined]
    return _CLIENT.post(_URL, json=body)


def _eligible_tickers(resp) -> list[str]:
    return [i["ticker"] for i in resp.json()["eligible_instruments"]]


def _excluded_tickers(resp) -> list[str]:
    return [e["ticker"] for e in resp.json()["exclusions"]]


# ─────────────────────────────────────────────────────────────────────────────
# Basic structure
# ─────────────────────────────────────────────────────────────────────────────


class TestUniverseFilterBasic:
    def test_empty_body_returns_200(self) -> None:
        resp = _post({})
        assert resp.status_code == 200

    def test_empty_body_returns_all_twelve_instruments(self) -> None:
        resp = _post({})
        data = resp.json()
        assert data["eligible_count"] == 12

    def test_response_includes_eligible_count(self) -> None:
        resp = _post({})
        assert "eligible_count" in resp.json()

    def test_response_includes_excluded_count(self) -> None:
        resp = _post({})
        assert "excluded_count" in resp.json()

    def test_response_includes_eligible_instruments(self) -> None:
        resp = _post({})
        data = resp.json()
        assert "eligible_instruments" in data
        assert isinstance(data["eligible_instruments"], list)

    def test_response_includes_exclusions(self) -> None:
        resp = _post({})
        data = resp.json()
        assert "exclusions" in data
        assert isinstance(data["exclusions"], list)

    def test_response_includes_applied_filters(self) -> None:
        resp = _post({})
        assert "applied_filters" in resp.json()

    def test_response_includes_warnings(self) -> None:
        resp = _post({})
        assert "warnings" in resp.json()

    def test_response_is_json_serializable(self) -> None:
        resp = _post({})
        # Already parsed; round-trip to make sure
        serialised = json.dumps(resp.json())
        reloaded = json.loads(serialised)
        assert reloaded["eligible_count"] == 12

    def test_eligible_instrument_shape(self) -> None:
        resp = _post({})
        inst = resp.json()["eligible_instruments"][0]
        required_fields = {
            "ticker", "name", "issuer", "instrument_type", "asset_class",
            "currency", "country", "sector", "available_entities", "hard_dollar",
            "maturity_date", "coupon_rate", "ytm", "duration", "liquidity_score",
            "min_piece", "rating", "notes",
        }
        assert required_fields.issubset(inst.keys())

    def test_empty_body_no_exclusions(self) -> None:
        resp = _post({})
        data = resp.json()
        assert data["excluded_count"] == 0
        assert data["exclusions"] == []

    def test_empty_body_no_applied_filters(self) -> None:
        resp = _post({})
        assert resp.json()["applied_filters"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Single-filter tests
# ─────────────────────────────────────────────────────────────────────────────


class TestUniverseFilterSingleFilters:
    def test_filter_entity_balanz(self) -> None:
        resp = _post({"entity": "Balanz"})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        # GLD is PPI;Cocos only — not at Balanz
        assert "GLD" in excluded
        # MELI30 is PPI;Cocos only — not at Balanz
        assert "MELI30" in excluded
        # BONO0 is PPI only — not at Balanz
        assert "BONO0" in excluded
        # SPY is at Balanz
        assert "SPY" not in excluded

    def test_filter_entity_applied_filter_label(self) -> None:
        resp = _post({"entity": "Balanz"})
        filters = resp.json()["applied_filters"]
        assert any("entity" in f for f in filters)

    def test_filter_allowed_instrument_types_corporate_bond(self) -> None:
        resp = _post({"allowed_instrument_types": ["CORPORATE_BOND"]})
        assert resp.status_code == 200
        eligible = _eligible_tickers(resp)
        assert set(eligible) == {"YCPDO", "GALI28", "PAMP27", "MELI30"}

    def test_filter_allowed_instrument_types_multiple(self) -> None:
        resp = _post({"allowed_instrument_types": ["ETF", "MONEY_MARKET"]})
        assert resp.status_code == 200
        eligible = _eligible_tickers(resp)
        assert set(eligible) == {"SPY", "VTI", "GLD", "FIMA", "BONO0"}

    def test_filter_excluded_instrument_types_etf(self) -> None:
        resp = _post({"excluded_instrument_types": ["ETF"]})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        assert set(excluded) == {"SPY", "VTI", "GLD"}

    def test_filter_currency_usd(self) -> None:
        resp = _post({"currency": "USD"})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        # FIMA (ARS) and APBR (ARS) excluded
        assert "FIMA" in excluded
        assert "APBR" in excluded
        eligible = _eligible_tickers(resp)
        assert "SPY" in eligible
        assert "YCPDO" in eligible

    def test_filter_currency_usd_count(self) -> None:
        resp = _post({"currency": "USD"})
        data = resp.json()
        # 12 total - 2 ARS (FIMA, APBR) = 10
        assert data["eligible_count"] == 10
        assert data["excluded_count"] == 2

    def test_filter_country_argentina(self) -> None:
        resp = _post({"country": "Argentina"})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        # US instruments excluded: SPY, VTI, GLD
        assert "SPY" in excluded
        assert "VTI" in excluded
        assert "GLD" in excluded
        eligible = _eligible_tickers(resp)
        # AR instruments pass
        assert "YCPDO" in eligible
        assert "GD30" in eligible

    def test_filter_country_argentina_alias_ar(self) -> None:
        resp_argentina = _post({"country": "Argentina"})
        resp_ar = _post({"country": "AR"})
        assert _eligible_tickers(resp_argentina) == _eligible_tickers(resp_ar)

    def test_filter_country_argentina_alias_arg(self) -> None:
        resp_argentina = _post({"country": "Argentina"})
        resp_arg = _post({"country": "ARG"})
        assert _eligible_tickers(resp_argentina) == _eligible_tickers(resp_arg)

    def test_filter_hard_dollar_only(self) -> None:
        resp = _post({"hard_dollar_only": True})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        # non-hard-dollar: SPY, VTI, GLD, FIMA, APBR
        assert {"SPY", "VTI", "GLD", "FIMA", "APBR"}.issubset(set(excluded))
        eligible = _eligible_tickers(resp)
        assert "YCPDO" in eligible
        assert "GD30" in eligible

    def test_filter_hard_dollar_false_no_filter(self) -> None:
        resp = _post({"hard_dollar_only": False})
        assert resp.status_code == 200
        assert resp.json()["eligible_count"] == 12

    def test_filter_avoid_sectors_energy(self) -> None:
        resp = _post({"avoid_sectors": ["Energy"]})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        # Energy instruments: YCPDO, PAMP27, APBR
        assert "YCPDO" in excluded
        assert "PAMP27" in excluded
        assert "APBR" in excluded
        assert "GALI28" not in excluded  # Financials sector

    def test_filter_avoid_sectors_reason_code(self) -> None:
        resp = _post({"avoid_sectors": ["Energy"]})
        data = resp.json()
        ycpdo_exc = next(e for e in data["exclusions"] if e["ticker"] == "YCPDO")
        assert any("sector_avoided" in r for r in ycpdo_exc["reasons"])

    def test_filter_avoid_issuers(self) -> None:
        resp = _post({"avoid_issuers": ["YPF"]})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        assert "YCPDO" in excluded
        assert "GALI28" not in excluded

    def test_filter_min_liquidity_score(self) -> None:
        resp = _post({"min_liquidity_score": 0.70})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        # GALI28 (0.65), MELI30 (0.60), APBR (0.60)
        assert "GALI28" in excluded
        assert "MELI30" in excluded
        assert "APBR" in excluded
        assert "YCPDO" not in excluded  # exactly 0.70 passes

    def test_filter_max_maturity_year(self) -> None:
        resp = _post({"max_maturity_year": 2028})
        assert resp.status_code == 200
        excluded = _excluded_tickers(resp)
        # MELI30 (2030), GD30 (2030), AL35 (2035)
        assert "MELI30" in excluded
        assert "GD30" in excluded
        assert "AL35" in excluded
        assert "YCPDO" not in excluded  # 2026 ≤ 2028


# ─────────────────────────────────────────────────────────────────────────────
# Chained / combined filter
# ─────────────────────────────────────────────────────────────────────────────


class TestUniverseFilterCombined:
    """
    Filters: entity=Balanz + allowed_instrument_types=[CORPORATE_BOND]
             + currency=USD + country=Argentina + hard_dollar_only=true
             + avoid_sectors=[Energy]
    Expected eligible: GALI28 only.
    """

    _COMBINED = {
        "entity": "Balanz",
        "allowed_instrument_types": ["CORPORATE_BOND"],
        "currency": "USD",
        "country": "Argentina",
        "hard_dollar_only": True,
        "avoid_sectors": ["Energy"],
    }

    def test_combined_eligible_is_gali28_only(self) -> None:
        resp = _post(self._COMBINED)
        assert resp.status_code == 200
        assert _eligible_tickers(resp) == ["GALI28"]

    def test_combined_eligible_count_is_one(self) -> None:
        resp = _post(self._COMBINED)
        assert resp.json()["eligible_count"] == 1

    def test_combined_excluded_count_is_eleven(self) -> None:
        resp = _post(self._COMBINED)
        assert resp.json()["excluded_count"] == 11

    def test_combined_all_tickers_accounted_for(self) -> None:
        resp = _post(self._COMBINED)
        data = resp.json()
        all_tickers = (
            [i["ticker"] for i in data["eligible_instruments"]]
            + [e["ticker"] for e in data["exclusions"]]
        )
        assert len(all_tickers) == 12

    def test_combined_applied_filters_recorded(self) -> None:
        resp = _post(self._COMBINED)
        filters = resp.json()["applied_filters"]
        assert any("entity" in f for f in filters)
        assert any("allowed_instrument_types" in f for f in filters)
        assert any("currency" in f for f in filters)
        assert any("country" in f for f in filters)
        assert any("hard_dollar_only" in f for f in filters)
        assert any("avoid_sectors" in f for f in filters)

    def test_combined_ycpdo_excluded_for_energy(self) -> None:
        resp = _post(self._COMBINED)
        exclusions = resp.json()["exclusions"]
        ycpdo = next((e for e in exclusions if e["ticker"] == "YCPDO"), None)
        assert ycpdo is not None
        assert any("sector_avoided" in r for r in ycpdo["reasons"])

    def test_combined_meli30_excluded_for_entity(self) -> None:
        resp = _post(self._COMBINED)
        exclusions = resp.json()["exclusions"]
        meli = next((e for e in exclusions if e["ticker"] == "MELI30"), None)
        assert meli is not None
        assert any("not_available_at_entity" in r for r in meli["reasons"])


# ─────────────────────────────────────────────────────────────────────────────
# Exclusion reasons
# ─────────────────────────────────────────────────────────────────────────────


class TestUniverseFilterExclusionDetails:
    def test_exclusions_include_reasons(self) -> None:
        resp = _post({"entity": "Balanz"})
        exclusions = resp.json()["exclusions"]
        assert len(exclusions) > 0
        for exc in exclusions:
            assert len(exc["reasons"]) > 0

    def test_entity_exclusion_reason_code(self) -> None:
        resp = _post({"entity": "Balanz"})
        exclusions = resp.json()["exclusions"]
        gld = next(e for e in exclusions if e["ticker"] == "GLD")
        assert any("not_available_at_entity:Balanz" == r for r in gld["reasons"])

    def test_multiple_reasons_accumulated(self) -> None:
        # currency=USD + avoid_sectors=Energy → APBR (ARS, Energy) gets 2 reasons
        resp = _post({"currency": "USD", "avoid_sectors": ["Energy"]})
        exclusions = resp.json()["exclusions"]
        apbr = next((e for e in exclusions if e["ticker"] == "APBR"), None)
        assert apbr is not None
        assert len(apbr["reasons"]) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# prefer_* keys — warnings only, no exclusions
# ─────────────────────────────────────────────────────────────────────────────


class TestUniverseFilterPreferKeys:
    def test_prefer_sectors_generates_warning(self) -> None:
        resp = _post({"prefer_sectors": ["Technology"]})
        assert resp.status_code == 200
        warnings = resp.json()["warnings"]
        assert any("prefer_sectors" in w for w in warnings)

    def test_prefer_sectors_does_not_exclude(self) -> None:
        resp = _post({"prefer_sectors": ["Technology"]})
        assert resp.json()["eligible_count"] == 12

    def test_prefer_issuers_generates_warning(self) -> None:
        resp = _post({"prefer_issuers": ["YPF"]})
        assert resp.status_code == 200
        warnings = resp.json()["warnings"]
        assert any("prefer_issuers" in w for w in warnings)


# ─────────────────────────────────────────────────────────────────────────────
# Validation errors
# ─────────────────────────────────────────────────────────────────────────────


class TestUniverseFilterValidationErrors:
    def test_invalid_instrument_type_returns_422(self) -> None:
        resp = _post({"allowed_instrument_types": ["NOT_A_REAL_TYPE"]})
        assert resp.status_code == 422

    def test_invalid_excluded_instrument_type_returns_422(self) -> None:
        resp = _post({"excluded_instrument_types": ["RUBBISH"]})
        assert resp.status_code == 422

    def test_invalid_min_liquidity_score_above_one_returns_422(self) -> None:
        resp = _post({"min_liquidity_score": 1.5})
        assert resp.status_code == 422

    def test_invalid_min_liquidity_score_below_zero_returns_422(self) -> None:
        resp = _post({"min_liquidity_score": -0.1})
        assert resp.status_code == 422

    def test_invalid_max_maturity_year_below_1900_returns_422(self) -> None:
        resp = _post({"max_maturity_year": 1800})
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Existing endpoints still work
# ─────────────────────────────────────────────────────────────────────────────


class TestExistingEndpointsUnaffected:
    def test_health_endpoint_returns_200(self) -> None:
        resp = _CLIENT.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ai_investment_preferences_returns_400_without_key(self) -> None:
        """
        /ai/investment-preferences requires OPENAI_API_KEY; without it → 400.
        Verifies the endpoint is still registered and routable.
        """
        resp = _CLIENT.post(
            "/ai/investment-preferences",
            json={
                "client_id": "TEST-001",
                "natural_language_preferences": "Solo quiero ONs hard dollar argentinas.",
            },
        )
        # 400 = key not configured; proves the route is reachable
        assert resp.status_code == 400
