"""
Risk Gap — mapper puro y determinístico.

Deriva un "Risk Gap" a partir del output de `analyze_kyc` (perfil declarado +
contradicciones) y, opcionalmente, del KYC payload (señal de estrés).

IMPORTANTE — qué ES y qué NO ES (ver docs/METHODOLOGY_NOTES.md):
    - NO mide ni infiere un "perfil conductual" del cliente.
    - SÍ marca la inconsistencia entre el perfil declarado y otras respuestas
      del cliente, y entrega preguntas para que el ASESOR la confirme.
    - El asesor decide el perfil. La IA solo propone la señal.

Es una función pura (sin IO, sin DB, sin LLM): mismo input → mismo output.
M-Engine reusa este mapper; solo cambia la fuente de las contradicciones (LLM).
"""

from __future__ import annotations

from typing import Any

# Preguntas por defecto cuando el análisis no trae follow-ups propios.
# Sondean capacidad y horizonte, NO repiten el escenario de estrés (evita la
# circularidad que un revisor técnico marcaría).
_DEFAULT_CONFIRMATION_QUESTIONS: tuple[str, ...] = (
    "¿Cuánto tiempo podés mantener esta inversión sin necesitar ese dinero?",
    "Si tuvieras una pérdida importante, ¿afectaría tus gastos del día a día?",
)

_MAX_CONFIRMATION_QUESTIONS: int = 2


def _normalize_severity(value: Any) -> str | None:
    """Normaliza severidades en inglés o español a {low, medium, high}."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in {"high", "alta"}:
        return "high"
    if v in {"medium", "media"}:
        return "medium"
    if v in {"low", "baja"}:
        return "low"
    return None


def derive_risk_gap(
    result: dict[str, Any],
    kyc_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Deriva el Risk Gap del output de `analyze_kyc`.

    Args:
        result: dict con (al menos) `preliminary_profile`, `contradictions`,
                `follow_up_questions` (formato OpenAIProfileClient.analyze_kyc).
        kyc_payload: dict del KYC; se usa `open_risk_reaction` como señal de estrés.

    Returns:
        dict con las claves de RiskGap, o None si no hay perfil declarado.
        gap_level ∈ {low, medium, high}. Sin contradicciones → low (alineado).
    """
    if not isinstance(result, dict):
        return None
    declared = result.get("preliminary_profile")
    if not declared or not isinstance(declared, str):
        return None

    contradictions_raw = result.get("contradictions")
    contradictions = [
        c for c in (contradictions_raw or []) if isinstance(c, dict)
    ]

    severities = {
        s for c in contradictions if (s := _normalize_severity(c.get("severity")))
    }
    if "high" in severities:
        gap_level = "high"
    elif "medium" in severities:
        gap_level = "medium"
    else:
        # low-severity-only o cero contradicciones → low (incluye el estado alineado).
        gap_level = "low"

    aligned = len(contradictions) == 0

    stress_signal = ""
    if isinstance(kyc_payload, dict):
        stress_signal = str(kyc_payload.get("open_risk_reaction") or "").strip()

    if aligned:
        gap_explanation = (
            f"El perfil declarado ({declared}) es consistente con las respuestas "
            "del cliente. No se detectó inconsistencia que confirmar. Esto NO es "
            "una medición del perfil conductual: es la ausencia de señales "
            "contradictorias en el KYC."
        )
    else:
        detail = "; ".join(
            s for c in contradictions
            if (s := str(c.get("explanation") or c.get("description") or "").strip())
        )
        gap_explanation = (
            f"El perfil declarado ({declared}) presenta inconsistencias con otras "
            f"respuestas del cliente"
            + (f": {detail}. " if detail else ". ")
            + "Esto NO es una medición del perfil conductual: es una "
            "inconsistencia para confirmar con el cliente."
        )

    follow_ups = [
        q for q in (result.get("follow_up_questions") or [])
        if isinstance(q, str) and q.strip()
    ]
    questions = follow_ups if follow_ups else list(_DEFAULT_CONFIRMATION_QUESTIONS)
    confirmation_questions = [q.strip() for q in questions][:_MAX_CONFIRMATION_QUESTIONS]

    return {
        "declared_profile": declared,
        "stress_signal": stress_signal,
        "gap_level": gap_level,
        "gap_explanation": gap_explanation,
        "confirmation_questions": confirmation_questions,
    }
