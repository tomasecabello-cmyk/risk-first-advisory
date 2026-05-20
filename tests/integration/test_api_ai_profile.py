"""
Tests de integración para POST /ai/profile-demo.

No llaman a la API real de OpenAI. Se monkeypatchea
risk_first_advisory.api_layer.main._get_openai_profile_client
para devolver un cliente fake sin acceso a red.

Clases:
    TestAIProfileDemoBasic         — respuestas 200/422/400/502 básicas.
    TestAIProfileDemoResponseFields— todos los campos obligatorios.
    TestAIProfileDemoValidation    — validaciones de los campos del request.
    TestAIProfileDemoErrors        — comportamiento ante API key faltante y fallo IA.
    TestAIProfileDemoSerialization — respuesta JSON pura, sin raw objects.
    TestExistingEndpointsUnaffected— endpoints existentes siguen verdes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _valid_ai_response(**overrides) -> dict:
    base: dict[str, Any] = {
        "preliminary_profile": "moderado",
        "confidence": 0.78,
        "contradictions": [
            {
                "field": "risk_tolerance_score",
                "severity": "medium",
                "explanation": "High capacity but low tolerance.",
            }
        ],
        "follow_up_questions": ["¿Cuál es su horizonte real de inversión?"],
        "advisor_notes": ["Verificar coherencia entre tolerancia y liquidez."],
    }
    base.update(overrides)
    return base


def _valid_followup_response(**overrides) -> dict:
    base: dict[str, Any] = {
        "revised_profile": "moderado",
        "confidence": 0.86,
        "remaining_contradictions": [],
        "profile_change_reason": (
            "Client confirmed 15-year horizon with no near-term liquidity need. "
            "Profile confirmed as moderado."
        ),
        "advisor_notes": ["Follow-up resolved liquidity contradiction."],
    }
    base.update(overrides)
    return base


class _FakeAIClient:
    """
    Cliente fake que devuelve respuestas pre-construidas sin llamar a OpenAI.
    Soporta tanto analyze_kyc (para /ai/profile-demo) como
    analyze_follow_up (para /ai/profile-follow-up).
    """

    def __init__(
        self,
        response: dict | None = None,
        raise_value_error: bool = False,
        followup_response: dict | None = None,
        raise_on_followup: bool = False,
    ):
        self._response = response or _valid_ai_response()
        self._raise = raise_value_error
        self._followup_response = followup_response or _valid_followup_response()
        self._raise_on_followup = raise_on_followup

    def analyze_kyc(self, kyc_payload: dict) -> dict:
        if self._raise:
            raise ValueError("AI returned invalid JSON")
        return self._response

    def analyze_follow_up(self, payload: dict) -> dict:
        if self._raise_on_followup:
            raise ValueError("AI follow-up returned invalid response")
        return self._followup_response


# Payload de request mínimo y válido
_VALID_REQUEST: dict = {
    "client_id": "CLI-AI-TEST",
    "kyc_payload": {
        "risk_tolerance_score": 5,
        "risk_capacity_score": 7,
        "liquidity_need_score": 3,
        "investment_horizon_years": 10,
        "max_acceptable_drawdown_pct": 20.0,
        "investment_experience": "moderada",
        "income_stability": "stable",
        "net_worth": 200_000,
        "liquid_net_worth": 80_000,
    },
}

_VALID_REQUEST_FULL: dict = {
    "client_id": "CLI-AI-FULL",
    "kyc_payload": {
        **_VALID_REQUEST["kyc_payload"],
        "declared_return_expectation_pct": 10.0,
        "open_investment_goal": "Quiero ahorrar para la jubilación.",
        "open_risk_reaction": "Me preocupa perder más del 15%.",
        "open_past_experience": "Vendí en 2020 al ver las caídas.",
        "open_concerns": "Inflación y pérdida de capital.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    """TestClient limpio, sin monkeypatch."""
    import risk_first_advisory.api_layer.main as main_module

    return TestClient(main_module.app)


@pytest.fixture
def client_with_fake_ai(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient con _get_openai_profile_client devolviendo fake client válido."""
    import risk_first_advisory.api_layer.main as main_module

    fake = _FakeAIClient()
    monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
    return TestClient(main_module.app)


@pytest.fixture
def ai_response(client_with_fake_ai: TestClient) -> dict:
    """Ejecuta POST /ai/profile-demo con request mínimo y cachea la respuesta."""
    r = client_with_fake_ai.post("/ai/profile-demo", json=_VALID_REQUEST)
    assert r.status_code == 200, r.text
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileDemoBasic
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileDemoBasic:
    def test_returns_200_with_fake_client(self, client_with_fake_ai: TestClient):
        r = client_with_fake_ai.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 200

    def test_returns_200_with_full_payload(self, client_with_fake_ai: TestClient):
        r = client_with_fake_ai.post("/ai/profile-demo", json=_VALID_REQUEST_FULL)
        assert r.status_code == 200

    def test_missing_client_id_returns_422(self, client_with_fake_ai: TestClient):
        payload = {k: v for k, v in _VALID_REQUEST.items() if k != "client_id"}
        r = client_with_fake_ai.post("/ai/profile-demo", json=payload)
        assert r.status_code == 422

    def test_empty_client_id_returns_422(self, client_with_fake_ai: TestClient):
        payload = {**_VALID_REQUEST, "client_id": ""}
        r = client_with_fake_ai.post("/ai/profile-demo", json=payload)
        assert r.status_code == 422

    def test_missing_kyc_payload_returns_422(self, client_with_fake_ai: TestClient):
        r = client_with_fake_ai.post("/ai/profile-demo", json={"client_id": "X"})
        assert r.status_code == 422

    def test_client_id_is_echoed_in_response(self, client_with_fake_ai: TestClient):
        payload = {**_VALID_REQUEST, "client_id": "CLI-SPECIFIC-99"}
        r = client_with_fake_ai.post("/ai/profile-demo", json=payload)
        assert r.status_code == 200
        assert r.json()["client_id"] == "CLI-SPECIFIC-99"


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileDemoResponseFields
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileDemoResponseFields:
    def test_has_client_id(self, ai_response: dict):
        assert "client_id" in ai_response
        assert ai_response["client_id"] == "CLI-AI-TEST"

    def test_has_preliminary_profile(self, ai_response: dict):
        assert "preliminary_profile" in ai_response
        assert isinstance(ai_response["preliminary_profile"], str)
        assert ai_response["preliminary_profile"]

    def test_preliminary_profile_value(self, ai_response: dict):
        assert ai_response["preliminary_profile"] == "moderado"

    def test_has_confidence(self, ai_response: dict):
        assert "confidence" in ai_response
        assert isinstance(ai_response["confidence"], float)

    def test_confidence_in_range(self, ai_response: dict):
        assert 0.0 <= ai_response["confidence"] <= 1.0

    def test_confidence_value(self, ai_response: dict):
        assert ai_response["confidence"] == pytest.approx(0.78)

    def test_has_contradictions(self, ai_response: dict):
        assert "contradictions" in ai_response
        assert isinstance(ai_response["contradictions"], list)

    def test_contradiction_has_required_fields(self, ai_response: dict):
        for c in ai_response["contradictions"]:
            assert "field" in c
            assert "severity" in c
            assert "explanation" in c

    def test_contradiction_fields_are_strings(self, ai_response: dict):
        for c in ai_response["contradictions"]:
            assert isinstance(c["field"], str)
            assert isinstance(c["severity"], str)
            assert isinstance(c["explanation"], str)

    def test_has_follow_up_questions(self, ai_response: dict):
        assert "follow_up_questions" in ai_response
        assert isinstance(ai_response["follow_up_questions"], list)

    def test_follow_up_questions_are_strings(self, ai_response: dict):
        for q in ai_response["follow_up_questions"]:
            assert isinstance(q, str)

    def test_has_advisor_notes(self, ai_response: dict):
        assert "advisor_notes" in ai_response
        assert isinstance(ai_response["advisor_notes"], list)

    def test_advisor_notes_are_strings(self, ai_response: dict):
        for n in ai_response["advisor_notes"]:
            assert isinstance(n, str)

    def test_empty_contradictions_returned_correctly(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setattr(
            main_module,
            "_get_openai_profile_client",
            lambda: _FakeAIClient(_valid_ai_response(contradictions=[])),
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 200
        assert r.json()["contradictions"] == []

    def test_empty_follow_up_returned_correctly(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setattr(
            main_module,
            "_get_openai_profile_client",
            lambda: _FakeAIClient(_valid_ai_response(follow_up_questions=[])),
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 200
        assert r.json()["follow_up_questions"] == []


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileDemoValidation — validaciones de campos del request
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileDemoValidation:
    def _bad_kyc(self, **overrides) -> dict:
        kyc = dict(_VALID_REQUEST["kyc_payload"])
        kyc.update(overrides)
        return {"client_id": "CLI-X", "kyc_payload": kyc}

    def test_risk_tolerance_score_zero_returns_422(
        self, client_with_fake_ai: TestClient
    ):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(risk_tolerance_score=0)
        )
        assert r.status_code == 422

    def test_risk_tolerance_score_eleven_returns_422(
        self, client_with_fake_ai: TestClient
    ):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(risk_tolerance_score=11)
        )
        assert r.status_code == 422

    def test_risk_capacity_score_out_of_range_returns_422(
        self, client_with_fake_ai: TestClient
    ):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(risk_capacity_score=0)
        )
        assert r.status_code == 422

    def test_liquidity_need_score_out_of_range_returns_422(
        self, client_with_fake_ai: TestClient
    ):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(liquidity_need_score=11)
        )
        assert r.status_code == 422

    def test_investment_horizon_years_zero_returns_422(
        self, client_with_fake_ai: TestClient
    ):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(investment_horizon_years=0)
        )
        assert r.status_code == 422

    def test_max_acceptable_drawdown_negative_returns_422(
        self, client_with_fake_ai: TestClient
    ):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(max_acceptable_drawdown_pct=-1.0)
        )
        assert r.status_code == 422

    def test_net_worth_negative_returns_422(self, client_with_fake_ai: TestClient):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(net_worth=-1)
        )
        assert r.status_code == 422

    def test_liquid_net_worth_negative_returns_422(
        self, client_with_fake_ai: TestClient
    ):
        r = client_with_fake_ai.post(
            "/ai/profile-demo", json=self._bad_kyc(liquid_net_worth=-100)
        )
        assert r.status_code == 422

    def test_all_optional_fields_omitted_still_returns_200(
        self, client_with_fake_ai: TestClient
    ):
        """Los campos opcionales (open_*, declared_return) pueden omitirse."""
        r = client_with_fake_ai.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 200

    def test_declared_return_expectation_accepted_when_present(
        self, client_with_fake_ai: TestClient
    ):
        payload = {**_VALID_REQUEST}
        payload["kyc_payload"] = {
            **_VALID_REQUEST["kyc_payload"],
            "declared_return_expectation_pct": 8.5,
        }
        r = client_with_fake_ai.post("/ai/profile-demo", json=payload)
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileDemoErrors
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileDemoErrors:
    def test_missing_api_key_returns_400(self, monkeypatch: pytest.MonkeyPatch):
        """Si _get_openai_profile_client lanza ValueError → HTTP 400."""
        import risk_first_advisory.api_layer.main as main_module

        def _raise_no_key():
            raise ValueError("OPENAI_API_KEY not configured")

        monkeypatch.setattr(
            main_module, "_get_openai_profile_client", _raise_no_key
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 400

    def test_missing_api_key_detail_mentions_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setattr(
            main_module,
            "_get_openai_profile_client",
            lambda: (_ for _ in ()).throw(ValueError("no key")),
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "OPENAI_API_KEY" in detail

    def test_import_error_returns_400(self, monkeypatch: pytest.MonkeyPatch):
        """Si openai no está instalado (ImportError) → HTTP 400."""
        import risk_first_advisory.api_layer.main as main_module

        def _raise_import():
            raise ImportError("No module named 'openai'")

        monkeypatch.setattr(
            main_module, "_get_openai_profile_client", _raise_import
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 400

    def test_ai_value_error_returns_502(self, monkeypatch: pytest.MonkeyPatch):
        """Si analyze_kyc lanza ValueError → HTTP 502."""
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient(raise_value_error=True)
        monkeypatch.setattr(
            main_module, "_get_openai_profile_client", lambda: fake
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert r.status_code == 502

    def test_ai_502_detail_does_not_expose_internals(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """El detalle del 502 no expone stacktrace ni claves internas."""
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient(raise_value_error=True)
        monkeypatch.setattr(
            main_module, "_get_openai_profile_client", lambda: fake
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        detail = r.json().get("detail", "")
        assert "Traceback" not in detail
        assert "sk-" not in detail
        assert "OPENAI_API_KEY" not in detail

    def test_400_detail_does_not_expose_api_key_value(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """El detalle del 400 no expone el valor de la API key."""
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")

        def _raise():
            raise ValueError("OPENAI_API_KEY not configured")

        monkeypatch.setattr(
            main_module, "_get_openai_profile_client", _raise
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert "sk-super-secret-key" not in r.text


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileDemoSerialization
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileDemoSerialization:
    def test_response_is_json_serializable(self, ai_response: dict):
        json.dumps(ai_response)  # no debe lanzar

    def test_no_raw_python_objects_in_json(self, ai_response: dict):
        serialized = json.dumps(ai_response)
        assert "<" not in serialized
        assert "object at 0x" not in serialized

    def test_all_string_fields_are_strings(self, ai_response: dict):
        assert isinstance(ai_response["client_id"], str)
        assert isinstance(ai_response["preliminary_profile"], str)

    def test_confidence_is_float_in_json(self, ai_response: dict):
        assert isinstance(ai_response["confidence"], float)

    def test_contradictions_serialized_as_list_of_dicts(self, ai_response: dict):
        for c in ai_response["contradictions"]:
            assert isinstance(c, dict)
            serialized = json.dumps(c)
            assert serialized  # no vacío

    def test_response_does_not_contain_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """La respuesta no contiene la API key aunque esté en el entorno."""
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-should-not-appear")
        fake = _FakeAIClient()
        monkeypatch.setattr(
            main_module, "_get_openai_profile_client", lambda: fake
        )
        client = TestClient(main_module.app)
        r = client.post("/ai/profile-demo", json=_VALID_REQUEST)
        assert "sk-test-key-should-not-appear" not in r.text


# ─────────────────────────────────────────────────────────────────────────────
# TestExistingEndpointsUnaffected
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / request fixtures for /ai/profile-follow-up
# ─────────────────────────────────────────────────────────────────────────────

_VALID_PREVIOUS_ANALYSIS: dict = {
    "client_id": "CLI-AI-TEST",
    "preliminary_profile": "moderado-defensivo",
    "confidence": 0.72,
    "contradictions": [
        {
            "field": "liquidity_need_score",
            "severity": "medium",
            "explanation": "High liquidity need with long horizon.",
        }
    ],
    "follow_up_questions": ["¿Cuál es su horizonte real de inversión?"],
    "advisor_notes": ["Verificar necesidad de liquidez."],
}

_VALID_FOLLOWUP_REQUEST: dict = {
    "client_id": "CLI-AI-TEST",
    "original_kyc_payload": _VALID_REQUEST["kyc_payload"],
    "previous_analysis": _VALID_PREVIOUS_ANALYSIS,
    "follow_up_answers": [
        {
            "question": "¿Cuál es su horizonte real de inversión?",
            "answer": "Al menos 15 años, no necesito el dinero antes.",
        }
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileFollowUpBasic
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileFollowUpBasic:
    def test_returns_200_with_fake_client(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 200

    def test_client_id_echoed_in_response(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 200
        assert r.json()["client_id"] == "CLI-AI-TEST"

    def test_missing_follow_up_answers_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        payload = {k: v for k, v in _VALID_FOLLOWUP_REQUEST.items()
                   if k != "follow_up_answers"}
        r = c.post("/ai/profile-follow-up", json=payload)
        assert r.status_code == 422

    def test_empty_follow_up_answers_list_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        payload = {**_VALID_FOLLOWUP_REQUEST, "follow_up_answers": []}
        r = c.post("/ai/profile-follow-up", json=payload)
        assert r.status_code == 422

    def test_empty_answer_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        payload = {
            **_VALID_FOLLOWUP_REQUEST,
            "follow_up_answers": [{"question": "¿Horizonte?", "answer": ""}],
        }
        r = c.post("/ai/profile-follow-up", json=payload)
        assert r.status_code == 422

    def test_empty_question_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        payload = {
            **_VALID_FOLLOWUP_REQUEST,
            "follow_up_answers": [{"question": "", "answer": "15 años"}],
        }
        r = c.post("/ai/profile-follow-up", json=payload)
        assert r.status_code == 422

    def test_empty_client_id_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        payload = {**_VALID_FOLLOWUP_REQUEST, "client_id": ""}
        r = c.post("/ai/profile-follow-up", json=payload)
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileFollowUpResponseFields
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileFollowUpResponseFields:
    @pytest.fixture
    def followup_response(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 200, r.text
        return r.json()

    def test_has_client_id(self, followup_response: dict):
        assert "client_id" in followup_response
        assert followup_response["client_id"] == "CLI-AI-TEST"

    def test_has_revised_profile(self, followup_response: dict):
        assert "revised_profile" in followup_response
        assert isinstance(followup_response["revised_profile"], str)
        assert followup_response["revised_profile"]

    def test_revised_profile_value(self, followup_response: dict):
        assert followup_response["revised_profile"] == "moderado"

    def test_has_confidence(self, followup_response: dict):
        assert "confidence" in followup_response
        assert isinstance(followup_response["confidence"], float)

    def test_confidence_in_range(self, followup_response: dict):
        assert 0.0 <= followup_response["confidence"] <= 1.0

    def test_has_remaining_contradictions(self, followup_response: dict):
        assert "remaining_contradictions" in followup_response
        assert isinstance(followup_response["remaining_contradictions"], list)

    def test_has_profile_change_reason(self, followup_response: dict):
        assert "profile_change_reason" in followup_response
        assert isinstance(followup_response["profile_change_reason"], str)
        assert followup_response["profile_change_reason"].strip()

    def test_has_advisor_notes(self, followup_response: dict):
        assert "advisor_notes" in followup_response
        assert isinstance(followup_response["advisor_notes"], list)

    def test_advisor_notes_are_strings(self, followup_response: dict):
        for n in followup_response["advisor_notes"]:
            assert isinstance(n, str)

    def test_empty_remaining_contradictions_returned_correctly(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient(followup_response=_valid_followup_response(
            remaining_contradictions=[]
        ))
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 200
        assert r.json()["remaining_contradictions"] == []

    def test_multiple_answers_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        payload = {
            **_VALID_FOLLOWUP_REQUEST,
            "follow_up_answers": [
                {"question": "¿Horizonte?", "answer": "15 años"},
                {"question": "¿Liquidez?", "answer": "No necesito liquidez"},
            ],
        }
        r = c.post("/ai/profile-follow-up", json=payload)
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileFollowUpErrors
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileFollowUpErrors:
    def test_missing_api_key_returns_400(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setattr(
            main_module,
            "_get_openai_profile_client",
            lambda: (_ for _ in ()).throw(ValueError("OPENAI_API_KEY not configured")),
        )
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 400

    def test_missing_api_key_detail_mentions_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        def _raise():
            raise ValueError("OPENAI_API_KEY not configured")

        monkeypatch.setattr(main_module, "_get_openai_profile_client", _raise)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 400
        assert "OPENAI_API_KEY" in r.json().get("detail", "")

    def test_ai_follow_up_value_error_returns_502(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient(raise_on_followup=True)
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 502

    def test_502_detail_does_not_expose_internals(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient(raise_on_followup=True)
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        detail = r.json().get("detail", "")
        assert "Traceback" not in detail
        assert "sk-" not in detail

    def test_response_does_not_expose_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import risk_first_advisory.api_layer.main as main_module

        monkeypatch.setenv("OPENAI_API_KEY", "sk-followup-secret-key")
        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert "sk-followup-secret-key" not in r.text


# ─────────────────────────────────────────────────────────────────────────────
# TestAIProfileFollowUpSerialization
# ─────────────────────────────────────────────────────────────────────────────


class TestAIProfileFollowUpSerialization:
    @pytest.fixture
    def followup_response(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        import risk_first_advisory.api_layer.main as main_module

        fake = _FakeAIClient()
        monkeypatch.setattr(main_module, "_get_openai_profile_client", lambda: fake)
        c = TestClient(main_module.app)
        r = c.post("/ai/profile-follow-up", json=_VALID_FOLLOWUP_REQUEST)
        assert r.status_code == 200, r.text
        return r.json()

    def test_response_is_json_serializable(self, followup_response: dict):
        json.dumps(followup_response)  # no debe lanzar

    def test_no_raw_python_objects_in_json(self, followup_response: dict):
        serialized = json.dumps(followup_response)
        assert "<" not in serialized
        assert "object at 0x" not in serialized

    def test_confidence_is_float(self, followup_response: dict):
        assert isinstance(followup_response["confidence"], float)

    def test_revised_profile_is_string(self, followup_response: dict):
        assert isinstance(followup_response["revised_profile"], str)

    def test_profile_change_reason_is_string(self, followup_response: dict):
        assert isinstance(followup_response["profile_change_reason"], str)


class TestExistingEndpointsUnaffected:
    def test_health_still_returns_ok(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_service_name_unchanged(self, client: TestClient):
        r = client.get("/health")
        assert r.json()["service"] == "risk-first-advisory"

    def test_live_portfolio_demo_not_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """POST /live/portfolio-demo con datos insuficientes devuelve 200 (no 500)."""
        import risk_first_advisory.api_layer.main as main_module

        # Provider que devuelve 0 snapshots → insufficient_data, no error HTTP
        class _EmptyProvider:
            def get_snapshot(self, ticker):
                return None

        monkeypatch.setattr(
            main_module,
            "_make_live_provider",
            lambda period, interval: _EmptyProvider(),
        )
        client = TestClient(main_module.app)
        r = client.post("/live/portfolio-demo", json={"profile": "moderado"})
        assert r.status_code == 200
        assert r.json()["status"] == "insufficient_data"
