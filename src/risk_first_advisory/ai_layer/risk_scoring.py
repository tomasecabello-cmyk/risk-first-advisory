"""
M-Engine — motor de scoring de riesgo determinístico (sin LLM).

Implementa el algoritmo propio descrito en docs/RISK_SCORING_THEORY.md:

  - Perfil DECLARADO (stated): rúbrica transparente tipo Grable-Lytton sobre los
    scores del KYC. La CAPACIDAD acota la TOLERANCIA (no se puede asumir más riesgo
    del que la situación financiera soporta). Mapea a los 5 perfiles del sistema.
  - Señal REVELADA (revealed): del escenario de estrés (open_risk_reaction).
  - Risk Gap: inconsistencia entre declarado y revelado (+ tensión interna
    willingness-vs-ability), con preguntas para que el asesor la confirme.

Es una función pura: mismo input → mismo output. No usa OpenAI, no toca DB.
Reemplaza la heurística enlatada por un cómputo real y auditable. NO mide
"conducta": marca una inconsistencia para que el ASESOR decida (human-in-the-loop).

Distinto del método patentado de Nitrogen (ver RISK_SCORING_THEORY.md §4): escala de
5 perfiles (no 1-99), capacidad-acota-tolerancia explícito, y el gap declarado-vs-
revelado como output central.
"""

from __future__ import annotations

from typing import Any

# Perfiles ordenados de menor a mayor riesgo (los 5 del sistema).
PROFILES: tuple[str, ...] = (
    "conservador",
    "moderado-defensivo",
    "moderado",
    "moderado-agresivo",
    "agresivo",
)

# Señales léxicas para la respuesta al escenario de estrés (open_risk_reaction).
_PANIC_HINTS: tuple[str, ...] = (
    "vend", "pánico", "panico", "todo", "salir", "salgo", "miedo",
    "no soporto", "no aguanto", "saco", "retiro", "liquido", "asust",
)
_COMPOSED_HINTS: tuple[str, ...] = (
    "mantengo", "mantener", "aguanto", "espero", "compro", "comprar",
    "largo plazo", "oportunidad", "no me asusta", "tranquil", "aprovecho",
)

_EXPERIENCE_PTS: dict[str, float] = {
    "ninguna": 0.10, "basica": 0.30, "básica": 0.30,
    "moderada": 0.55, "avanzada": 0.80, "experto": 1.00,
}
_OBJECTIVE_PTS: dict[str, float] = {
    "capital_preservation": 0.10, "income": 0.30, "balanced": 0.50,
    "growth": 0.80, "aggressive_growth": 1.00,
}


def _clamp01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def _score_1_10(v: Any, default: float = 5.0) -> float:
    """Normaliza un score 1-10 a [0,1]."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        n = default
    return _clamp01((n - 1.0) / 9.0)


def _horizon_pts(years: Any) -> float:
    try:
        y = float(years)
    except (TypeError, ValueError):
        return 0.5
    if y <= 2:
        return 0.10
    if y <= 4:
        return 0.35
    if y <= 7:
        return 0.60
    if y <= 15:
        return 0.85
    return 1.00


def _liquidity_inv_pts(score: Any) -> float:
    """Necesidad de liquidez alta -> menor capacidad de riesgo. Escala 3/5/8."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return 0.5
    # 3 (baja) -> 0.80 ; 5 (media) -> 0.50 ; 8 (alta) -> 0.15. Interpolado fuera de esos.
    if s <= 3:
        return 0.80
    if s <= 5:
        return 0.50
    if s <= 8:
        return 0.15
    return 0.10


def _profile_from_score(score_0_100: float) -> str:
    """Mapea un score 0-100 a uno de los 5 perfiles por bandas de 20."""
    idx = int(score_0_100 // 20)
    if idx > 4:
        idx = 4
    if idx < 0:
        idx = 0
    return PROFILES[idx]


def _profile_index(profile: str) -> int:
    try:
        return PROFILES.index(profile)
    except ValueError:
        return 2  # default moderado


def score_stated_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Perfil declarado desde el KYC. La capacidad acota la tolerancia:
    riesgo efectivo = min(willingness, ability).

    Returns dict: profile, score (0-100), willingness, ability, binding_dimension,
    internal_gap (|willingness-ability| en bandas).
    """
    p = payload or {}
    tolerance = _score_1_10(p.get("risk_tolerance_score"))
    capacity = _score_1_10(p.get("risk_capacity_score"))
    horizon = _horizon_pts(p.get("investment_horizon_years"))
    liquidity_inv = _liquidity_inv_pts(p.get("liquidity_need_score"))
    experience = _EXPERIENCE_PTS.get(str(p.get("investment_experience", "")).lower(), 0.5)
    objective = _OBJECTIVE_PTS.get(str(p.get("investment_objective", "")).lower(), 0.5)

    # Willingness (lo que el cliente QUIERE) vs Ability (lo que PUEDE soportar).
    willingness = _clamp01(0.6 * tolerance + 0.4 * objective)
    ability = _clamp01(0.4 * capacity + 0.3 * horizon + 0.2 * liquidity_inv + 0.1 * experience)

    effective = min(willingness, ability)  # capacidad/ability acota
    score = round(effective * 100.0, 1)
    profile = _profile_from_score(score)
    binding = "ability" if ability <= willingness else "willingness"

    # Distancia en bandas entre lo que quiere y lo que puede (tensión interna).
    internal_gap_bands = abs(_profile_index(_profile_from_score(willingness * 100))
                             - _profile_index(_profile_from_score(ability * 100)))

    return {
        "profile": profile,
        "score": score,
        "willingness": round(willingness, 3),
        "ability": round(ability, 3),
        "binding_dimension": binding,
        "internal_gap_bands": internal_gap_bands,
    }


def assess_revealed_signal(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Señal revelada desde la respuesta al escenario de estrés (open_risk_reaction).

    Returns dict: direction ('lower' | 'composed' | 'none'), evidence (texto).
    'lower' = reaccionaría más conservador que lo declarado (pánico/venta).
    'composed' = mantiene/aprovecha (consistente con tomar riesgo).
    """
    reaction = str((payload or {}).get("open_risk_reaction") or "").lower().strip()
    if not reaction:
        return {"direction": "none", "evidence": ""}
    if any(h in reaction for h in _PANIC_HINTS):
        return {"direction": "lower", "evidence": reaction}
    if any(h in reaction for h in _COMPOSED_HINTS):
        return {"direction": "composed", "evidence": reaction}
    return {"direction": "none", "evidence": reaction}


_DEFAULT_QUESTIONS: tuple[str, ...] = (
    "¿Cuánto tiempo podés mantener esta inversión sin necesitar ese dinero?",
    "Si tuvieras una pérdida importante, ¿afectaría tus gastos del día a día?",
)


def compute_risk_gap(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Risk Gap real (determinístico) desde el KYC. Combina:
      - perfil declarado (score_stated_profile),
      - señal revelada del escenario de estrés,
      - tensión interna willingness-vs-ability.

    Returns un dict con la misma forma que consume el schema RiskGap:
    declared_profile, stress_signal, gap_level (low|medium|high),
    gap_explanation, confirmation_questions. (+ campos de diagnóstico.)
    """
    stated = score_stated_profile(payload)
    revealed = assess_revealed_signal(payload)
    declared_profile = stated["profile"]
    declared_idx = _profile_index(declared_profile)

    # gap_bands: cuánto baja el perfil revelado respecto del declarado.
    # 'lower' empuja a conservador (índice 0). Estimamos el revelado como
    # min(declarado, conservador+0) cuando hay pánico: la distancia es declared_idx.
    revealed_drop = declared_idx if revealed["direction"] == "lower" else 0
    internal = stated["internal_gap_bands"]
    severity_bands = max(revealed_drop, internal)

    if severity_bands >= 3:
        gap_level = "high"
    elif severity_bands == 2:
        gap_level = "medium"
    elif severity_bands == 1:
        gap_level = "low"
    else:
        gap_level = "low"  # alineado

    aligned = severity_bands == 0
    if aligned:
        gap_explanation = (
            f"El perfil declarado ({declared_profile}) es consistente con la capacidad "
            "financiera y con la reacción del cliente. No se detectó inconsistencia que "
            "confirmar. Esto NO es una medición del perfil conductual."
        )
    else:
        partes = []
        if revealed["direction"] == "lower":
            partes.append(
                "ante una caída el cliente reaccionaría más conservador que su perfil declarado")
        if internal >= 1:
            quiere = "más" if stated["willingness"] > stated["ability"] else "menos"
            partes.append(
                f"lo que el cliente quiere asumir es {quiere} de lo que su situación "
                f"financiera soporta (dimensión que limita: {stated['binding_dimension']})")
        detalle = "; ".join(partes) if partes else "hay señales contradictorias"
        gap_explanation = (
            f"El perfil declarado ({declared_profile}) presenta una inconsistencia: "
            f"{detalle}. Esto NO es una medición del perfil conductual: es una "
            "inconsistencia para confirmar con el cliente."
        )

    return {
        "declared_profile": declared_profile,
        "stress_signal": revealed["evidence"],
        "gap_level": gap_level,
        "gap_explanation": gap_explanation,
        "confirmation_questions": list(_DEFAULT_QUESTIONS),
        # diagnóstico (no parte del schema RiskGap; útil para tests / Modo técnico):
        "_stated": stated,
        "_revealed_direction": revealed["direction"],
        "_severity_bands": severity_bands,
    }
