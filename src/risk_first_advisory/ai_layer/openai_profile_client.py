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

_REQUIRED_FOLLOWUP_KEYS: tuple[str, ...] = (
    "revised_profile",
    "confidence",
    "remaining_contradictions",
    "profile_change_reason",
    "advisor_notes",
)

_REQUIRED_PREFERENCES_KEYS: tuple[str, ...] = (
    "allowed_instrument_types",
    "excluded_instrument_types",
    "currency",
    "country",
    "entity",
    "hard_dollar_only",
    "avoid_sectors",
    "prefer_sectors",
    "avoid_issuers",
    "prefer_issuers",
    "min_liquidity_score",
    "max_maturity_year",
    "hard_constraints",
    "soft_preferences",
    "unparsed_preferences",
    "confidence",
    "advisor_notes",
)

_VALID_INSTRUMENT_TYPES: frozenset[str] = frozenset({
    "ETF", "CORPORATE_BOND", "SOVEREIGN_BOND", "STOCK",
    "CEDEAR", "MUTUAL_FUND", "MONEY_MARKET", "OTHER",
})

_DEFAULT_MODEL: str = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS: int = 1024
_DEFAULT_TEMPERATURE: float = 0.2     # baja para respuestas reproducibles


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de validación de respuestas (privados, a nivel módulo)
# ─────────────────────────────────────────────────────────────────────────────


def _assert_not_bool(value: Any, field: str, context: str = "") -> None:
    """
    Levanta ValueError si value es bool.

    En Python bool es subclase de int, por lo que isinstance(True, int) es True.
    Esta guarda debe aplicarse ANTES de cualquier isinstance(..., (int, float))
    para rechazar explícitamente True/False como valores numéricos.
    """
    if isinstance(value, bool):
        ctx = f" ({context})" if context else ""
        raise ValueError(
            f"OpenAI response{ctx} field '{field}' must be a number, not bool. "
            f"Received {value!r}."
        )


def _assert_list_of_str(lst: list, field: str, context: str = "") -> None:
    """Levanta ValueError si algún elemento de lst no es str."""
    ctx = f" ({context})" if context else ""
    for i, item in enumerate(lst):
        if not isinstance(item, str):
            raise ValueError(
                f"OpenAI response{ctx} field '{field}' must be a list of strings, "
                f"but item at index {i} is {type(item).__name__}: {item!r}"
            )


def _assert_contradiction_items(lst: list, field: str, context: str = "") -> None:
    """
    Valida que cada elemento de lst sea un dict con las claves
    'field', 'severity' y 'explanation' como strings no vacíos.
    """
    ctx = f" ({context})" if context else ""
    for i, item in enumerate(lst):
        if not isinstance(item, dict):
            raise ValueError(
                f"OpenAI response{ctx} field '{field}' item at index {i} "
                f"must be a dict, got {type(item).__name__}."
            )
        for subkey in ("field", "severity", "explanation"):
            if subkey not in item:
                raise ValueError(
                    f"OpenAI response{ctx} '{field}'[{i}] missing required key '{subkey}'."
                )
            val = item[subkey]
            if not isinstance(val, str) or not val.strip():
                raise ValueError(
                    f"OpenAI response{ctx} '{field}'[{i}]['{subkey}'] "
                    f"must be a non-empty string, got {val!r}."
                )


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
- IMPORTANT — write every human-readable text field (explanation, follow_up_questions,
  advisor_notes) in SPANISH (rioplatense). JSON keys and the preliminary_profile enum stay
  as defined. severity must be one of: baja | media | alta.

SCORE CONVENTIONS — the KYC uses THESE scales. Interpret accordingly; do NOT assume a generic 1-10:
- risk_tolerance_score: 1–10 (1 = tolerancia mínima, 10 = máxima).
- risk_capacity_score: 1–10 (1 = capacidad mínima, 10 = máxima).
- liquidity_need_score: 3 = necesidad de liquidez BAJA, 5 = MEDIA, 8 = ALTA. Un score de 3
  significa necesidad de liquidez BAJA, NO moderada.
- max_acceptable_drawdown_pct: porcentaje (ej. 20 = el cliente tolera una caída del 20%).
- investment_horizon_years: años (entero).

Output format (strict JSON, no other text):
{
  "preliminary_profile": "<one of: conservador|moderado-defensivo|moderado|moderado-agresivo|agresivo>",
  "confidence": <float 0.0–1.0>,
  "contradictions": [
    {
      "field": "<field name or topic>",
      "severity": "<baja|media|alta>",
      "explanation": "<explicación breve en español>"
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
# Follow-up system prompt
# ─────────────────────────────────────────────────────────────────────────────

_FOLLOWUP_SYSTEM_PROMPT: str = """
You are a risk-profiling analyst assistant for a financial advisory firm.

You are conducting a second-round review. You have been provided:
1. The original KYC data for the client.
2. The preliminary profile and contradictions identified in the first round.
3. The advisor's follow-up questions and the client's answers.

Your role is strictly limited to:
1. Re-evaluating the risk profile in light of the new information.
2. Identifying any remaining contradictions or new inconsistencies.
3. Explaining clearly whether the profile should remain the same or change, and why.
4. Providing updated notes for the human advisor.

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
  "revised_profile": "<one of: conservador|moderado-defensivo|moderado|moderado-agresivo|agresivo>",
  "confidence": <float 0.0–1.0>,
  "remaining_contradictions": [
    {
      "field": "<field name or topic>",
      "severity": "<low|medium|high>",
      "explanation": "<brief explanation>"
    }
  ],
  "profile_change_reason": "<non-empty explanation of why the profile was maintained or changed>",
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
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Investment preferences system prompt
# ─────────────────────────────────────────────────────────────────────────────

_PREFERENCES_SYSTEM_PROMPT: str = """
You are an investment preferences extraction assistant for a financial advisory firm.

You receive a natural language description of a client's investment preferences and restrictions,
optionally accompanied by their KYC data and a preliminary risk profile analysis.

Your role is strictly limited to:
1. Parsing and structuring the client's stated preferences into a standardized JSON format.
2. Identifying which preferences are hard constraints vs soft preferences.
3. Flagging preferences that are ambiguous or cannot be confidently parsed.
4. Providing notes for the human advisor about ambiguities or potential conflicts.

HARD RULES — you must never violate these:
- You do NOT filter or select specific instruments. That is done by a separate system.
- You do NOT invent, recommend, or mention specific tickers, funds, or securities.
- You do NOT recommend any financial products.
- You do NOT generate portfolios or asset allocations.
- You do NOT output any information about your own model, API key, or system internals.
- You always respond with ONLY a valid JSON object — no markdown, no prose.

PARSING RULES:
- "ONs" / "obligaciones negociables" / "corporate bonds" / "bonos corporativos"
  → allowed_instrument_types: ["CORPORATE_BOND"]
- "hard dollar" / "dólar hard" / "USD hard" / "dólares duros"
  → hard_dollar_only: true, currency: "USD"
- "solo USD" / "en dólares" / "USD only"
  → currency: "USD"
- "argentina" / "argentinas" / "argentino" / "argentinos" / "de Argentina"
  (used as adjective describing instrument origin, e.g. "ONs argentinas")
  → country: "Argentina"
- "disponible en Balanz/PPI/Cocos" / "solo en Balanz" / "a través de Balanz"
  → entity: "Balanz" (or the respective entity name)
- "no energía" / "evitar energía" / "sin sector energético" / "no oil & gas"
  → avoid_sectors: ["Energy"]
- "vencimiento antes de YYYY" / "máximo vencimiento YYYY" / "no más allá de YYYY"
  → max_maturity_year: YYYY
- "solo" / "únicamente" / "exclusivamente" / "solo quiero"
  → The entire restriction is a hard constraint. In addition, populate hard_constraints
    with the STRUCTURED FIELD NAMES that were constrained — not a prose description.
    Use these canonical field names: "instrument_type", "currency", "country",
    "hard_dollar", "entity", "sector", "issuer", "maturity", "liquidity".
    Example: "Solo quiero ONs hard dollar argentinas disponibles en Balanz y evitar energía."
    → hard_constraints: ["instrument_type", "currency", "country", "hard_dollar", "entity", "sector"]
- "prefiero" / "me gusta" / "si es posible" / "idealmente"
  → treat that preference as a soft_preference (field name in soft_preferences)
- "instrumentos líquidos" / "alta liquidez" / "fácil de vender"
  → min_liquidity_score: 0.7 (use judgment for "muy líquidos" → 0.85)
- Ambiguous, unclear, or contradictory preferences → unparsed_preferences list

Valid instrument types (use these exact values): ETF, CORPORATE_BOND, SOVEREIGN_BOND,
STOCK, CEDEAR, MUTUAL_FUND, MONEY_MARKET, OTHER

Output format (strict JSON, no other text):
{
  "allowed_instrument_types": ["<instrument type>"],
  "excluded_instrument_types": ["<instrument type>"],
  "currency": "<currency code or null>",
  "country": "<country name or null>",
  "entity": "<entity name or null>",
  "hard_dollar_only": <true|false|null>,
  "avoid_sectors": ["<sector name>"],
  "prefer_sectors": ["<sector name>"],
  "avoid_issuers": ["<issuer name>"],
  "prefer_issuers": ["<issuer name>"],
  "min_liquidity_score": <0.0-1.0 or null>,
  "max_maturity_year": <integer year or null>,
  "hard_constraints": ["<constrained field name, e.g. instrument_type, currency, country, hard_dollar, entity, sector>"],
  "soft_preferences": ["<soft field name, e.g. sector, issuer, liquidity>"],
  "unparsed_preferences": ["<ambiguous or unclear preference>"],
  "confidence": <float 0.0-1.0>,
  "advisor_notes": ["<note for the advisor>"]
}
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

    def _call_api(self, user_message: str, system_prompt: str = _SYSTEM_PROMPT) -> str:
        """
        Llama a la API de OpenAI y devuelve el contenido de la respuesta como string.

        Args:
            user_message  : mensaje del usuario serializado.
            system_prompt : prompt de sistema a usar (default: _SYSTEM_PROMPT para KYC).
                            Pasar _FOLLOWUP_SYSTEM_PROMPT para el análisis de follow-up.

        Raises:
            ValueError: si la respuesta está vacía o la API falla.
        """
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
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

    # ── Construcción del user message (follow-up) ─────────────────────────────

    @staticmethod
    def _build_followup_user_message(payload: dict[str, Any]) -> str:
        """
        Construye el mensaje de usuario para la segunda ronda de análisis.

        El payload debe contener: client_id, original_kyc, previous_analysis,
        follow_up_answers.
        """
        try:
            payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"follow-up payload no es serializable a JSON: {exc}"
            ) from exc

        return (
            "Please analyze the following follow-up information and respond with ONLY a valid "
            "JSON object following the specified output format. No markdown, no prose.\n\n"
            f"FOLLOW-UP DATA:\n{payload_json}"
        )

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

        # confidence — bool debe rechazarse antes del chequeo numérico
        confidence = data["confidence"]
        _assert_not_bool(confidence, "confidence")
        if not isinstance(confidence, (int, float)):
            raise ValueError(
                f"OpenAI response field 'confidence' must be a number between 0 and 1, "
                f"got {type(confidence).__name__}: {confidence!r}"
            )
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(
                f"OpenAI response field 'confidence' must be a number between 0 and 1, "
                f"got {confidence!r}"
            )

        # contradictions — lista + estructura interna de cada item
        if not isinstance(data["contradictions"], list):
            raise ValueError(
                "Respuesta de IA inválida: 'contradictions' debe ser una lista, "
                f"recibido {type(data['contradictions']).__name__}."
            )
        _assert_contradiction_items(data["contradictions"], "contradictions")

        # follow_up_questions — lista + items deben ser strings
        if not isinstance(data["follow_up_questions"], list):
            raise ValueError(
                "Respuesta de IA inválida: 'follow_up_questions' debe ser una lista, "
                f"recibido {type(data['follow_up_questions']).__name__}."
            )
        _assert_list_of_str(data["follow_up_questions"], "follow_up_questions")

        # advisor_notes — lista + items deben ser strings
        if not isinstance(data["advisor_notes"], list):
            raise ValueError(
                "Respuesta de IA inválida: 'advisor_notes' debe ser una lista, "
                f"recibido {type(data['advisor_notes']).__name__}."
            )
        _assert_list_of_str(data["advisor_notes"], "advisor_notes")

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

    # ── Validación de respuesta follow-up ────────────────────────────────────

    @staticmethod
    def _validate_followup_response(data: dict[str, Any]) -> None:
        """
        Valida que el dict devuelto por la IA (follow-up) tenga la estructura esperada.

        Raises:
            ValueError: con mensaje descriptivo si la validación falla.
        """
        # Claves requeridas
        for key in _REQUIRED_FOLLOWUP_KEYS:
            if key not in data:
                raise ValueError(
                    f"Respuesta de IA inválida (follow-up): falta la clave requerida '{key}'. "
                    f"Claves presentes: {list(data.keys())}"
                )

        # revised_profile
        profile = data["revised_profile"]
        if not isinstance(profile, str) or profile not in _VALID_PROFILES:
            raise ValueError(
                f"Respuesta de IA inválida (follow-up): revised_profile={profile!r} "
                f"no es uno de los perfiles válidos: {sorted(_VALID_PROFILES)}"
            )

        # confidence — bool debe rechazarse antes del chequeo numérico
        confidence = data["confidence"]
        _assert_not_bool(confidence, "confidence", "follow-up")
        if not isinstance(confidence, (int, float)):
            raise ValueError(
                f"OpenAI response (follow-up) field 'confidence' must be a number between 0 and 1, "
                f"got {type(confidence).__name__}: {confidence!r}"
            )
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(
                f"OpenAI response (follow-up) field 'confidence' must be a number between 0 and 1, "
                f"got {confidence!r}"
            )

        # remaining_contradictions — lista + estructura interna de cada item
        if not isinstance(data["remaining_contradictions"], list):
            raise ValueError(
                "Respuesta de IA inválida (follow-up): 'remaining_contradictions' debe ser "
                f"una lista, recibido {type(data['remaining_contradictions']).__name__}."
            )
        _assert_contradiction_items(
            data["remaining_contradictions"], "remaining_contradictions", "follow-up"
        )

        # profile_change_reason — string no vacío
        reason = data["profile_change_reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                "Respuesta de IA inválida (follow-up): 'profile_change_reason' debe ser "
                "un string no vacío."
            )

        # advisor_notes — lista + items deben ser strings
        if not isinstance(data["advisor_notes"], list):
            raise ValueError(
                "Respuesta de IA inválida (follow-up): 'advisor_notes' debe ser una lista, "
                f"recibido {type(data['advisor_notes']).__name__}."
            )
        _assert_list_of_str(data["advisor_notes"], "advisor_notes", "follow-up")

    # ── API pública — follow-up ───────────────────────────────────────────────

    def analyze_follow_up(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Segunda ronda de análisis. Considera el KYC original, el análisis previo
        y las respuestas del cliente a las preguntas de follow-up.

        Args:
            payload: dict con las claves:
                client_id         : str
                original_kyc      : dict (campos KYC del primer análisis)
                previous_analysis : dict (resultado de analyze_kyc)
                follow_up_answers : list[dict] con {question: str, answer: str}

        Returns:
            dict con las claves:
                revised_profile          : str (uno de los 5 perfiles)
                confidence               : float [0.0, 1.0]
                remaining_contradictions : list[dict] (field, severity, explanation)
                profile_change_reason    : str (no vacío)
                advisor_notes            : list[str]

        Raises:
            ValueError: si el payload no es serializable, la API falla,
                        la respuesta no es JSON válido, o falla la validación.
        """
        user_message = self._build_followup_user_message(payload)
        raw_content = self._call_api(user_message, system_prompt=_FOLLOWUP_SYSTEM_PROMPT)

        # Parsear JSON
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"La IA devolvió JSON inválido (follow-up): {exc}. "
                f"Contenido recibido (primeros 200 chars): {raw_content[:200]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"La IA devolvió un JSON que no es un objeto (dict) (follow-up). "
                f"Tipo recibido: {type(data).__name__}."
            )

        self._validate_followup_response(data)
        return data

    # ── Construcción del user message (preferences) ───────────────────────────

    @staticmethod
    def _build_preferences_user_message(payload: dict[str, Any]) -> str:
        """
        Construye el mensaje de usuario para la extracción de preferencias.

        El payload debe contener al menos: client_id, natural_language_preferences.
        Opcionalmente: kyc_context, previous_profile_analysis.
        """
        try:
            payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"preferences payload no es serializable a JSON: {exc}"
            ) from exc

        return (
            "Please extract structured investment preferences from the following input "
            "and respond with ONLY a valid JSON object following the specified output format. "
            "No markdown, no prose.\n\n"
            f"PREFERENCES INPUT:\n{payload_json}"
        )

    # ── Validación de respuesta (preferences) ─────────────────────────────────

    @staticmethod
    def _validate_preferences_response(data: dict[str, Any]) -> None:
        """
        Valida que el dict devuelto por la IA (preferences) tenga la estructura esperada.

        Raises:
            ValueError: con mensaje descriptivo si la validación falla.
        """
        # Claves requeridas
        for key in _REQUIRED_PREFERENCES_KEYS:
            if key not in data:
                raise ValueError(
                    f"Respuesta de IA inválida (preferences): falta la clave requerida '{key}'. "
                    f"Claves presentes: {list(data.keys())}"
                )

        # allowed_instrument_types / excluded_instrument_types
        for field in ("allowed_instrument_types", "excluded_instrument_types"):
            val = data[field]
            if not isinstance(val, list):
                raise ValueError(
                    f"Respuesta de IA inválida (preferences): '{field}' debe ser una lista, "
                    f"recibido {type(val).__name__}."
                )
            # Los items deben ser strings antes de comparar con el enum
            for i, item in enumerate(val):
                if not isinstance(item, str):
                    raise ValueError(
                        f"OpenAI preferences field '{field}' must be a list of strings, "
                        f"but item at index {i} is {type(item).__name__}: {item!r}"
                    )
                if item not in _VALID_INSTRUMENT_TYPES:
                    raise ValueError(
                        f"Respuesta de IA inválida (preferences): {field} contiene tipo "
                        f"inválido {item!r}. Tipos válidos: {sorted(_VALID_INSTRUMENT_TYPES)}"
                    )

        # currency, country, entity — str no vacío or None
        for field in ("currency", "country", "entity"):
            val = data[field]
            if val is not None:
                if not isinstance(val, str):
                    raise ValueError(
                        f"OpenAI preferences field '{field}' must be str or null, "
                        f"got {type(val).__name__}: {val!r}"
                    )
                if not val.strip():
                    raise ValueError(
                        f"OpenAI preferences field '{field}' must be a non-empty string or null, "
                        f"got empty string."
                    )

        # hard_dollar_only — bool or None (no strings, no números)
        hdol = data["hard_dollar_only"]
        if hdol is not None and not isinstance(hdol, bool):
            raise ValueError(
                f"OpenAI preferences field 'hard_dollar_only' must be bool or null, "
                f"got {type(hdol).__name__}: {hdol!r}"
            )

        # List fields — lista + items deben ser strings
        _list_fields = (
            "avoid_sectors", "prefer_sectors",
            "avoid_issuers", "prefer_issuers",
            "hard_constraints", "soft_preferences",
            "unparsed_preferences", "advisor_notes",
        )
        for field in _list_fields:
            if not isinstance(data[field], list):
                raise ValueError(
                    f"Respuesta de IA inválida (preferences): '{field}' debe ser una lista, "
                    f"recibido {type(data[field]).__name__}."
                )
            _assert_list_of_str(data[field], field, "preferences")

        # min_liquidity_score — None or numeric (no bool) in [0, 1]
        liq = data["min_liquidity_score"]
        if liq is not None:
            _assert_not_bool(liq, "min_liquidity_score", "preferences")
            if not isinstance(liq, (int, float)):
                raise ValueError(
                    f"Respuesta de IA inválida (preferences): 'min_liquidity_score' debe ser "
                    f"numérico o null, recibido {type(liq).__name__}."
                )
            if not 0.0 <= float(liq) <= 1.0:
                raise ValueError(
                    f"OpenAI preferences field 'min_liquidity_score' must be a number between "
                    f"0 and 1, got {liq!r}"
                )

        # max_maturity_year — None or int (no bool) >= 1900
        year = data["max_maturity_year"]
        if year is not None:
            _assert_not_bool(year, "max_maturity_year", "preferences")
            if not isinstance(year, int):
                raise ValueError(
                    f"Respuesta de IA inválida (preferences): 'max_maturity_year' debe ser "
                    f"int o null, recibido {type(year).__name__}."
                )
            if year < 1900:
                raise ValueError(
                    f"OpenAI preferences field 'max_maturity_year' must be >= 1900, "
                    f"got {year!r}"
                )

        # confidence — numeric (no bool) in [0, 1]
        confidence = data["confidence"]
        _assert_not_bool(confidence, "confidence", "preferences")
        if not isinstance(confidence, (int, float)):
            raise ValueError(
                f"OpenAI response (preferences) field 'confidence' must be a number between "
                f"0 and 1, got {type(confidence).__name__}: {confidence!r}"
            )
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(
                f"OpenAI response (preferences) field 'confidence' must be a number between "
                f"0 and 1, got {confidence!r}"
            )

    # ── API pública — preferences ─────────────────────────────────────────────

    def extract_investment_preferences(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Extrae preferencias y restricciones de inversión estructuradas a partir de
        lenguaje natural.

        Args:
            payload: dict que puede incluir:
                client_id                  : str
                natural_language_preferences: str (texto libre del cliente)
                kyc_context                : dict | None
                previous_profile_analysis  : dict | None

        Returns:
            dict con las claves:
                allowed_instrument_types  : list[str]
                excluded_instrument_types : list[str]
                currency                  : str | None
                country                   : str | None
                entity                    : str | None
                hard_dollar_only          : bool | None
                avoid_sectors             : list[str]
                prefer_sectors            : list[str]
                avoid_issuers             : list[str]
                prefer_issuers            : list[str]
                min_liquidity_score       : float | None
                max_maturity_year         : int | None
                hard_constraints          : list[str]
                soft_preferences          : list[str]
                unparsed_preferences      : list[str]
                confidence                : float [0.0, 1.0]
                advisor_notes             : list[str]

        Raises:
            ValueError: si el payload no es serializable, la API falla,
                        la respuesta no es JSON válido, o falla la validación.
        """
        user_message = self._build_preferences_user_message(payload)
        raw_content = self._call_api(
            user_message, system_prompt=_PREFERENCES_SYSTEM_PROMPT
        )

        # Parsear JSON
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"La IA devolvió JSON inválido (preferences): {exc}. "
                f"Contenido recibido (primeros 200 chars): {raw_content[:200]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"La IA devolvió un JSON que no es un objeto (dict) (preferences). "
                f"Tipo recibido: {type(data).__name__}."
            )

        self._validate_preferences_response(data)
        return data
