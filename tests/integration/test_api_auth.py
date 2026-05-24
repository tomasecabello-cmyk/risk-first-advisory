"""
Integration tests for the Phase-1 advisor-auth scaffold.

Cubre:
    - GET /auth/me — happy path con tokens demo + variantes de error 401.
    - Garantía de NO regresión: los endpoints existentes (health, universe,
      ai/filtered-portfolio-demo) siguen funcionando SIN token.

No usa OpenAI real (monkeypatch del cliente AI). No escribe en data/demo_api.db
(monkeypatch de DEFAULT_DB_PATH a tmp_path).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import risk_first_advisory.api_layer.main as _main_module


_AUTH_URL = "/auth/me"
_GENERIC_AUTH_ERROR = "Invalid or missing advisor authentication token."


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    """TestClient sin monkeypatch de auth: usa los tokens demo reales."""
    return TestClient(_main_module.app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# /auth/me — missing or malformed header
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthMeMissingOrMalformed:
    def test_no_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(_AUTH_URL)
        assert resp.status_code == 401

    def test_no_token_uses_generic_error(self, client: TestClient) -> None:
        resp = client.get(_AUTH_URL)
        assert resp.json()["detail"] == _GENERIC_AUTH_ERROR

    def test_no_token_includes_www_authenticate_header(self, client: TestClient) -> None:
        resp = client.get(_AUTH_URL)
        # RFC 6750 — challenge header con esquema Bearer.
        assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")

    def test_empty_authorization_header_returns_401(self, client: TestClient) -> None:
        resp = client.get(_AUTH_URL, headers={"Authorization": ""})
        assert resp.status_code == 401
        assert resp.json()["detail"] == _GENERIC_AUTH_ERROR

    def test_whitespace_only_authorization_header_returns_401(
        self, client: TestClient
    ) -> None:
        resp = client.get(_AUTH_URL, headers={"Authorization": "   "})
        assert resp.status_code == 401

    def test_bearer_without_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(_AUTH_URL, headers={"Authorization": "Bearer"})
        assert resp.status_code == 401

    def test_bearer_with_empty_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(_AUTH_URL, headers={"Authorization": "Bearer "})
        assert resp.status_code == 401

    def test_wrong_scheme_basic_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "Basic dev-advisor-token"}
        )
        assert resp.status_code == 401

    def test_wrong_scheme_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "Token dev-advisor-token"}
        )
        assert resp.status_code == 401

    def test_bearer_with_spaces_in_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "Bearer dev advisor token"}
        )
        assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# /auth/me — invalid (unknown) token
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthMeInvalidToken:
    def test_unknown_token_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert resp.status_code == 401

    def test_unknown_token_uses_generic_error(self, client: TestClient) -> None:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert resp.json()["detail"] == _GENERIC_AUTH_ERROR

    def test_error_does_not_echo_token(self, client: TestClient) -> None:
        secret_looking_token = "definitely-a-secret-12345"
        resp = client.get(
            _AUTH_URL, headers={"Authorization": f"Bearer {secret_looking_token}"}
        )
        assert resp.status_code == 401
        # The token must NEVER appear anywhere in the response.
        body = resp.text
        assert secret_looking_token not in body
        for header_value in resp.headers.values():
            assert secret_looking_token not in header_value


# ─────────────────────────────────────────────────────────────────────────────
# /auth/me — happy path: demo advisor
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthMeAdvisorToken:
    @pytest.fixture
    def advisor_response(self, client: TestClient) -> Any:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "Bearer dev-advisor-token"}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_returns_200(self, advisor_response: dict) -> None:
        # advisor_response was built by a request that asserted 200.
        assert isinstance(advisor_response, dict)

    def test_returns_advisor_id_ADV_001(self, advisor_response: dict) -> None:
        assert advisor_response["advisor_id"] == "ADV-001"

    def test_returns_display_name(self, advisor_response: dict) -> None:
        assert advisor_response["display_name"] == "Demo Advisor"

    def test_returns_advisor_role(self, advisor_response: dict) -> None:
        assert advisor_response["roles"] == ["advisor"]

    def test_returns_null_firm_id(self, advisor_response: dict) -> None:
        assert advisor_response["firm_id"] is None

    def test_response_shape_is_stable(self, advisor_response: dict) -> None:
        expected_keys = {"advisor_id", "display_name", "firm_id", "roles"}
        assert set(advisor_response.keys()) == expected_keys


# ─────────────────────────────────────────────────────────────────────────────
# /auth/me — happy path: compliance role
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthMeComplianceToken:
    @pytest.fixture
    def compliance_response(self, client: TestClient) -> Any:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "Bearer dev-compliance-token"}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_returns_200(self, compliance_response: dict) -> None:
        assert isinstance(compliance_response, dict)

    def test_returns_advisor_id_CMP_001(self, compliance_response: dict) -> None:
        assert compliance_response["advisor_id"] == "CMP-001"

    def test_returns_compliance_role(self, compliance_response: dict) -> None:
        assert "compliance" in compliance_response["roles"]

    def test_returns_display_name(self, compliance_response: dict) -> None:
        assert compliance_response["display_name"] == "Demo Compliance"


# ─────────────────────────────────────────────────────────────────────────────
# Case-insensitive scheme
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthMeSchemeCase:
    """RFC 6750 — el esquema 'Bearer' es case-insensitive."""

    def test_lowercase_bearer_accepted(self, client: TestClient) -> None:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "bearer dev-advisor-token"}
        )
        assert resp.status_code == 200
        assert resp.json()["advisor_id"] == "ADV-001"

    def test_uppercase_bearer_accepted(self, client: TestClient) -> None:
        resp = client.get(
            _AUTH_URL, headers={"Authorization": "BEARER dev-advisor-token"}
        )
        assert resp.status_code == 200
        assert resp.json()["advisor_id"] == "ADV-001"


# ─────────────────────────────────────────────────────────────────────────────
# No regresión — endpoints existentes NO requieren auth todavía
# ─────────────────────────────────────────────────────────────────────────────


class TestExistingEndpointsDoNotRequireAuth:
    def test_health_works_without_token(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_works_with_token(self, client: TestClient) -> None:
        """Pasarle un token a /health no debería romper nada."""
        resp = client.get(
            "/health", headers={"Authorization": "Bearer dev-advisor-token"}
        )
        assert resp.status_code == 200

    def test_universe_filter_demo_works_without_token(
        self, client: TestClient
    ) -> None:
        resp = client.post("/universe/filter-demo", json={})
        assert resp.status_code == 200
        assert resp.json()["eligible_count"] >= 20

    def test_ai_filter_universe_demo_works_without_token(
        self, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ) -> None:
        fake = _make_fake_ai_client()
        monkeypatch.setattr(
            _main_module, "_get_openai_profile_client", lambda: fake
        )
        resp = client.post(
            "/ai/filter-universe-demo",
            json={
                "client_id": "CLI-NO-AUTH",
                "natural_language_preferences": "test",
            },
        )
        assert resp.status_code == 200

    def test_ai_filtered_portfolio_demo_works_without_token(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`/ai/filtered-portfolio-demo` debe seguir sin auth requerida.
        El test sólo verifica que NO devuelve 401 (no le importa el status final
        del pipeline; lo que importa es que auth no aplica aquí todavía)."""
        fake = _make_fake_ai_client()
        monkeypatch.setattr(
            _main_module, "_get_openai_profile_client", lambda: fake
        )
        # Redirigir SQLite a tmp_path para no contaminar data/demo_api.db.
        monkeypatch.setattr(
            _main_module, "DEFAULT_DB_PATH", tmp_path / "noauth_check.db"
        )

        resp = client.post(
            "/ai/filtered-portfolio-demo",
            json={
                "client_id": "CLI-NO-AUTH",
                "profile": "moderado",
                "natural_language_preferences": "test",
            },
        )
        # El status puede ser 200, 422 o 500 dependiendo del pipeline, pero
        # nunca debería ser 401: este endpoint NO exige auth en Fase 1.
        assert resp.status_code != 401


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_fake_ai_client():
    """FakeAIClient mínimo: extract_investment_preferences devuelve pass-through."""

    class _Fake:
        def extract_investment_preferences(self, _payload: dict) -> dict:
            return {
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

    return _Fake()
