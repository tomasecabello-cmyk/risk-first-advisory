"""
Integration tests for POST /ai/filtered-portfolio-demo.

Pipeline: lenguaje natural → OpenAI (mocked) → PreferenceFilterEngine
         → InstrumentMarketDataAdapter → RiskBudget
         → PortfolioGenerationCoordinator → response.

No llaman a OpenAI real. Se monkeypatchea
risk_first_advisory.api_layer.main._get_openai_profile_client
para devolver un _FakeAIClient con respuestas pre-construidas.

Fixture de universo: tests/fixtures/universe/sample_instrument_universe.csv (20 instrumentos).

AI response presets used in this file:
  _PASSTHROUGH_PREFS         — sin filtros activos → todos elegibles.
  _BALANZ_ONS_PREFS          — CORPORATE_BOND + USD + Argentina + Balanz + hard_dollar
                               + avoid Energy → 9 usable snapshots → "completed".
  _MONEY_MARKET_ONLY_PREFS   — solo MONEY_MARKET → 0 usable snapshots →
                               "blocked_insufficient_universe".
  _FIVE_SNAPSHOT_PREFS       — CORPORATE_BOND + max_maturity=2028 + min_liq=0.65
                               → 5 usable snapshots; con perfil "conservador"
                               (max_single_asset=15% → requires 7) →
                               "blocked_insufficient_diversification_capacity".
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module

_URL = "/ai/filtered-portfolio-demo"

# ─────────────────────────────────────────────────────────────────────────────
# AI response presets
# ─────────────────────────────────────────────────────────────────────────────


def _passthrough_prefs(**overrides) -> dict[str, Any]:
    """Sin filtros activos → todos los instrumentos elegibles."""
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
    ONs hard dollar argentinas en Balanz, evitar Energy.
    → 9 eligible CORPORATE_BONDs, all usable → "completed" with moderado.
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
        "min_liquidity_score": None,
        "max_maturity_year": None,
        "hard_constraints": ["instrument_type", "currency", "country", "hard_dollar", "entity", "sector"],
        "soft_preferences": [],
        "unparsed_preferences": [],
        "confidence": 0.92,
        "advisor_notes": ["Client explicitly excluded energy sector."],
    }
    base.update(overrides)
    return base


def _money_market_only_prefs(**overrides) -> dict[str, Any]:
    """
    Solo MONEY_MARKET → FIMA y BONO0 elegibles, ninguno con ytm →
    0 snapshots usables → "blocked_insufficient_universe".
    """
    base: dict[str, Any] = {
        "allowed_instrument_types": ["MONEY_MARKET"],
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
        "hard_constraints": ["instrument_type"],
        "soft_preferences": [],
        "unparsed_preferences": [],
        "confidence": 0.90,
        "advisor_notes": [],
    }
    base.update(overrides)
    return base


def _five_snapshot_prefs(**overrides) -> dict[str, Any]:
    """
    CORPORATE_BOND + max_maturity=2028 + min_liquidity=0.65
    → 5 usable snapshots (YCPDO, GALI28, PAMP27, AERO27, SUPV28).
    Con perfil "conservador" (max_single_asset=15% → requires 7):
    → "blocked_insufficient_diversification_capacity".
    """
    base: dict[str, Any] = {
        "allowed_instrument_types": ["CORPORATE_BOND"],
        "excluded_instrument_types": [],
        "currency": None,
        "country": None,
        "entity": None,
        "hard_dollar_only": None,
        "avoid_sectors": [],
        "prefer_sectors": [],
        "avoid_issuers": [],
        "prefer_issuers": [],
        "min_liquidity_score": 0.65,
        "max_maturity_year": 2028,
        "hard_constraints": [],
        "soft_preferences": [],
        "unparsed_preferences": [],
        "confidence": 0.80,
        "advisor_notes": [],
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
def client_balanz_ons(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """9 Balanz ONs non-Energy → usable → completed."""
    fake = _FakeAIClient(preferences_response=_balanz_ons_prefs())
    monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(_main_module.app, raise_server_exceptions=False)


@pytest.fixture
def client_no_usable(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """MONEY_MARKET only → 0 usable snapshots → blocked_insufficient_universe."""
    fake = _FakeAIClient(preferences_response=_money_market_only_prefs())
    monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(_main_module.app, raise_server_exceptions=False)


@pytest.fixture
def client_five_snapshots(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """5 usable snapshots → blocked_insufficient_diversification_capacity (conservador)."""
    fake = _FakeAIClient(preferences_response=_five_snapshot_prefs())
    monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(_main_module.app, raise_server_exceptions=False)


@pytest.fixture
def client_raises_on_prefs(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """AI lanza ValueError → espera HTTP 502."""
    fake = _FakeAIClient(raise_on_preferences=True)
    monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(_main_module.app, raise_server_exceptions=False)


# Payload mínimo válido (happy path)
_VALID_PAYLOAD: dict = {
    "client_id": "CLI-TEST-PORT-001",
    "profile": "moderado",
    "natural_language_preferences": "Solo quiero ONs hard dollar argentinas en Balanz.",
}

_CONSERVADOR_PAYLOAD: dict = {
    "client_id": "CLI-TEST-PORT-002",
    "profile": "conservador",
    "natural_language_preferences": "Quiero algo conservador.",
}


def _post(client: TestClient, body: dict = _VALID_PAYLOAD) -> Any:
    return client.post(_URL, json=body)


# ─────────────────────────────────────────────────────────────────────────────
# Response structure
# ─────────────────────────────────────────────────────────────────────────────


class TestAIFilteredPortfolioStructure:
    def test_returns_200_completed(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_response_includes_client_id(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["client_id"] == "CLI-TEST-PORT-001"

    def test_response_includes_profile(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["profile"] == "moderado"

    def test_response_includes_preferences(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        assert "preferences" in data
        assert isinstance(data["preferences"], dict)
        assert data["preferences"]["client_id"] == "CLI-TEST-PORT-001"

    def test_preferences_contains_entity(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["preferences"]["entity"] == "Balanz"

    def test_preferences_contains_currency(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["preferences"]["currency"] == "USD"

    def test_preferences_contains_avoid_sectors(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert "Energy" in resp.json()["preferences"]["avoid_sectors"]

    def test_response_includes_eligible_instruments(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        assert "eligible_instruments" in data
        assert isinstance(data["eligible_instruments"], list)
        assert len(data["eligible_instruments"]) >= 7

    def test_eligible_instruments_are_non_energy_corporate_bonds(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(client_balanz_ons)
        for inst in resp.json()["eligible_instruments"]:
            assert inst["instrument_type"] == "CORPORATE_BOND"
            assert inst["sector"] != "Energy"
            assert "Balanz" in inst["available_entities"]

    def test_response_includes_exclusions(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        assert "exclusions" in data
        assert isinstance(data["exclusions"], list)

    def test_response_includes_applied_filters(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert isinstance(resp.json()["applied_filters"], list)

    def test_response_includes_warnings(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert "warnings" in resp.json()

    def test_response_includes_snapshots(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        assert "snapshots" in data
        assert isinstance(data["snapshots"], list)
        assert len(data["snapshots"]) >= 7

    def test_snapshot_shape(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        snap = resp.json()["snapshots"][0]
        required = {"ticker", "expected_return_annual", "volatility_annual", "duration",
                    "liquidity_score", "notes"}
        assert required.issubset(snap.keys())

    def test_snapshot_count_matches_snapshots_list(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        assert data["snapshot_count"] == len(data["snapshots"])

    def test_response_includes_message(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert isinstance(resp.json()["message"], str)
        assert len(resp.json()["message"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Candidates
# ─────────────────────────────────────────────────────────────────────────────


class TestAIFilteredPortfolioCandidates:
    def test_candidate_count_at_least_one(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        assert resp.json()["candidate_count"] >= 1

    def test_candidate_count_matches_candidates_list(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        data = resp.json()
        assert data["candidate_count"] == len(data["candidates"])

    def test_balanced_appears_in_candidates(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        variants = [c["variant"] for c in resp.json()["candidates"]]
        assert "BALANCED" in variants

    def test_growth_appears_or_status_completed(self, client_balanz_ons: TestClient) -> None:
        """GROWTH may require advisor override but should still be generated."""
        resp = _post(client_balanz_ons)
        data = resp.json()
        assert data["status"] == "completed"
        variants = [c["variant"] for c in data["candidates"]]
        # GROWTH may or may not be generated depending on optimizer feasibility;
        # if present, verify it has the expected shape.
        if "GROWTH" in variants:
            growth = next(c for c in data["candidates"] if c["variant"] == "GROWTH")
            assert "expected_return_annual" in growth
            assert "volatility_annual" in growth
            assert "weights" in growth

    def test_growth_metadata_if_exceeds_risk_budget(self, client_balanz_ons: TestClient) -> None:
        """If GROWTH exists and exceeds the risk budget, it requires advisor override."""
        resp = _post(client_balanz_ons)
        candidates = resp.json()["candidates"]
        growth_candidates = [c for c in candidates if c["variant"] == "GROWTH"]
        for growth in growth_candidates:
            if not growth["constraints_satisfied"]:
                assert growth["metadata"]["requires_advisor_override"] is True

    def test_candidate_shape(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        cand = resp.json()["candidates"][0]
        required = {
            "variant", "objective", "expected_return_annual", "volatility_annual",
            "risk_score", "constraints_satisfied", "metadata", "weights",
        }
        assert required.issubset(cand.keys())

    def test_candidate_weights_sum_to_one(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        for cand in resp.json()["candidates"]:
            total = sum(w["weight"] for w in cand["weights"])
            assert abs(total - 1.0) < 1e-4, f"{cand['variant']}: weights sum={total}"

    def test_candidate_weights_all_positive(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        for cand in resp.json()["candidates"]:
            for w in cand["weights"]:
                assert w["weight"] > 0

    def test_candidate_weights_all_eligible_tickers(self, client_balanz_ons: TestClient) -> None:
        """All weight tickers must be among the eligible instruments."""
        resp = _post(client_balanz_ons)
        data = resp.json()
        eligible_tickers = {i["ticker"] for i in data["eligible_instruments"]}
        for cand in data["candidates"]:
            for w in cand["weights"]:
                assert w["ticker"] in eligible_tickers, (
                    f"Unexpected ticker {w['ticker']} not in eligible universe"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Blocked scenarios
# ─────────────────────────────────────────────────────────────────────────────


class TestAIFilteredPortfolioBlocked:
    def test_insufficient_universe_returns_200(self, client_no_usable: TestClient) -> None:
        resp = _post(client_no_usable)
        assert resp.status_code == 200

    def test_insufficient_universe_status(self, client_no_usable: TestClient) -> None:
        resp = _post(client_no_usable)
        assert resp.json()["status"] == "blocked_insufficient_universe"

    def test_insufficient_universe_candidates_empty(self, client_no_usable: TestClient) -> None:
        resp = _post(client_no_usable)
        assert resp.json()["candidates"] == []
        assert resp.json()["candidate_count"] == 0

    def test_insufficient_universe_still_includes_preferences(
        self, client_no_usable: TestClient
    ) -> None:
        resp = _post(client_no_usable)
        assert "preferences" in resp.json()
        assert resp.json()["preferences"]["client_id"] == "CLI-TEST-PORT-001"

    def test_insufficient_universe_message_not_empty(self, client_no_usable: TestClient) -> None:
        resp = _post(client_no_usable)
        assert len(resp.json()["message"]) > 0

    def test_insufficient_diversification_status(
        self, client_five_snapshots: TestClient
    ) -> None:
        """5 usable snapshots, conservador profile requires 7 → blocked."""
        resp = _post(client_five_snapshots, body=_CONSERVADOR_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["status"] == "blocked_insufficient_diversification_capacity"

    def test_insufficient_diversification_candidates_empty(
        self, client_five_snapshots: TestClient
    ) -> None:
        resp = _post(client_five_snapshots, body=_CONSERVADOR_PAYLOAD)
        assert resp.json()["candidates"] == []
        assert resp.json()["candidate_count"] == 0

    def test_insufficient_diversification_snapshot_count(
        self, client_five_snapshots: TestClient
    ) -> None:
        """5 snapshots should be reported (the filter produces exactly 5 CORPORATE_BONDs)."""
        resp = _post(client_five_snapshots, body=_CONSERVADOR_PAYLOAD)
        assert resp.json()["snapshot_count"] == 5

    def test_insufficient_diversification_message_mentions_profile(
        self, client_five_snapshots: TestClient
    ) -> None:
        resp = _post(client_five_snapshots, body=_CONSERVADOR_PAYLOAD)
        msg = resp.json()["message"]
        assert "conservador" in msg or "7" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Error handling
# ─────────────────────────────────────────────────────────────────────────────


class TestAIFilteredPortfolioErrors:
    def test_missing_api_key_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _factory_raises():
            raise ValueError("OPENAI_API_KEY not set")

        monkeypatch.setattr(_main_module, "_get_openai_profile_client", _factory_raises)
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = _post(client)
        assert resp.status_code == 400
        assert "OPENAI_API_KEY" in resp.json()["detail"]

    def test_import_error_returns_400(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _factory_raises():
            raise ImportError("openai not installed")

        monkeypatch.setattr(_main_module, "_get_openai_profile_client", _factory_raises)
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = _post(client)
        assert resp.status_code == 400

    def test_ai_value_error_returns_502(self, client_raises_on_prefs: TestClient) -> None:
        resp = _post(client_raises_on_prefs)
        assert resp.status_code == 502
        assert "AI investment preference extraction failed" in resp.json()["detail"]

    def test_invalid_profile_returns_422(self, client_balanz_ons: TestClient) -> None:
        resp = _post(
            client_balanz_ons,
            body={
                "client_id": "CLI-X",
                "profile": "ultra_agresivo_inventado",
                "natural_language_preferences": "algo",
            },
        )
        assert resp.status_code == 422

    def test_invalid_profile_detail_mentions_valid_profiles(
        self, client_balanz_ons: TestClient
    ) -> None:
        resp = _post(
            client_balanz_ons,
            body={
                "client_id": "CLI-X",
                "profile": "no_existe",
                "natural_language_preferences": "algo",
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        # detail may be a string or a list (FastAPI validation vs our HTTPException)
        detail_str = json.dumps(detail)
        assert "no_existe" in detail_str or "válid" in detail_str.lower() or "valid" in detail_str.lower()

    def test_empty_client_id_returns_422(self, client_balanz_ons: TestClient) -> None:
        resp = _post(
            client_balanz_ons,
            body={
                "client_id": "",
                "profile": "moderado",
                "natural_language_preferences": "algo",
            },
        )
        assert resp.status_code == 422

    def test_empty_natural_language_returns_422(self, client_balanz_ons: TestClient) -> None:
        resp = _post(
            client_balanz_ons,
            body={
                "client_id": "CLI-X",
                "profile": "moderado",
                "natural_language_preferences": "",
            },
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────────────────


class TestAIFilteredPortfolioSerialization:
    def test_response_json_serializable(self, client_balanz_ons: TestClient) -> None:
        resp = _post(client_balanz_ons)
        serialised = json.dumps(resp.json())
        reloaded = json.loads(serialised)
        assert reloaded["status"] == "completed"
        assert reloaded["client_id"] == "CLI-TEST-PORT-001"

    def test_blocked_response_json_serializable(self, client_no_usable: TestClient) -> None:
        resp = _post(client_no_usable)
        serialised = json.dumps(resp.json())
        reloaded = json.loads(serialised)
        assert reloaded["status"] == "blocked_insufficient_universe"


# ─────────────────────────────────────────────────────────────────────────────
# Existing endpoints unaffected
# ─────────────────────────────────────────────────────────────────────────────


class TestExistingEndpointsUnaffected:
    def test_health_still_works(self) -> None:
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_universe_filter_demo_still_works(self) -> None:
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = client.post("/universe/filter-demo", json={})
        assert resp.status_code == 200
        assert resp.json()["eligible_count"] >= 20

    def test_ai_filter_universe_demo_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeAIClient(preferences_response=_passthrough_prefs())
        monkeypatch.setattr(_main_module, "_get_openai_profile_client", lambda: fake)
        client = TestClient(_main_module.app, raise_server_exceptions=False)
        resp = client.post(
            "/ai/filter-universe-demo",
            json={
                "client_id": "CLI-CHECK",
                "natural_language_preferences": "cualquier cosa",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["eligible_count"] == 20
