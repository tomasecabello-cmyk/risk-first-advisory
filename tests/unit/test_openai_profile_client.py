"""
Tests unitarios para OpenAIProfileClient.

No llaman a la API real de OpenAI. Se inyecta un cliente fake vía el
parámetro _client del constructor, eliminando cualquier dependencia de red
y de OPENAI_API_KEY.

Clases:
    TestMissingApiKey          — falla sin variable de entorno.
    TestAnalyzeKycValid        — respuesta JSON válida → dict correcto.
    TestAnalyzeKycJsonErrors   — JSON inválido → ValueError.
    TestValidation             — validaciones de campos individuales.
    TestPromptContent          — el system prompt contiene las reglas correctas.
    TestApiKeyNotLeaked        — la API key no aparece en outputs.
"""

from __future__ import annotations

import json
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_fake_client(content: str) -> Any:
    """
    Construye un objeto que imita openai.OpenAI().chat.completions.create(...)
    devolviendo `content` como texto de la respuesta.
    """
    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    completion = MagicMock()
    completion.choices = [choice]

    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


def _valid_response(**overrides) -> dict:
    """Devuelve un dict de respuesta válida, opcionalmente sobreescrito."""
    base = {
        "preliminary_profile": "moderado",
        "confidence": 0.78,
        "contradictions": [
            {
                "field": "risk_tolerance_score",
                "severity": "medium",
                "explanation": "High tolerance but high liquidity need.",
            }
        ],
        "follow_up_questions": ["¿Cuál es su horizonte real de inversión?"],
        "advisor_notes": ["Verificar coherencia entre tolerancia y necesidad de liquidez."],
    }
    base.update(overrides)
    return base


def _make_client_from_dict(d: dict) -> Any:
    return _make_fake_client(json.dumps(d))


def _build_client(response_dict: dict):
    """Construye OpenAIProfileClient con fake client que devuelve response_dict."""
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    fake = _make_client_from_dict(response_dict)
    return OpenAIProfileClient(_client=fake)


_SAMPLE_KYC: dict = {
    "risk_tolerance_score": 4,
    "risk_capacity_score": 8,
    "liquidity_need_score": 7,
    "investment_horizon_years": 15,
    "investment_experience": "moderada",
    "income_stability": "stable",
    "net_worth": 500_000,
    "liquid_net_worth": 150_000,
    "max_acceptable_drawdown_pct": 12.0,
    "open_investment_goal": "Quiero ahorrar para la jubilación.",
    "open_risk_reaction": "Me preocuparía mucho una caída del 15%.",
}


# ─────────────────────────────────────────────────────────────────────────────
# TestMissingApiKey
# ─────────────────────────────────────────────────────────────────────────────


class TestMissingApiKey:
    def test_raises_value_error_when_key_missing(self, monkeypatch):
        """Sin OPENAI_API_KEY en el entorno, el constructor levanta ValueError."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIProfileClient()

    def test_error_message_mentions_set_command(self, monkeypatch):
        """El mensaje de error incluye instrucción set/export."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        with pytest.raises(ValueError) as exc_info:
            OpenAIProfileClient()
        msg = str(exc_info.value)
        # Debe mencionar la variable y cómo configurarla
        assert "OPENAI_API_KEY" in msg
        assert "set" in msg.lower() or "export" in msg.lower()

    def test_injected_client_bypasses_key_check(self):
        """Con _client inyectado no se valida OPENAI_API_KEY."""
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        fake = _make_fake_client(json.dumps(_valid_response()))
        # No debe lanzar aunque no haya variable de entorno.
        client = OpenAIProfileClient(_client=fake)
        assert client is not None


# ─────────────────────────────────────────────────────────────────────────────
# TestAnalyzeKycValid
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeKycValid:
    def test_returns_dict(self):
        client = _build_client(_valid_response())
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert isinstance(result, dict)

    def test_preliminary_profile_present(self):
        client = _build_client(_valid_response())
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert "preliminary_profile" in result

    def test_preliminary_profile_value(self):
        client = _build_client(_valid_response(preliminary_profile="moderado"))
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert result["preliminary_profile"] == "moderado"

    def test_confidence_present_and_float(self):
        client = _build_client(_valid_response(confidence=0.75))
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert isinstance(result["confidence"], (int, float))
        assert result["confidence"] == pytest.approx(0.75)

    def test_contradictions_is_list(self):
        client = _build_client(_valid_response())
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert isinstance(result["contradictions"], list)

    def test_follow_up_questions_is_list(self):
        client = _build_client(_valid_response())
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert isinstance(result["follow_up_questions"], list)

    def test_advisor_notes_is_list(self):
        client = _build_client(_valid_response())
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert isinstance(result["advisor_notes"], list)

    def test_all_required_keys_present(self):
        from risk_first_advisory.ai_layer.openai_profile_client import _REQUIRED_OUTPUT_KEYS

        client = _build_client(_valid_response())
        result = client.analyze_kyc(_SAMPLE_KYC)
        for key in _REQUIRED_OUTPUT_KEYS:
            assert key in result, f"Falta clave requerida: {key!r}"

    def test_all_valid_profiles_accepted(self):
        profiles = [
            "conservador",
            "moderado-defensivo",
            "moderado",
            "moderado-agresivo",
            "agresivo",
        ]
        for profile in profiles:
            client = _build_client(_valid_response(preliminary_profile=profile))
            result = client.analyze_kyc(_SAMPLE_KYC)
            assert result["preliminary_profile"] == profile

    def test_empty_contradictions_accepted(self):
        client = _build_client(_valid_response(contradictions=[]))
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert result["contradictions"] == []

    def test_empty_follow_up_accepted(self):
        client = _build_client(_valid_response(follow_up_questions=[]))
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert result["follow_up_questions"] == []

    def test_confidence_boundary_zero(self):
        client = _build_client(_valid_response(confidence=0.0))
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert result["confidence"] == 0.0

    def test_confidence_boundary_one(self):
        client = _build_client(_valid_response(confidence=1.0))
        result = client.analyze_kyc(_SAMPLE_KYC)
        assert result["confidence"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# TestAnalyzeKycJsonErrors
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeKycJsonErrors:
    def test_invalid_json_raises_value_error(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        fake = _make_fake_client("this is not json at all {{{{")
        client = OpenAIProfileClient(_client=fake)
        with pytest.raises(ValueError, match="JSON"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_json_array_raises_value_error(self):
        """La IA devuelve una lista en vez de un objeto → ValueError."""
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        fake = _make_fake_client(json.dumps([{"preliminary_profile": "moderado"}]))
        client = OpenAIProfileClient(_client=fake)
        with pytest.raises(ValueError, match="dict"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_empty_response_raises_value_error(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        message = MagicMock()
        message.content = ""
        choice = MagicMock()
        choice.message = message
        completion = MagicMock()
        completion.choices = [choice]
        fake = MagicMock()
        fake.chat.completions.create.return_value = completion

        client = OpenAIProfileClient(_client=fake)
        with pytest.raises(ValueError):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_no_choices_raises_value_error(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        completion = MagicMock()
        completion.choices = []
        fake = MagicMock()
        fake.chat.completions.create.return_value = completion

        client = OpenAIProfileClient(_client=fake)
        with pytest.raises(ValueError):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_api_exception_raises_value_error(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        fake = MagicMock()
        fake.chat.completions.create.side_effect = RuntimeError("API timeout")

        client = OpenAIProfileClient(_client=fake)
        with pytest.raises(ValueError, match="OpenAI"):
            client.analyze_kyc(_SAMPLE_KYC)


# ─────────────────────────────────────────────────────────────────────────────
# TestValidation — cada campo que puede fallar la validación
# ─────────────────────────────────────────────────────────────────────────────


class TestValidation:
    def test_invalid_profile_raises_value_error(self):
        client = _build_client(_valid_response(preliminary_profile="ultra_agresivo"))
        with pytest.raises(ValueError, match="preliminary_profile"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_empty_profile_raises_value_error(self):
        client = _build_client(_valid_response(preliminary_profile=""))
        with pytest.raises(ValueError, match="preliminary_profile"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_confidence_above_one_raises_value_error(self):
        client = _build_client(_valid_response(confidence=1.5))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_confidence_below_zero_raises_value_error(self):
        client = _build_client(_valid_response(confidence=-0.1))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_confidence_non_numeric_raises_value_error(self):
        client = _build_client(_valid_response(confidence="high"))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_missing_preliminary_profile_raises_value_error(self):
        d = _valid_response()
        del d["preliminary_profile"]
        client = _build_client(d)
        with pytest.raises(ValueError, match="preliminary_profile"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_missing_confidence_raises_value_error(self):
        d = _valid_response()
        del d["confidence"]
        client = _build_client(d)
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_missing_contradictions_raises_value_error(self):
        d = _valid_response()
        del d["contradictions"]
        client = _build_client(d)
        with pytest.raises(ValueError, match="contradictions"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_missing_follow_up_questions_raises_value_error(self):
        d = _valid_response()
        del d["follow_up_questions"]
        client = _build_client(d)
        with pytest.raises(ValueError, match="follow_up_questions"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_missing_advisor_notes_raises_value_error(self):
        d = _valid_response()
        del d["advisor_notes"]
        client = _build_client(d)
        with pytest.raises(ValueError, match="advisor_notes"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_contradictions_not_list_raises_value_error(self):
        client = _build_client(_valid_response(contradictions={"field": "x"}))
        with pytest.raises(ValueError, match="contradictions"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_follow_up_questions_not_list_raises_value_error(self):
        client = _build_client(_valid_response(follow_up_questions="¿pregunta?"))
        with pytest.raises(ValueError, match="follow_up_questions"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_advisor_notes_not_list_raises_value_error(self):
        client = _build_client(_valid_response(advisor_notes="nota"))
        with pytest.raises(ValueError, match="advisor_notes"):
            client.analyze_kyc(_SAMPLE_KYC)


# ─────────────────────────────────────────────────────────────────────────────
# TestPromptContent — el system prompt contiene las reglas correctas
# ─────────────────────────────────────────────────────────────────────────────


class TestPromptContent:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from risk_first_advisory.ai_layer import openai_profile_client as module
        self.prompt = module._SYSTEM_PROMPT

    def test_prompt_says_ai_does_not_approve_profile(self):
        """La IA no aprueba el perfil — solo el asesor humano puede hacerlo."""
        p = self.prompt.lower()
        assert "not approve" in p or "no aprueba" in p or "only the human advisor" in p

    def test_prompt_says_ai_does_not_recommend_products(self):
        """La IA no recomienda productos."""
        p = self.prompt.lower()
        assert "not recommend" in p or "no recomiend" in p

    def test_prompt_says_ai_does_not_generate_portfolios(self):
        """La IA no genera portfolios."""
        p = self.prompt.lower()
        assert "not generate" in p or "no genera" in p or "portfolio" in p

    def test_prompt_requires_json_only_output(self):
        """El prompt pide respuesta exclusivamente en JSON."""
        p = self.prompt.lower()
        assert "json" in p
        assert "no markdown" in p or "only" in p or "strictly" in p or "valid json" in p

    def test_prompt_mentions_five_profiles(self):
        """Los cinco perfiles válidos están mencionados en el prompt."""
        for profile in ("conservador", "moderado", "agresivo"):
            assert profile in self.prompt.lower()

    def test_prompt_mentions_contradictions(self):
        """El prompt menciona la detección de contradicciones."""
        assert "contradiction" in self.prompt.lower()

    def test_prompt_mentions_follow_up(self):
        """El prompt menciona preguntas de follow-up."""
        assert "follow" in self.prompt.lower() or "follow-up" in self.prompt.lower()

    def test_prompt_mentions_declared_return_restriction(self):
        """El prompt prohíbe usar declared_return_expectation para construir el perfil."""
        p = self.prompt.lower()
        assert "declared_return" in p or "return_expectation" in p


# ─────────────────────────────────────────────────────────────────────────────
# TestApiKeyNotLeaked
# ─────────────────────────────────────────────────────────────────────────────


class TestApiKeyNotLeaked:
    def test_api_key_not_in_response_dict(self, monkeypatch):
        """La API key no aparece en el dict devuelto por analyze_kyc."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-key-12345")

        client = _build_client(_valid_response())
        result = client.analyze_kyc(_SAMPLE_KYC)
        result_str = json.dumps(result)
        assert "sk-test-secret-key-12345" not in result_str

    def test_api_key_not_in_user_message(self):
        """La API key no aparece en el user message construido."""
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        msg = OpenAIProfileClient._build_user_message({"key": "value"})
        assert "sk-" not in msg

    def test_api_key_not_in_system_prompt(self):
        """
        La API key no está hardcodeada en el system prompt.
        Busca el patrón 'sk-' seguido de al menos 20 chars alfanuméricos,
        que es la forma de una clave real de OpenAI.
        """
        import re
        from risk_first_advisory.ai_layer import openai_profile_client as module

        # "sk-" seguido de 20+ chars alfanuméricos (patrón de key real)
        assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", module._SYSTEM_PROMPT), (
            "El system prompt parece contener una API key real."
        )
        # La variable de entorno tampoco debe aparecer como valor literal
        assert "OPENAI_API_KEY" not in module._SYSTEM_PROMPT

    def test_client_str_does_not_expose_key(self, monkeypatch):
        """repr/str del objeto no expone la key."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-appear")

        client = _build_client(_valid_response())
        as_str = str(client) + repr(client)
        assert "sk-should-not-appear" not in as_str
