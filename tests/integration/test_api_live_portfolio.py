"""
Tests de integración para POST /live/portfolio-demo.

NO llaman a internet real. Se inyecta un proveedor fake via monkeypatch
sobre risk_first_advisory.api_layer.main._make_live_provider.

Estructura:
    - _FakeProvider        : proveedor que devuelve snapshots pre-construidos.
    - _make_fake_snapshot  : factory de MarketDataSnapshot válidos.
    - Fixtures             : client, fake_provider, client_with_fake.
    - Clases de tests      : Response básica, candidatos, metadata,
                             insuficiencia de datos, infactibilidad,
                             serialización, endpoints existentes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────────────
# Fake provider helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_fake_snapshot(
    ticker: str,
    asset_class: str,
    expected_return: float = 0.08,
    volatility: float = 0.15,
    liquidity_score: float = 0.9,
):
    """Crea un MarketDataSnapshot válido y usable sin internet."""
    from risk_first_advisory.data_layer.market_data import MarketDataSnapshot

    return MarketDataSnapshot(
        ticker=ticker,
        expected_return_annual=expected_return,
        volatility_annual=volatility,
        liquidity_score=liquidity_score,
        expense_ratio=0.0,
        duration=None,
        asset_class=asset_class,
        currency="USD",
        stale=False,
        missing_fields=["expense_ratio"],   # non-critical → is_usable=True
        notes=["source=test"],
    )


# Universo fake: 9 instrumentos.
# "moderado" tiene max_single_asset=0.15 → necesita N >= ceil(1/0.15) = 7 activos
# para que los pesos sumen 1.0. Usamos 9 para margen.
_FAKE_SNAPSHOTS: dict[str, Any] = {
    "BIL": _make_fake_snapshot("BIL", "cash",      expected_return=0.040, volatility=0.005),
    "SHV": _make_fake_snapshot("SHV", "cash",      expected_return=0.040, volatility=0.004),
    "AGG": _make_fake_snapshot("AGG", "bond",      expected_return=0.050, volatility=0.045),
    "BND": _make_fake_snapshot("BND", "bond",      expected_return=0.050, volatility=0.048),
    "IEF": _make_fake_snapshot("IEF", "bond",      expected_return=0.055, volatility=0.070),
    "VTI": _make_fake_snapshot("VTI", "equity",    expected_return=0.100, volatility=0.175),
    "SPY": _make_fake_snapshot("SPY", "equity",    expected_return=0.100, volatility=0.172),
    "VEA": _make_fake_snapshot("VEA", "equity",    expected_return=0.080, volatility=0.160),
    "GLD": _make_fake_snapshot("GLD", "commodity", expected_return=0.060, volatility=0.140),
}


class _FakeProvider:
    """
    Proveedor fake que devuelve snapshots pre-construidos sin llamar a yfinance.

    Los tickers no presentes en el mapa devuelven None (sin datos).
    """

    def __init__(self, snapshots_map: dict):
        self._map = snapshots_map

    def get_snapshot(self, ticker: str):
        return self._map.get(ticker)

    def get_many(self, tickers: list[str]) -> list:
        return [s for t in tickers if (s := self._map.get(t)) is not None]

    def contains(self, ticker: str) -> bool:
        return ticker in self._map

    def __len__(self) -> int:
        return len(self._map)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    """TestClient limpio sin monkeypatching."""
    import risk_first_advisory.api_layer.main as main_module

    return TestClient(main_module.app)


@pytest.fixture
def fake_provider() -> _FakeProvider:
    return _FakeProvider(_FAKE_SNAPSHOTS)


@pytest.fixture
def client_with_fake(monkeypatch: pytest.MonkeyPatch, fake_provider: _FakeProvider) -> TestClient:
    """
    TestClient con _make_live_provider monkeypatched para devolver el fake provider.
    Ningún test que use este fixture llama a internet.
    """
    import risk_first_advisory.api_layer.main as main_module

    monkeypatch.setattr(
        main_module,
        "_make_live_provider",
        lambda period, interval: fake_provider,
    )
    return TestClient(main_module.app)


@pytest.fixture
def live_response(client_with_fake: TestClient) -> dict:
    """Ejecuta POST /live/portfolio-demo una vez y cachea la respuesta."""
    response = client_with_fake.post(
        "/live/portfolio-demo",
        json={"profile": "moderado", "period": "3y", "interval": "1d"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# Tests: respuesta HTTP básica
# ─────────────────────────────────────────────────────────────────────────────


class TestLivePortfolioDemoBasic:
    def test_returns_200_with_fake_provider(self, client_with_fake: TestClient):
        response = client_with_fake.post(
            "/live/portfolio-demo",
            json={"profile": "moderado"},
        )
        assert response.status_code == 200

    def test_default_profile_used_when_not_supplied(self, client_with_fake: TestClient):
        """POST sin body usa los defaults (profile=moderado)."""
        response = client_with_fake.post("/live/portfolio-demo", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["profile"] == "moderado"

    def test_invalid_profile_returns_422(self, client_with_fake: TestClient):
        response = client_with_fake.post(
            "/live/portfolio-demo",
            json={"profile": "inventado"},
        )
        assert response.status_code == 422

    def test_period_and_interval_echoed_in_response(self, live_response: dict):
        assert live_response["period"] == "3y"
        assert live_response["interval"] == "1d"


# ─────────────────────────────────────────────────────────────────────────────
# Tests: campos de la respuesta completed
# ─────────────────────────────────────────────────────────────────────────────


class TestLivePortfolioDemoResponse:
    def test_status_is_completed(self, live_response: dict):
        assert live_response["status"] == "completed"

    def test_candidate_count_is_positive(self, live_response: dict):
        assert live_response["candidate_count"] > 0

    def test_candidates_is_list(self, live_response: dict):
        assert isinstance(live_response["candidates"], list)

    def test_candidate_count_matches_candidates_length(self, live_response: dict):
        assert live_response["candidate_count"] == len(live_response["candidates"])

    def test_total_tickers_is_eleven(self, live_response: dict):
        assert live_response["total_tickers"] == 11

    def test_usable_snapshots_positive(self, live_response: dict):
        assert live_response["usable_snapshots"] > 0

    def test_failed_or_missing_non_negative(self, live_response: dict):
        assert live_response["failed_or_missing"] >= 0

    def test_total_tickers_equals_usable_plus_failed(self, live_response: dict):
        assert (
            live_response["usable_snapshots"] + live_response["failed_or_missing"]
            == live_response["total_tickers"]
        )

    def test_dq_warnings_is_list(self, live_response: dict):
        assert isinstance(live_response["dq_warnings"], list)

    def test_message_is_non_empty_string(self, live_response: dict):
        assert isinstance(live_response["message"], str)
        assert live_response["message"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: estructura de candidatos
# ─────────────────────────────────────────────────────────────────────────────


class TestLivePortfolioCandidates:
    def test_candidate_has_variant_field(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "variant" in candidate
        assert isinstance(candidate["variant"], str)

    def test_candidate_has_objective_field(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "objective" in candidate
        assert isinstance(candidate["objective"], str)

    def test_candidate_has_expected_return(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "expected_return_annual" in candidate
        assert isinstance(candidate["expected_return_annual"], float)

    def test_candidate_has_volatility(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "volatility_annual" in candidate
        assert isinstance(candidate["volatility_annual"], float)

    def test_candidate_has_risk_score(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "risk_score" in candidate
        assert isinstance(candidate["risk_score"], float)

    def test_candidate_has_constraints_satisfied(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "constraints_satisfied" in candidate
        assert isinstance(candidate["constraints_satisfied"], bool)

    def test_candidate_has_weights(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "weights" in candidate
        assert isinstance(candidate["weights"], list)

    def test_candidate_weights_have_ticker_and_weight(self, live_response: dict):
        for candidate in live_response["candidates"]:
            for w in candidate["weights"]:
                assert "ticker" in w
                assert "weight" in w
                assert isinstance(w["ticker"], str)
                assert isinstance(w["weight"], float)

    def test_candidate_weights_are_sorted_descending(self, live_response: dict):
        for candidate in live_response["candidates"]:
            weights = [w["weight"] for w in candidate["weights"]]
            assert weights == sorted(weights, reverse=True), (
                f"Pesos no ordenados en variante {candidate['variant']}: {weights}"
            )

    def test_candidate_weights_are_positive(self, live_response: dict):
        for candidate in live_response["candidates"]:
            for w in candidate["weights"]:
                assert w["weight"] > 0.0

    def test_candidate_has_reason_codes_list(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "reason_codes" in candidate
        assert isinstance(candidate["reason_codes"], list)

    def test_candidate_has_notes_list(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "notes" in candidate
        assert isinstance(candidate["notes"], list)

    def test_candidates_in_canonical_order(self, live_response: dict):
        """Orden canónico: DEFENSIVE antes que BALANCED antes que GROWTH."""
        canonical = ["DEFENSIVE", "BALANCED", "GROWTH"]
        variants = [c["variant"] for c in live_response["candidates"]]
        ordered = [v for v in canonical if v in variants]
        assert variants == ordered


# ─────────────────────────────────────────────────────────────────────────────
# Tests: metadata de variantes
# ─────────────────────────────────────────────────────────────────────────────


class TestLivePortfolioMetadata:
    def test_candidate_has_metadata(self, live_response: dict):
        candidate = live_response["candidates"][0]
        assert "metadata" in candidate
        assert isinstance(candidate["metadata"], dict)

    def test_metadata_has_required_fields(self, live_response: dict):
        meta = live_response["candidates"][0]["metadata"]
        assert "risk_budget_exceeded" in meta
        assert "requires_advisor_override" in meta
        assert "exceeded_constraints" in meta
        assert "reason_codes" in meta
        assert "notes" in meta

    def test_metadata_booleans_are_bool(self, live_response: dict):
        for candidate in live_response["candidates"]:
            meta = candidate["metadata"]
            assert isinstance(meta["risk_budget_exceeded"], bool)
            assert isinstance(meta["requires_advisor_override"], bool)

    def test_metadata_lists_are_lists(self, live_response: dict):
        for candidate in live_response["candidates"]:
            meta = candidate["metadata"]
            assert isinstance(meta["exceeded_constraints"], list)
            assert isinstance(meta["reason_codes"], list)
            assert isinstance(meta["notes"], list)

    def test_defensive_and_balanced_do_not_require_override(self, live_response: dict):
        """DEFENSIVE y BALANCED nunca deben tener requires_advisor_override=True."""
        for candidate in live_response["candidates"]:
            if candidate["variant"] in ("DEFENSIVE", "BALANCED"):
                assert candidate["metadata"]["requires_advisor_override"] is False, (
                    f"Variante {candidate['variant']} no debería requerir override"
                )

    def test_growth_requires_advisor_override_when_present(self, live_response: dict):
        """
        GROWTH siempre relaja max_volatility → requires_advisor_override=True.
        Si GROWTH no está generado (infactible), el test es vacuamente verdadero.
        """
        growth_list = [c for c in live_response["candidates"] if c["variant"] == "GROWTH"]
        for growth in growth_list:
            assert growth["metadata"]["requires_advisor_override"] is True
            assert "max_volatility" in growth["metadata"]["exceeded_constraints"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: status insufficient_data
# ─────────────────────────────────────────────────────────────────────────────


class TestLivePortfolioInsufficientData:
    @pytest.fixture
    def client_with_scarce_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> TestClient:
        """Proveedor con solo 2 snapshots → insufficient_data."""
        import risk_first_advisory.api_layer.main as main_module

        scarce_map = {
            "VTI": _FAKE_SNAPSHOTS["VTI"],
            "SPY": _FAKE_SNAPSHOTS["SPY"],
        }
        monkeypatch.setattr(
            main_module,
            "_make_live_provider",
            lambda period, interval: _FakeProvider(scarce_map),
        )
        return TestClient(main_module.app)

    def test_insufficient_data_returns_200(
        self, client_with_scarce_provider: TestClient
    ):
        response = client_with_scarce_provider.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        )
        assert response.status_code == 200

    def test_insufficient_data_status(self, client_with_scarce_provider: TestClient):
        data = client_with_scarce_provider.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        ).json()
        assert data["status"] == "insufficient_data"

    def test_insufficient_data_candidates_empty(
        self, client_with_scarce_provider: TestClient
    ):
        data = client_with_scarce_provider.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        ).json()
        assert data["candidates"] == []
        assert data["candidate_count"] == 0

    def test_insufficient_data_message_is_informative(
        self, client_with_scarce_provider: TestClient
    ):
        data = client_with_scarce_provider.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        ).json()
        assert data["message"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: status infeasible
# ─────────────────────────────────────────────────────────────────────────────


class TestLivePortfolioInfeasible:
    @pytest.fixture
    def client_with_infeasible_coordinator(
        self, monkeypatch: pytest.MonkeyPatch, fake_provider: _FakeProvider
    ) -> TestClient:
        """
        Provider fake con datos válidos, pero PortfolioGenerationCoordinator.generate
        monkeypatched para lanzar ValueError → status infeasible.
        """
        import risk_first_advisory.api_layer.main as main_module
        from risk_first_advisory.portfolio_layer import generation as gen_module

        monkeypatch.setattr(
            main_module,
            "_make_live_provider",
            lambda period, interval: fake_provider,
        )
        monkeypatch.setattr(
            gen_module.PortfolioGenerationCoordinator,
            "generate",
            lambda self, **kwargs: (_ for _ in ()).throw(
                ValueError("Ninguna variante factible")
            ),
        )
        return TestClient(main_module.app)

    def test_infeasible_returns_200(self, client_with_infeasible_coordinator: TestClient):
        response = client_with_infeasible_coordinator.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        )
        assert response.status_code == 200

    def test_infeasible_status(self, client_with_infeasible_coordinator: TestClient):
        data = client_with_infeasible_coordinator.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        ).json()
        assert data["status"] == "infeasible"

    def test_infeasible_candidates_empty(
        self, client_with_infeasible_coordinator: TestClient
    ):
        data = client_with_infeasible_coordinator.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        ).json()
        assert data["candidates"] == []
        assert data["candidate_count"] == 0

    def test_infeasible_message_contains_info(
        self, client_with_infeasible_coordinator: TestClient
    ):
        data = client_with_infeasible_coordinator.post(
            "/live/portfolio-demo", json={"profile": "moderado"}
        ).json()
        assert data["message"]


# ─────────────────────────────────────────────────────────────────────────────
# Tests: serialización
# ─────────────────────────────────────────────────────────────────────────────


class TestLivePortfolioSerialization:
    def test_response_is_json_serializable(self, live_response: dict):
        # No debe lanzar.
        json.dumps(live_response)

    def test_no_raw_python_objects_in_json(self, live_response: dict):
        serialized = json.dumps(live_response)
        assert "<" not in serialized
        assert "PortfolioVariant" not in serialized
        assert "OptimizationObjective" not in serialized

    def test_variant_values_are_strings(self, live_response: dict):
        for candidate in live_response["candidates"]:
            assert isinstance(candidate["variant"], str)
            assert candidate["variant"] in ("DEFENSIVE", "BALANCED", "GROWTH")

    def test_objective_values_are_strings(self, live_response: dict):
        valid_objectives = {"MIN_VARIANCE", "MAX_UTILITY", "MAX_RETURN"}
        for candidate in live_response["candidates"]:
            assert candidate["objective"] in valid_objectives

    def test_all_list_fields_contain_correct_types(self, live_response: dict):
        assert all(isinstance(w, str) for w in live_response["dq_warnings"])
        for candidate in live_response["candidates"]:
            assert all(isinstance(rc, str) for rc in candidate["reason_codes"])
            assert all(isinstance(n, str) for n in candidate["notes"])


# ─────────────────────────────────────────────────────────────────────────────
# Tests: endpoints existentes no rotos
# ─────────────────────────────────────────────────────────────────────────────


class TestExistingEndpointsUnaffected:
    def test_health_still_returns_ok(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_service_name_unchanged(self, client: TestClient):
        response = client.get("/health")
        assert response.json()["service"] == "risk-first-advisory"

    def test_list_workflows_still_returns_200(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setattr(main_module, "DEFAULT_DB_PATH", tmp_path / "t.db")
        client = TestClient(main_module.app)
        response = client.get("/workflow")
        assert response.status_code == 200
