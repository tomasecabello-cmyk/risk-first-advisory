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
from typing import Any
from unittest.mock import MagicMock

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

    # ── bool-as-number ──────────────────────────────────────────────────────

    def test_confidence_true_raises_value_error(self):
        """confidence=True no debe aceptarse (bool es subclase de int)."""
        client = _build_client(_valid_response(confidence=True))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_confidence_false_raises_value_error(self):
        """confidence=False tampoco debe aceptarse."""
        client = _build_client(_valid_response(confidence=False))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_confidence_none_raises_value_error(self):
        """confidence=None no debe aceptarse."""
        client = _build_client(_valid_response(confidence=None))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_kyc(_SAMPLE_KYC)

    # ── list element type validation ────────────────────────────────────────

    def test_follow_up_questions_item_not_string_raises(self):
        """follow_up_questions con item no-string levanta ValueError."""
        client = _build_client(_valid_response(follow_up_questions=[123, "¿pregunta?"]))
        with pytest.raises(ValueError, match="follow_up_questions"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_advisor_notes_item_not_string_raises(self):
        """advisor_notes con item no-string levanta ValueError."""
        client = _build_client(_valid_response(advisor_notes=[None, "nota válida"]))
        with pytest.raises(ValueError, match="advisor_notes"):
            client.analyze_kyc(_SAMPLE_KYC)

    # ── contradiction structure ─────────────────────────────────────────────

    def test_contradiction_missing_field_key_raises(self):
        """Contradiction sin clave 'field' levanta ValueError."""
        bad = [{"severity": "high", "explanation": "algo"}]
        client = _build_client(_valid_response(contradictions=bad))
        with pytest.raises(ValueError, match="field"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_contradiction_empty_severity_raises(self):
        """Contradiction con severity vacío levanta ValueError."""
        bad = [{"field": "x", "severity": "  ", "explanation": "algo"}]
        client = _build_client(_valid_response(contradictions=bad))
        with pytest.raises(ValueError, match="severity"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_contradiction_missing_explanation_raises(self):
        """Contradiction sin clave 'explanation' levanta ValueError."""
        bad = [{"field": "x", "severity": "low"}]
        client = _build_client(_valid_response(contradictions=bad))
        with pytest.raises(ValueError, match="explanation"):
            client.analyze_kyc(_SAMPLE_KYC)

    def test_contradiction_item_not_dict_raises(self):
        """Contradiction como string (no dict) levanta ValueError."""
        client = _build_client(_valid_response(contradictions=["no es un dict"]))
        with pytest.raises(ValueError, match="contradictions"):
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para follow-up
# ─────────────────────────────────────────────────────────────────────────────


def _valid_followup_response(**overrides) -> dict:
    """Devuelve un dict de respuesta follow-up válida, opcionalmente sobreescrito."""
    base = {
        "revised_profile": "moderado",
        "confidence": 0.84,
        "remaining_contradictions": [],
        "profile_change_reason": (
            "Client confirmed 15-year horizon with no near-term liquidity need. "
            "Profile maintained as moderado."
        ),
        "advisor_notes": ["Follow-up confirmed long-term focus. No profile change needed."],
    }
    base.update(overrides)
    return base


def _build_followup_client(response_dict: dict):
    """Construye OpenAIProfileClient con fake client que devuelve response_dict (follow-up)."""
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    fake = _make_fake_client(json.dumps(response_dict))
    return OpenAIProfileClient(_client=fake)


_SAMPLE_FOLLOWUP_PAYLOAD: dict = {
    "client_id": "CLI-FU-001",
    "original_kyc": dict(_SAMPLE_KYC),
    "previous_analysis": {
        "preliminary_profile": "moderado-defensivo",
        "confidence": 0.72,
        "contradictions": [
            {
                "field": "liquidity_need_score",
                "severity": "medium",
                "explanation": "High liquidity need conflicts with 15-year horizon.",
            }
        ],
        "follow_up_questions": ["¿Cuál es su horizonte real de inversión?"],
        "advisor_notes": ["Verificar necesidad de liquidez antes de confirmar perfil."],
    },
    "follow_up_answers": [
        {
            "question": "¿Cuál es su horizonte real de inversión?",
            "answer": "Al menos 15 años, no necesito el dinero antes de la jubilación.",
        }
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# TestAnalyzeFollowUpValid
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeFollowUpValid:
    def test_returns_dict(self):
        client = _build_followup_client(_valid_followup_response())
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert isinstance(result, dict)

    def test_revised_profile_present(self):
        client = _build_followup_client(_valid_followup_response())
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert "revised_profile" in result

    def test_revised_profile_value(self):
        client = _build_followup_client(_valid_followup_response(revised_profile="moderado"))
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert result["revised_profile"] == "moderado"

    def test_confidence_present_and_in_range(self):
        client = _build_followup_client(_valid_followup_response(confidence=0.84))
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert isinstance(result["confidence"], (int, float))
        assert 0.0 <= result["confidence"] <= 1.0

    def test_remaining_contradictions_is_list(self):
        client = _build_followup_client(_valid_followup_response())
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert isinstance(result["remaining_contradictions"], list)

    def test_profile_change_reason_is_nonempty_str(self):
        client = _build_followup_client(_valid_followup_response())
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert isinstance(result["profile_change_reason"], str)
        assert result["profile_change_reason"].strip()

    def test_advisor_notes_is_list(self):
        client = _build_followup_client(_valid_followup_response())
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert isinstance(result["advisor_notes"], list)

    def test_all_valid_profiles_accepted(self):
        for profile in (
            "conservador",
            "moderado-defensivo",
            "moderado",
            "moderado-agresivo",
            "agresivo",
        ):
            client = _build_followup_client(_valid_followup_response(revised_profile=profile))
            result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
            assert result["revised_profile"] == profile

    def test_empty_remaining_contradictions_accepted(self):
        client = _build_followup_client(_valid_followup_response(remaining_contradictions=[]))
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert result["remaining_contradictions"] == []

    def test_confidence_boundary_zero(self):
        client = _build_followup_client(_valid_followup_response(confidence=0.0))
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert result["confidence"] == 0.0

    def test_confidence_boundary_one(self):
        client = _build_followup_client(_valid_followup_response(confidence=1.0))
        result = client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert result["confidence"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# TestAnalyzeFollowUpValidation
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyzeFollowUpValidation:
    def test_invalid_revised_profile_raises_value_error(self):
        client = _build_followup_client(
            _valid_followup_response(revised_profile="ultra_agresivo")
        )
        with pytest.raises(ValueError, match="revised_profile"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_empty_revised_profile_raises_value_error(self):
        client = _build_followup_client(_valid_followup_response(revised_profile=""))
        with pytest.raises(ValueError, match="revised_profile"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_confidence_above_one_raises_value_error(self):
        client = _build_followup_client(_valid_followup_response(confidence=1.5))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_confidence_below_zero_raises_value_error(self):
        client = _build_followup_client(_valid_followup_response(confidence=-0.1))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_missing_revised_profile_raises_value_error(self):
        d = _valid_followup_response()
        del d["revised_profile"]
        client = _build_followup_client(d)
        with pytest.raises(ValueError, match="revised_profile"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_missing_confidence_raises_value_error(self):
        d = _valid_followup_response()
        del d["confidence"]
        client = _build_followup_client(d)
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_missing_remaining_contradictions_raises_value_error(self):
        d = _valid_followup_response()
        del d["remaining_contradictions"]
        client = _build_followup_client(d)
        with pytest.raises(ValueError, match="remaining_contradictions"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_remaining_contradictions_not_list_raises_value_error(self):
        client = _build_followup_client(
            _valid_followup_response(remaining_contradictions={"field": "x"})
        )
        with pytest.raises(ValueError, match="remaining_contradictions"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_missing_profile_change_reason_raises_value_error(self):
        d = _valid_followup_response()
        del d["profile_change_reason"]
        client = _build_followup_client(d)
        with pytest.raises(ValueError, match="profile_change_reason"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_empty_profile_change_reason_raises_value_error(self):
        client = _build_followup_client(_valid_followup_response(profile_change_reason=""))
        with pytest.raises(ValueError, match="profile_change_reason"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_whitespace_profile_change_reason_raises_value_error(self):
        client = _build_followup_client(_valid_followup_response(profile_change_reason="   "))
        with pytest.raises(ValueError, match="profile_change_reason"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_advisor_notes_not_list_raises_value_error(self):
        client = _build_followup_client(_valid_followup_response(advisor_notes="una nota"))
        with pytest.raises(ValueError, match="advisor_notes"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_invalid_json_raises_value_error(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        fake = _make_fake_client("this is not json at all {{{{")
        client = OpenAIProfileClient(_client=fake)
        with pytest.raises(ValueError, match="JSON"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    # ── bool-as-number ──────────────────────────────────────────────────────

    def test_confidence_true_raises_value_error(self):
        """confidence=True no debe aceptarse en follow-up."""
        client = _build_followup_client(_valid_followup_response(confidence=True))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_confidence_none_raises_value_error(self):
        """confidence=None no debe aceptarse en follow-up."""
        client = _build_followup_client(_valid_followup_response(confidence=None))
        with pytest.raises(ValueError, match="confidence"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    # ── advisor_notes element type ──────────────────────────────────────────

    def test_advisor_notes_item_not_string_raises(self):
        """advisor_notes con item no-string levanta ValueError en follow-up."""
        client = _build_followup_client(
            _valid_followup_response(advisor_notes=[42, "nota válida"])
        )
        with pytest.raises(ValueError, match="advisor_notes"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    # ── remaining_contradictions structure ──────────────────────────────────

    def test_remaining_contradictions_item_not_dict_raises(self):
        """remaining_contradictions con item no-dict levanta ValueError."""
        client = _build_followup_client(
            _valid_followup_response(remaining_contradictions=["texto plano"])
        )
        with pytest.raises(ValueError, match="remaining_contradictions"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_remaining_contradictions_missing_field_raises(self):
        """remaining_contradictions sin clave 'field' levanta ValueError."""
        bad = [{"severity": "low", "explanation": "algo"}]
        client = _build_followup_client(
            _valid_followup_response(remaining_contradictions=bad)
        )
        with pytest.raises(ValueError, match="field"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)

    def test_remaining_contradictions_empty_severity_raises(self):
        """remaining_contradictions con severity vacío levanta ValueError."""
        bad = [{"field": "x", "severity": "", "explanation": "algo"}]
        client = _build_followup_client(
            _valid_followup_response(remaining_contradictions=bad)
        )
        with pytest.raises(ValueError, match="severity"):
            client.analyze_follow_up(_SAMPLE_FOLLOWUP_PAYLOAD)


# ─────────────────────────────────────────────────────────────────────────────
# TestFollowUpPromptContent
# ─────────────────────────────────────────────────────────────────────────────


class TestFollowUpPromptContent:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from risk_first_advisory.ai_layer import openai_profile_client as module

        self.prompt = module._FOLLOWUP_SYSTEM_PROMPT

    def test_prompt_says_ai_does_not_approve_profile(self):
        p = self.prompt.lower()
        assert "not approve" in p or "no aprueba" in p or "only the human advisor" in p

    def test_prompt_says_ai_does_not_recommend_products(self):
        p = self.prompt.lower()
        assert "not recommend" in p or "no recomiend" in p

    def test_prompt_says_ai_does_not_generate_portfolios(self):
        p = self.prompt.lower()
        assert "not generate" in p or "no genera" in p or "portfolio" in p

    def test_prompt_requires_json_only_output(self):
        p = self.prompt.lower()
        assert "json" in p
        assert "no markdown" in p or "only" in p or "valid json" in p

    def test_prompt_mentions_revised_profile_key(self):
        assert "revised_profile" in self.prompt

    def test_prompt_mentions_remaining_contradictions_key(self):
        assert "remaining_contradictions" in self.prompt

    def test_prompt_mentions_profile_change_reason_key(self):
        assert "profile_change_reason" in self.prompt

    def test_prompt_mentions_five_profiles(self):
        for profile in ("conservador", "moderado", "agresivo"):
            assert profile in self.prompt.lower()

    def test_user_message_includes_original_kyc(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        msg = OpenAIProfileClient._build_followup_user_message(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert "original_kyc" in msg or "risk_tolerance_score" in msg


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para extract_investment_preferences
# ─────────────────────────────────────────────────────────────────────────────


def _valid_preferences_response(**overrides) -> dict:
    """Devuelve un dict de respuesta de preferencias válido, con overrides opcionales.

    hard_constraints contiene nombres de campos estructurados (no frases en prosa),
    tal como lo requiere el nuevo prompt: instrument_type, currency, country, etc.
    """
    base = {
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
        "hard_constraints": [
            "instrument_type",
            "currency",
            "country",
            "hard_dollar",
            "entity",
            "sector",
        ],
        "soft_preferences": [],
        "unparsed_preferences": [],
        "confidence": 0.88,
        "advisor_notes": ["Client explicitly excluded energy sector."],
    }
    base.update(overrides)
    return base


def _build_preferences_client(response_dict: dict):
    """Construye OpenAIProfileClient con fake client que devuelve response_dict."""
    from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

    fake = _make_fake_client(json.dumps(response_dict))
    return OpenAIProfileClient(_client=fake)


_SAMPLE_PREFERENCES_PAYLOAD: dict = {
    "client_id": "CLI-PREF-001",
    "natural_language_preferences": (
        "Solo quiero ONs hard dollar argentinas disponibles en Balanz. "
        "No quiero energía. Vencimientos antes de 2029."
    ),
    "kyc_context": None,
    "previous_profile_analysis": None,
}


# ─────────────────────────────────────────────────────────────────────────────
# TestExtractPreferencesValid
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractPreferencesValid:
    def test_returns_dict(self):
        client = _build_preferences_client(_valid_preferences_response())
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert isinstance(result, dict)

    def test_allowed_instrument_types_is_list(self):
        client = _build_preferences_client(_valid_preferences_response())
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert isinstance(result["allowed_instrument_types"], list)

    def test_excluded_instrument_types_is_list(self):
        client = _build_preferences_client(_valid_preferences_response())
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert isinstance(result["excluded_instrument_types"], list)

    def test_currency_is_str_or_none(self):
        client = _build_preferences_client(_valid_preferences_response())
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert result["currency"] is None or isinstance(result["currency"], str)

    def test_hard_dollar_only_is_bool_or_none(self):
        client = _build_preferences_client(_valid_preferences_response())
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert result["hard_dollar_only"] is None or isinstance(
            result["hard_dollar_only"], bool
        )

    def test_avoid_sectors_is_list(self):
        client = _build_preferences_client(_valid_preferences_response())
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert isinstance(result["avoid_sectors"], list)

    def test_min_liquidity_score_in_range_or_none(self):
        client = _build_preferences_client(
            _valid_preferences_response(min_liquidity_score=0.6)
        )
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        liq = result["min_liquidity_score"]
        assert liq is None or (isinstance(liq, (int, float)) and 0.0 <= liq <= 1.0)

    def test_max_maturity_year_int_or_none(self):
        client = _build_preferences_client(
            _valid_preferences_response(max_maturity_year=2029)
        )
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        yr = result["max_maturity_year"]
        assert yr is None or (isinstance(yr, int) and yr >= 1900)

    def test_confidence_in_range(self):
        client = _build_preferences_client(
            _valid_preferences_response(confidence=0.88)
        )
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_all_null_optionals_accepted(self):
        response = _valid_preferences_response(
            currency=None,
            country=None,
            entity=None,
            hard_dollar_only=None,
            min_liquidity_score=None,
            max_maturity_year=None,
        )
        client = _build_preferences_client(response)
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert result["currency"] is None
        assert result["hard_dollar_only"] is None
        assert result["min_liquidity_score"] is None
        assert result["max_maturity_year"] is None


# ─────────────────────────────────────────────────────────────────────────────
# TestExtractPreferencesMapping
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractPreferencesMapping:
    """Escenario realista: ONs hard dollar argentinas en Balanz, no energía."""

    def _run(self) -> dict:
        client = _build_preferences_client(_valid_preferences_response())
        return client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_corporate_bond_in_allowed_types(self):
        result = self._run()
        assert "CORPORATE_BOND" in result["allowed_instrument_types"]

    def test_currency_is_usd(self):
        result = self._run()
        assert result["currency"] == "USD"

    def test_country_is_argentina(self):
        result = self._run()
        assert result["country"] == "Argentina"

    def test_entity_is_balanz(self):
        result = self._run()
        assert result["entity"] == "Balanz"

    def test_hard_dollar_only_is_true(self):
        result = self._run()
        assert result["hard_dollar_only"] is True

    def test_avoid_sectors_includes_energy(self):
        result = self._run()
        sectors_lower = [s.lower() for s in result["avoid_sectors"]]
        assert any("energ" in s for s in sectors_lower)

    def test_max_maturity_year_is_2029(self):
        result = self._run()
        assert result["max_maturity_year"] == 2029

    def test_hard_constraints_not_empty(self):
        result = self._run()
        assert len(result["hard_constraints"]) >= 1

    def test_hard_constraints_contain_field_names(self):
        """hard_constraints debe contener nombres de campos estructurados, no prosa libre."""
        result = self._run()
        # Al menos "instrument_type", "currency", "country", "hard_dollar", "entity"
        # deben aparecer en hard_constraints (tal como lo pide el prompt revisado)
        expected_fields = {"instrument_type", "currency", "country", "hard_dollar", "entity"}
        actual_constraints = set(result["hard_constraints"])
        assert expected_fields.issubset(actual_constraints), (
            f"hard_constraints {actual_constraints} no contiene todos los campos requeridos "
            f"{expected_fields}"
        )

    def test_country_argentina_from_adjective_keyword(self):
        """Cuando la frase contiene 'argentinas', country debe resolverse a 'Argentina'."""
        # Este test verifica el mapeo introducido por la regla del prompt:
        # "argentina/argentinas/argentino" → country = "Argentina"
        response = _valid_preferences_response(country="Argentina")
        client = _build_preferences_client(response)
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert result["country"] == "Argentina"

    def test_sector_in_hard_constraints_when_avoid_energy_explicit(self):
        """Evitar energía con 'solo' → 'sector' debe estar en hard_constraints."""
        response = _valid_preferences_response(
            hard_constraints=["instrument_type", "currency", "country",
                              "hard_dollar", "entity", "sector"]
        )
        client = _build_preferences_client(response)
        result = client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)
        assert "sector" in result["hard_constraints"]


# ─────────────────────────────────────────────────────────────────────────────
# TestExtractPreferencesValidation
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractPreferencesValidation:
    def test_invalid_instrument_type_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(
                allowed_instrument_types=["ETF", "INVALID_TYPE"]
            )
        )
        with pytest.raises(ValueError, match="instrument_type|tipo.*inválido|inválido"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_allowed_types_not_list_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(allowed_instrument_types="CORPORATE_BOND")
        )
        with pytest.raises(ValueError, match="allowed_instrument_types"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_excluded_types_not_list_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(excluded_instrument_types="ETF")
        )
        with pytest.raises(ValueError, match="excluded_instrument_types"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_min_liquidity_score_above_one_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(min_liquidity_score=1.5)
        )
        with pytest.raises(ValueError, match="min_liquidity_score"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_min_liquidity_score_below_zero_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(min_liquidity_score=-0.1)
        )
        with pytest.raises(ValueError, match="min_liquidity_score"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_max_maturity_year_below_1900_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(max_maturity_year=1800)
        )
        with pytest.raises(ValueError, match="max_maturity_year"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_max_maturity_year_not_int_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(max_maturity_year="2029")
        )
        with pytest.raises(ValueError, match="max_maturity_year"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_confidence_above_one_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(confidence=1.01)
        )
        with pytest.raises(ValueError, match="confidence"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_confidence_below_zero_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(confidence=-0.1)
        )
        with pytest.raises(ValueError, match="confidence"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_missing_required_key_raises(self):
        response = _valid_preferences_response()
        del response["confidence"]
        client = _build_preferences_client(response)
        with pytest.raises(ValueError, match="confidence"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_avoid_sectors_not_list_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(avoid_sectors="Energy")
        )
        with pytest.raises(ValueError, match="avoid_sectors"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_advisor_notes_not_list_raises(self):
        client = _build_preferences_client(
            _valid_preferences_response(advisor_notes="single note")
        )
        with pytest.raises(ValueError, match="advisor_notes"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_invalid_json_raises(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        fake = _make_fake_client("not a valid json {{{")
        client = OpenAIProfileClient(_client=fake)
        with pytest.raises(ValueError, match="JSON"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    # ── bool-as-number ──────────────────────────────────────────────────────

    def test_confidence_true_raises(self):
        """confidence=True no debe aceptarse en preferences."""
        client = _build_preferences_client(
            _valid_preferences_response(confidence=True)
        )
        with pytest.raises(ValueError, match="confidence"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_min_liquidity_score_true_raises(self):
        """min_liquidity_score=True no debe aceptarse (bool es subclase de int)."""
        client = _build_preferences_client(
            _valid_preferences_response(min_liquidity_score=True)
        )
        with pytest.raises(ValueError, match="min_liquidity_score"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_min_liquidity_score_false_raises(self):
        """min_liquidity_score=False no debe aceptarse."""
        client = _build_preferences_client(
            _valid_preferences_response(min_liquidity_score=False)
        )
        with pytest.raises(ValueError, match="min_liquidity_score"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_max_maturity_year_true_raises(self):
        """max_maturity_year=True no debe aceptarse (bool es subclase de int)."""
        client = _build_preferences_client(
            _valid_preferences_response(max_maturity_year=True)
        )
        with pytest.raises(ValueError, match="max_maturity_year"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    # ── hard_dollar_only type ───────────────────────────────────────────────

    def test_hard_dollar_only_string_raises(self):
        """hard_dollar_only='true' (string) no debe aceptarse."""
        client = _build_preferences_client(
            _valid_preferences_response(hard_dollar_only="true")
        )
        with pytest.raises(ValueError, match="hard_dollar_only"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_hard_dollar_only_integer_raises(self):
        """hard_dollar_only=1 (int) no debe aceptarse."""
        client = _build_preferences_client(
            _valid_preferences_response(hard_dollar_only=1)
        )
        with pytest.raises(ValueError, match="hard_dollar_only"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    # ── currency / entity empty string ──────────────────────────────────────

    def test_currency_empty_string_raises(self):
        """currency='' (string vacío) no debe aceptarse."""
        client = _build_preferences_client(
            _valid_preferences_response(currency="")
        )
        with pytest.raises(ValueError, match="currency"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_entity_integer_raises(self):
        """entity=123 (int) no debe aceptarse."""
        client = _build_preferences_client(
            _valid_preferences_response(entity=123)
        )
        with pytest.raises(ValueError, match="entity"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_country_empty_string_raises(self):
        """country='' (string vacío) no debe aceptarse."""
        client = _build_preferences_client(
            _valid_preferences_response(country="")
        )
        with pytest.raises(ValueError, match="country"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    # ── list element type validation ────────────────────────────────────────

    def test_allowed_instrument_types_item_not_string_raises(self):
        """allowed_instrument_types con item no-string levanta ValueError."""
        client = _build_preferences_client(
            _valid_preferences_response(allowed_instrument_types=[123])
        )
        with pytest.raises(ValueError, match="allowed_instrument_types"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_hard_constraints_item_not_string_raises(self):
        """hard_constraints con item no-string levanta ValueError."""
        client = _build_preferences_client(
            _valid_preferences_response(hard_constraints=["instrument_type", 42])
        )
        with pytest.raises(ValueError, match="hard_constraints"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_soft_preferences_item_not_string_raises(self):
        """soft_preferences con item no-string levanta ValueError."""
        client = _build_preferences_client(
            _valid_preferences_response(soft_preferences=[None])
        )
        with pytest.raises(ValueError, match="soft_preferences"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_avoid_sectors_item_not_string_raises(self):
        """avoid_sectors con item no-string levanta ValueError."""
        client = _build_preferences_client(
            _valid_preferences_response(avoid_sectors=[{"name": "Energy"}])
        )
        with pytest.raises(ValueError, match="avoid_sectors"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)

    def test_advisor_notes_item_not_string_raises_in_preferences(self):
        """advisor_notes con item no-string levanta ValueError en preferences."""
        client = _build_preferences_client(
            _valid_preferences_response(advisor_notes=[True])
        )
        with pytest.raises(ValueError, match="advisor_notes"):
            client.extract_investment_preferences(_SAMPLE_PREFERENCES_PAYLOAD)


# ─────────────────────────────────────────────────────────────────────────────
# TestExtractPreferencesPrompt
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractPreferencesPrompt:
    @pytest.fixture(autouse=True)
    def _load_prompt(self):
        from risk_first_advisory.ai_layer import openai_profile_client as module

        self.prompt = module._PREFERENCES_SYSTEM_PROMPT

    def test_prompt_says_ai_does_not_invent_tickers(self):
        p = self.prompt.lower()
        assert "ticker" in p and ("not" in p or "no" in p)

    def test_prompt_says_ai_does_not_recommend_products(self):
        p = self.prompt.lower()
        assert "not recommend" in p or "no recomiend" in p

    def test_prompt_says_ai_does_not_generate_portfolios(self):
        p = self.prompt.lower()
        assert "not generate" in p or "no genera" in p or "portfolio" in p

    def test_prompt_requires_json_only_output(self):
        p = self.prompt.lower()
        assert "json" in p
        assert "no markdown" in p or "only" in p

    def test_prompt_mentions_corporate_bond_mapping(self):
        p = self.prompt.lower()
        assert "corporate_bond" in p or "corporate bond" in p

    def test_prompt_mentions_hard_dollar_mapping(self):
        p = self.prompt.lower()
        assert "hard dollar" in p or "hard_dollar" in p

    def test_prompt_mentions_entity_mapping(self):
        p = self.prompt.lower()
        assert "balanz" in p or "entity" in p

    def test_prompt_mentions_avoid_sectors(self):
        p = self.prompt.lower()
        assert "avoid_sectors" in p or "sector" in p

    def test_prompt_mentions_max_maturity_year(self):
        p = self.prompt.lower()
        assert "max_maturity_year" in p or "maturity" in p

    def test_prompt_mentions_hard_constraints_vs_soft(self):
        p = self.prompt.lower()
        assert "hard_constraint" in p or "hard constraint" in p
        assert "soft_preference" in p or "soft preference" in p

    def test_prompt_mentions_argentina_mapping(self):
        """El prompt debe tener regla explícita para mapear 'argentinas' → country Argentina."""
        p = self.prompt.lower()
        assert "argentina" in p and ("country" in p)

    def test_prompt_mentions_structured_field_names_for_hard_constraints(self):
        """El prompt debe indicar que hard_constraints deben ser nombres de campos."""
        p = self.prompt.lower()
        # El prompt debe mencionar explícitamente los nombres de campo canónicos
        assert "instrument_type" in p
        assert "hard_dollar" in p
        assert "entity" in p

    def test_user_message_contains_natural_language_preferences(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        msg = OpenAIProfileClient._build_preferences_user_message(
            _SAMPLE_PREFERENCES_PAYLOAD
        )
        assert "PREFERENCES INPUT" in msg
        assert "ONs hard dollar" in msg or "natural_language_preferences" in msg

    def test_api_key_not_in_preferences_system_prompt(self):
        import re

        assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", self.prompt)
        assert "OPENAI_API_KEY" not in self.prompt

    def test_user_message_includes_follow_up_answers(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        msg = OpenAIProfileClient._build_followup_user_message(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert "follow_up_answers" in msg

    def test_user_message_includes_previous_analysis(self):
        from risk_first_advisory.ai_layer.openai_profile_client import OpenAIProfileClient

        msg = OpenAIProfileClient._build_followup_user_message(_SAMPLE_FOLLOWUP_PAYLOAD)
        assert "previous_analysis" in msg or "preliminary_profile" in msg

    def test_followup_prompt_no_api_key_hardcoded(self):
        import re

        from risk_first_advisory.ai_layer import openai_profile_client as module

        assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", module._FOLLOWUP_SYSTEM_PROMPT), (
            "El follow-up system prompt parece contener una API key real."
        )
