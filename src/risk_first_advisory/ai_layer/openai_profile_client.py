"""
OpenAIProfileClient — cliente de IA real (OpenAI) para análisis de KYC.

Responsabilidad única: tomar un KYC payload estructurado con respuestas abiertas
y devolver un análisis JSON con perfil preliminar, contradicciones detectadas,
preguntas de follow-up y notas para el asesor.

IMPORTANTES restricciones de diseño:
    - La IA NO aprueba el perfil. Eso lo hace el asesor humano.
    - La IA NO recomienda productos ni tickers.
    - La IA NO genera portfolios ni retornos esperados.
    - La IA NO usa declared_return_expectation para construir el perfil.
    - La IA solo interpreta el KYC, detecta contradicciones y propone follow-up.
    - La aprobación final siempre corresponde al asesor (human-in-the-loop).

La API key se lee de la variable de entorno OPENAI_API_KEY.
Nunca se imprime, loguea ni expone en las respuestas.

Uso:
    client = OpenAIProfileClient()
    result = client.analyze_kyc(kyc_payload)

No usar en tests sin mockear. Ver tests/unit/test_openai_profile_client.py.
"""

from __future__ import annotations

import json
import os
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_VALID_PROFILES: frozenset[str] = frozenset({
    "conservador",
    "moderado-defensivo",
    "moderado",
    "moderado-agresivo",
    "agresivo",
})

_REQUIRED_OUTPUT_KEYS: tuple[str, ...] = (
    "preliminary_profile",
    "confidence",
    "contradictions",
    "follow_up_questions",
    "advisor_notes",
)

_DEFAULT_MODEL: str = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS: int = 1024
_DEFAULT_TEMPERATURE: float = 0.2     # baja para respuestas reproducibles


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT: str = """
You are a risk-profiling analyst assistant for a financial advisory firm.

Your role is strictly limited to:
1. Interpreting structured KYC data and open-ended client responses.
2. Identifying contradictions or inconsistencies in the risk profile.
3. Suggesting follow-up questions the human advisor should ask.
4. Proposing a PRELIMINARY risk profile (not final, always subject to advisor review).

HARD RULES — you must never violate these:
- You do NOT approve the final profile. Only the human advisor can approve it.
- You do NOT recommend financial products, tickers, ETFs, or securities.
- You do NOT generate portfolios or asset allocations.
- You do NOT use declared_return_expectation_pct to construct the profile.
  Return expectations are noted but never used to elevate the risk profile.
- You do NOT output any information about your own model, API key, or system internals.
- You always respond with ONLY a valid JSON object — no markdown, no prose.

Output format (strict JSON, no other text):
{
  "preliminary_profile": "<one of: conservador|moderado-defensivo|moderado|moderado-agresivo|agresivo>",
  "confidence": <float 0.0–1.0>,
  "contradictions": [
    {
      "field": "<field name or topic>",
      "severity": "<low|medium|high>",
      "explanation": "<brief explanation>"
    }
  ],
  "follow_up_questions": [
    "<question string>"
  ],
  "advisor_notes": [
    "<note string>"
  ]
}

Profile definitions (for your reference only — do not output):
- conservador: very low risk tolerance, capital preservation focus, short horizon or high liquidity need
- moderado-defensivo: low-medium risk, some growth but predominantly defensive
- moderado: balanced risk/return, medium horizon, moderate experience
- moderado-agresivo: medium-high risk, growth-oriented, longer horizon
- agresivo: high risk tolerance, long horizon, experienced investor, low liquidity need

Contradictions to watch for:
- High risk_tolerance_score but high liquidity_need_score (short-term horizon conflicts long-term risk)
- Low risk_capacity_score vs high risk_tolerance_score (willingness exceeds financial capacity)
- High max_acceptable_drawdown_pct vs stated concern about losses in open fields
- Declared return expectation incompatible with stated risk tolerance
- Short investment horizon with high equity preference
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# OpenAIProfileClient
# ─────────────────────────────────────────────────────────────────────────────


class OpenAIProfileClient:
    """
    Cliente de IA real (OpenAI) para análisis de KYC y perfilamiento preliminar.

    Lee OPENAI_API_KEY del entorno. Levanta ValueError si la key no existe.

    Parámetros:
        model        : modelo de OpenAI a usar (default: gpt-4o-mini).
        max_tokens   : máximo de tokens en la respuesta (default: 1024).
        temperature  : temperatura del modelo (default: 0.2, baja para reproducibilidad).
        _client      : cliente OpenAI inyectable para tests (si None, se crea real).
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        temperature: float = _DEFAULT_TEMPERATURE,
        _client: Any = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

        if _client is not None:
            # Inyección directa para tests — no se valida la key.
            self._client = _client
        else:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY no está configurada en las variables de entorno. "
                    "Ejecutar: set OPENAI_API_KEY=sk-... (Windows) "
                    "o export OPENAI_API_KEY=sk-... (Unix/macOS)."
                )
            try:
                import openai
            except ImportError as exc:
                raise ImportError(
                    "El paquete 'openai' no está instalado. "
                    "Ejecutar: pip install openai"
                ) from exc

            self._client = openai.OpenAI(api_key=api_key)

    # ── Construcción del user message ────────────────────────────────────────

    @staticmethod
    def _build_user_message(kyc_payload: dict[str, Any]) -> str:
        """
        Construye el mensaje de usuario a partir del KYC payload.

        Serializa el payload como JSON indentado para que la IA pueda
        interpretarlo campo por campo.
        """
        try:
            payload_json = json.dumps(kyc_payload, indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"kyc_payload no es serializable a JSON: {exc}"
            ) from exc

        return (
            "Please analyze the following KYC data and respond with ONLY a valid JSON object "
            "following the specified output format. No markdown, no prose.\n\n"
            f"KYC DATA:\n{payload_json}"
        )

    # ── Llamada a la IA ───────────────────────────────────────────────────────

    def _call_api(self, user_message: str) -> str:
        """
        Llama a la API de OpenAI y devuelve el contenido de la respuesta como string.

        Raises:
            ValueError: si la respuesta está vacía o la API falla.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise ValueError(
                f"Error al llamar a la API de OpenAI: {type(exc).__name__}: {exc}"
            ) from exc

        choices = getattr(response, "choices", None)
        if not choices:
            raise ValueError("La API de OpenAI devolvió una respuesta sin choices.")

        content = getattr(choices[0].message, "content", None)
        if not content or not content.strip():
            raise ValueError("La API de OpenAI devolvió contenido vacío.")

        return content.strip()

    # ── Validación de la respuesta ────────────────────────────────────────────

    @staticmethod
    def _validate_response(data: dict[str, Any]) -> None:
        """
        Valida que el dict devuelto por la IA tenga la estructura esperada.

        Raises:
            ValueError: con mensaje descriptivo si la validación falla.
        """
        # Claves requeridas
        for key in _REQUIRED_OUTPUT_KEYS:
            if key not in data:
                raise ValueError(
                    f"Respuesta de IA inválida: falta la clave requerida '{key}'. "
                    f"Claves presentes: {list(data.keys())}"
                )

        # preliminary_profile
        profile = data["preliminary_profile"]
        if not isinstance(profile, str) or profile not in _VALID_PROFILES:
            raise ValueError(
                f"Respuesta de IA inválida: preliminary_profile={profile!r} "
                f"no es uno de los perfiles válidos: {sorted(_VALID_PROFILES)}"
            )

        # confidence
        confidence = data["confidence"]
        if not isinstance(confidence, (int, float)):
            raise ValueError(
                f"Respuesta de IA inválida: confidence debe ser numérico, "
                f"recibido {type(confidence).__name__}."
            )
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(
                f"Respuesta de IA inválida: confidence={confidence} "
                "debe estar en el rango [0.0, 1.0]."
            )

        # contradictions
        if not isinstance(data["contradictions"], list):
            raise ValueError(
                "Respuesta de IA inválida: 'contradictions' debe ser una lista, "
                f"recibido {type(data['contradictions']).__name__}."
            )

        # follow_up_questions
        if not isinstance(data["follow_up_questions"], list):
            raise ValueError(
                "Respuesta de IA inválida: 'follow_up_questions' debe ser una lista, "
                f"recibido {type(data['follow_up_questions']).__name__}."
            )

        # advisor_notes
        if not isinstance(data["advisor_notes"], list):
            raise ValueError(
                "Respuesta de IA inválida: 'advisor_notes' debe ser una lista, "
                f"recibido {type(data['advisor_notes']).__name__}."
            )

    # ── API pública ───────────────────────────────────────────────────────────

    def analyze_kyc(self, kyc_payload: dict[str, Any]) -> dict[str, Any]:
        """
        Analiza un KYC payload y devuelve un análisis JSON validado.

        Args:
            kyc_payload: diccionario con los datos KYC del cliente.
                         Puede incluir campos de scores, cualitativos y abiertos.

        Returns:
            dict con las claves:
                preliminary_profile  : str (uno de los 5 perfiles)
                confidence           : float [0.0, 1.0]
                contradictions       : list[dict] (field, severity, explanation)
                follow_up_questions  : list[str]
                advisor_notes        : list[str]

        Raises:
            ValueError: si el kyc_payload no es serializable, la API falla,
                        la respuesta no es JSON válido, o falla la validación.
        """
        user_message = self._build_user_message(kyc_payload)
        raw_content = self._call_api(user_message)

        # Parsear JSON
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"La IA devolvió JSON inválido: {exc}. "
                f"Contenido recibido (primeros 200 chars): {raw_content[:200]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"La IA devolvió un JSON que no es un objeto (dict). "
                f"Tipo recibido: {type(data).__name__}."
            )

        self._validate_response(data)
        return data
