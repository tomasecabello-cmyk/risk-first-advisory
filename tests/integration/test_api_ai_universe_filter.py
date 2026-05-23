"""
Integration tests for POST /ai/filter-universe-demo.

Pipeline: lenguaje natural → OpenAI (mocked) → PreferenceFilterEngine → response.

No llaman a OpenAI real. Se monkeypatchea
risk_first_advisory.api_layer.main._get_openai_profile_client
para devolver un _FakeAIClient que devuelve respuestas pre-construidas.

Fixture de universo: tests/fixtures/universe/sample_instrument_universe.csv (20 instrumentos).

Two AI response presets:
  _PASSTHROUGH_PREFS  — sin filtros activos → todos los instrumentos elegibles.
  _BALANZ_ONS_PREFS   — CORPORATE_BOND + USD + Argentina + Balanz + hard_dollar + avoid Energy
                         + min_liquidity=0.6 + max_maturity_year=2029
                         → GALI28 + 8 nuevos CORPORATE_BONDs no-Energy elegibles (9 total).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module

_URL = "/ai/filter-universe-demo"

# ─────────────────────────────────────────────────────────────────────────────
# AI response presets
# ─────────────────────────────────────────────────────────────────────────────


def _passthrough_prefs(**overrides) -> dict[str, Any]:
    """
    Preferences that activate no filters → all instruments eligible.
    """
    base: dict[str, Any] = {
        "allowed_instrument_types": [],
        "excluded_instrument_types": [],
        "currency": None,
        "country": None,
        "entity": None,
        "hard_dollar_only": None,
        "avoid_sectors": [],
        "prefer_sectors": [],
        "avoid_issuers": [],
        "prefer_issuers": [],
        "min_liquidity_score": None,
        "max_maturity_year": None,
        "hard_constraints": [],
        "soft_preferences": [],
        "unparsed_preferences": [],
        "confidence": 0.85,
        "advisor_notes": [],
    }
    base.update(overrides)
    return base


def _balanz_ons_prefs(**overrides) -> dict[str, Any]:
    """
    Preferences matching: ONs hard dollar argentinas en Balanz, evitar Energy.
    Expected eligible after filter: GALI28 + 8 new non-Energy Balanz CORPORATE_BONDs.
    """
    base: dict[str, Any] = {
        "allowed_instrument_types": ["CORPORATE_BOND"],
        "excluded_instrument_types": [],
        "currency": "USD",
        "country": "Argentina",
        "entity": "Balanz",
        "hard_dollar_only": True,
        "avoid_sectors": ["Energy"],
        "prefer_sectors": [],
        "avoid_issuers": [],
        "prefer_issuers": [],
        "min_liquidity_score": 0.6,
        "max_maturity_year": 2029,
        "hard_constraints": ["instrument_type", "currency", "country", "hard_dollar", "entity", "sector"],
        "soft_preferences": [],
        "unparsed_preferences": [],
        "confidence": 0.92,
        "advisor_notes": ["Client explicitly excluded energy sector."],
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Fake AI client
# ─────────────────────────────────────────────────────────────────────────────


class _FakeAIClient:
    """Devuelve respuestas pre-construidas sin llamar a OpenAI."""

    def __init__(
        self,
        preferences_response: dict | None = None,
        raise_on_preferences: bool = False,
    ) -> None:
        self._prefs = preferences_response if preferences_response is not None else _passthrough_prefs()
        self._raise = raise_on_preferences

    def extract_investment_preferences(self, payload: dict) -> dict:
        if self._raise:
            raise ValueError("AI preferences extraction returned invalid response")
        return self._prefs


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client_passthrough(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient cuyos fake AI prefs no activan ningún filtro → todos elegibles."""
    fake = _FakeAIClient(preferences_response=_passthrough_prefs())
    monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(_main_module.app, raise_server_exceptions=False)


@pytest.fixture
def client_balanz_ons(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient con prefs Balanz ONs hard dollar Argentina → GALI28 + nuevos no-Energy."""
    fake = _FakeAIClient(preferences_response=_balanz_ons_prefs())
    monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(_main_module.app, raise_server_exceptions=False)


@pytest.fixture
def client_raises_on_prefs(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient cuyo fake AI lanza ValueError → espera HTTP 502."""
    fake = _FakeAIClient(raise_on_preferences=True)
    monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(_main_module.app, raise_server_exceptions=False)


# Payload mínimo válido
_VALID_PAYLOAD: dict = {
    "client_id": "CLI-AI-FILTER-001",
    "natural_language_preferences": "Solo quiero ONs hard dollar argentinas en Balanz.",
}


def _post(client: TestClient, body: dict = _VALID_PAYLOAD) -> Any:
    return client.post(_URL, json=body)


# ─────────────────────────────────────────────────────────────────────────────
# Basic response structure
# ─────────────────────────────────────────────────────────────────────────────


class TestAIUniverseFilterBasic:
    def test_returns_200_with_fake_client(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert resp.status_code == 200

    def test_response_includes_client_id(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert resp.json()["client_id"] == "CLI-AI-FILTER-001"

    def test_response_includes_preferences_field(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert "preferences" in resp.json()
        assert isinstance(resp.json()["preferences"], dict)

    def test_response_includes_eligible_count(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert "eligible_count" in resp.json()

    def test_response_includes_excluded_count(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert "excluded_count" in resp.json()

    def test_response_includes_eligible_instruments(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        data = resp.json()
        assert "eligible_instruments" in data
        assert isinstance(data["eligible_instruments"], list)

    def test_response_includes_exclusions(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        data = resp.json()
        assert "exclusions" in data
        assert isinstance(data["exclusions"], list)

    def test_response_includes_applied_filters(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert "applied_filters" in resp.json()

    def test_response_includes_warnings(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert "warnings" in resp.json()

    def test_response_is_json_serializable(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        serialised = json.dumps(resp.json())
        reloaded = json.loads(serialised)
        assert "client_id" in reloaded

    def test_passthrough_all_twelve_eligible(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert resp.json()["eligible_count"] == 20

    def test_passthrough_no_exclusions(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert resp.json()["excluded_count"] == 0
        assert resp.json()["exclusions"] == []

    def test_passthrough_no_applied_filters(self, client_passthrough: TestClient) -> None:
        resp = _post(client_passthrough)
        assert resp.json()["applied_filters"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Preferences field contents
# ─────────────────────────────────────────────────────────────────────────────


class TestAIUniverseFilterPreferencesField:
    def test_preferences_includes_allowed_instrument_types(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        prefs = resp.json()["preferences"]
        assert "allowed_instrument_types" in prefs
        assert "CORPORATE_BOND" in prefs["allowed_instrument_types"]

    def test_preferences_includes_currency(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["preferences"]["currency"] == "USD"

    def test_preferences_includes_country(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["preferences"]["country"] == "Argentina"

    def test_preferences_includes_entity(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["preferences"]["entity"] == "Balanz"

    def test_preferences_includes_hard_dollar_only(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["preferences"]["hard_dollar_only"] is True

    def test_preferences_includes_avoid_sectors(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        prefs = resp.json()["preferences"]
        assert "Energy" in prefs["avoid_sectors"]

    def test_preferences_includes_confidence(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        prefs = resp.json()["preferences"]
        assert "confidence" in prefs
        assert isinstance(prefs["confidence"], float)

    def test_preferences_client_id_matches_request(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["preferences"]["client_id"] == "CLI-AI-FILTER-001"


# ─────────────────────────────────────────────────────────────────────────────
# Combined filter correctness (Balanz ONs scenario)
# ─────────────────────────────────────────────────────────────────────────────


class TestAIUniverseFilterCombined:
    """
    fake AI returns: CORPORATE_BOND + USD + Argentina + Balanz + hard_dollar + avoid Energy
    + min_liquidity_score=0.6 + max_maturity_year=2029
    → GALI28 + 8 new non-Energy Balanz CORPORATE_BONDs eligible (9 total).
    Excluded: same 11 original instruments.
    """

    def test_only_gali28_eligible(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        eligible = [i["ticker"] for i in data["eligible_instruments"]]
        assert "GALI28" in eligible
        # All eligible must satisfy filter constraints
        for inst in data["eligible_instruments"]:
            assert inst["instrument_type"] == "CORPORATE_BOND"
            assert inst["currency"] == "USD"
            assert inst["hard_dollar"] is True
            assert inst["sector"] != "Energy"
            assert "Balanz" in inst["available_entities"]

    def test_eligible_count_is_one(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["eligible_count"] >= 7

    def test_excluded_count_is_eleven(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["excluded_count"] == 11

    def test_all_twelve_accounted_for(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        all_tickers = (
            [i["ticker"] for i in data["eligible_instruments"]]
            + [e["ticker"] for e in data["exclusions"]]
        )
        assert len(all_tickers) == 20

    def test_applied_filters_contains_entity(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        filters = resp.json()["applied_filters"]
        assert any("entity" in f for f in filters)

    def test_applied_filters_contains_currency(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        filters = resp.json()["applied_filters"]
        assert any("currency" in f for f in filters)

    def test_applied_filters_contains_country(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        filters = resp.json()["applied_filters"]
        assert any("country" in f for f in filters)

    def test_applied_filters_contains_hard_dollar(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        filters = resp.json()["applied_filters"]
        assert any("hard_dollar_only" in f for f in filters)

    def test_applied_filters_contains_allowed_instrument_types(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        filters = resp.json()["applied_filters"]
        assert any("allowed_instrument_types" in f for f in filters)

    def test_applied_filters_contains_avoid_sectors(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        filters = resp.json()["applied_filters"]
        assert any("avoid_sectors" in f for f in filters)

    def test_exclusions_contain_reasons(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        exclusions = resp.json()["exclusions"]
        assert len(exclusions) > 0
        for exc in exclusions:
            assert len(exc["reasons"]) > 0

    def test_ycpdo_excluded_for_energy_sector(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        exclusions = resp.json()["exclusions"]
        ycpdo = next((e for e in exclusions if e["ticker"] == "YCPDO"), None)
        assert ycpdo is not None
        assert any("sector_avoided" in r for r in ycpdo["reasons"])

    def test_meli30_excluded_for_entity(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        exclusions = resp.json()["exclusions"]
        meli = next((e for e in exclusions if e["ticker"] == "MELI30"), None)
        assert meli is not None
        assert any("not_available_at_entity" in r for r in meli["reasons"])


# ─────────────────────────────────────────────────────────────────────────────
# Request validation errors (no AI call needed)
# ─────────────────────────────────────────────────────────────────────────────


class TestAIUniverseFilterRequestValidation:
    def test_empty_natural_language_preferences_returns_422(
        self, client_passthrough: TestClient
    ) -> None:
        resp = _post(
            client_passthrough,
            {"client_id": "X", "natural_language_preferences": ""},
        )
        assert resp.status_code == 422

    def test_missing_natural_language_preferences_returns_422(
        self, client_passthrough: TestClient
    ) -> None:
        resp = _post(client_passthrough, {"client_id": "X"})
        assert resp.status_code == 422

    def test_empty_client_id_returns_422(self, client_passthrough: TestClient) -> None:
        resp = _post(
            client_passthrough,
            {"client_id": "", "natural_language_preferences": "algo"},
        )
        assert resp.status_code == 422

    def test_missing_client_id_returns_422(self, client_passthrough: TestClient) -> None:
        resp = _post(
            client_passthrough,
            {"natural_language_preferences": "algo"},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Error handling
# ─────────────────────────────────────────────────────────────────────────────


class TestAIUniverseFilterErrors:
    def test_missing_api_key_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Factory lanza ValueError (OPENAI_API_KEY no configurada) → HTTP 400."""
        def _factory_raises():
            raise ValueError("OPENAI_API_KEY not set")

        monkeypatch.setattr(_main_module, "_get_openai_profile_client", _factory_raises)
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = _post(client)
        assert resp.status_code == 400
        assert "OPENAI_API_KEY" in resp.json()["detail"]

    def test_import_error_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Factory lanza ImportError (openai no instalado) → HTTP 400."""
        def _factory_raises():
            raise ImportError("openai not installed")

        monkeypatch.setattr(_main_module, "_get_openai_profile_client", _factory_raises)
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = _post(client)
        assert resp.status_code == 400

    def test_ai_value_error_returns_502(
        self, client_raises_on_prefs: TestClient
    ) -> None:
        """extract_investment_preferences lanza ValueError → HTTP 502."""
        resp = _post(client_raises_on_prefs)
        assert resp.status_code == 502
        assert "AI investment preference extraction failed" in resp.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Existing endpoints unaffected
# ─────────────────────────────────────────────────────────────────────────────


class TestExistingEndpointsUnaffected:
    def test_health_endpoint_still_works(self) -> None:
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ai_investment_preferences_still_routable(self) -> None:
        """/ai/investment-preferences returns 400 (no key) not 404 — route still registered."""
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = client.post(
            "/ai/investment-preferences",
            json={
                "client_id": "X",
                "natural_language_preferences": "algo",
            },
        )
        assert resp.status_code == 400

    def test_universe_filter_demo_still_works(self) -> None:
        """/universe/filter-demo (no AI) returns 200 with empty body."""
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = client.post("/universe/filter-demo", json={})
        assert resp.status_code == 200
        assert resp.json()["eligible_count"] >= 20
