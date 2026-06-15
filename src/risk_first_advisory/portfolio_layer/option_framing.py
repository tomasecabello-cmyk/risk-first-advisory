"""
option_framing — encuadre A/B de las carteras candidatas + explicación por opción.

Convierte las 3 variantes (DEFENSIVE/BALANCED/GROWTH) en la conversación que el
asesor tiene con el cliente:

  - Grupo A · "dentro de tu capacidad": variantes que NO exceden el presupuesto de
    riesgo aprobado (no requieren override). Son las opciones "seguras".
  - Grupo B · "requiere override": variantes que buscan más retorno excediendo el
    presupuesto → necesitan firma explícita del asesor (el cliente asume más riesgo
    del que su perfil aprobado soporta).

Para cada opción produce un `rationale` en español que explica el porqué, cruzando
volatilidad, retorno, diversificación (HHI/score/flags) y estado de override. Es la
lente "la IA interpreta, no recalcula" del markowitz-optimizer, pero determinística
(sin red, sin LLM): mismas carteras → misma explicación, auditable. Un path con LLM
puede envolver esto más adelante sin cambiar el contrato.
"""

from __future__ import annotations

from typing import Any

ROLE_WITHIN = "dentro_de_capacidad"   # Grupo A
ROLE_OVERRIDE = "requiere_override"   # Grupo B

GROUP_A_LABEL = "Dentro de tu capacidad (sin override)"
GROUP_B_LABEL = "Más retorno, requiere override firmado"


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _div_phrase(div: dict[str, Any]) -> str:
    """Frase corta sobre la diversificación de la cartera."""
    if not div:
        return "sin descomposición de diversificación"
    score = div.get("diversification_score")
    band = div.get("concentration_band", "—")
    n = div.get("holdings_count", 0)
    base = f"{n} posiciones, diversificación {round(score) if isinstance(score, (int, float)) else '—'}/100 (concentración {band})"
    flags = div.get("flags") or []
    if flags:
        legibles = {
            "concentracion_single_asset": "una posición pesa demasiado",
            "clase_unica": "una sola clase de activo",
            "pocas_posiciones": "pocas posiciones",
            "concentracion_sectorial": "sector dominante",
        }
        notas = [legibles.get(f, f) for f in flags]
        base += f"; ojo: {', '.join(notas)}"
    return base


def _rationale(candidate: dict[str, Any], role: str) -> str:
    variant = candidate.get("variant", "?")
    vol = _pct(candidate.get("volatility_annual"))
    ret = _pct(candidate.get("expected_return_annual"))
    div_phrase = _div_phrase(candidate.get("diversification") or {})

    if role == ROLE_WITHIN:
        return (
            f"{variant}: retorno esperado {ret} con volatilidad {vol}, dentro de tu "
            f"presupuesto de riesgo aprobado — no requiere override. Reparte el riesgo en "
            f"{div_phrase}."
        )
    meta = candidate.get("metadata") or {}
    exceeded = meta.get("exceeded_constraints") or []
    exc = ", ".join(exceeded) if exceeded else "el presupuesto de riesgo"
    return (
        f"{variant}: busca más retorno ({ret}) pero su volatilidad ({vol}) excede {exc} "
        f"del perfil aprobado, así que requiere tu firma (override). Es la cartera mejor "
        f"diversificada posible dentro de ese riesgo más alto: {div_phrase}."
    )


def frame_portfolio_options(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Encuadra las carteras candidatas en grupos A (dentro de capacidad) / B (override)
    y arma una explicación por opción.

    `candidates`: lista de dicts serializados de cartera (variant, volatility_annual,
    expected_return_annual, diversification, metadata.requires_advisor_override...).

    Returns dict: options (list con variant, option_role, group_label, rationale),
    group_a_count, group_b_count, summary (es). Función pura.
    """
    options: list[dict[str, Any]] = []
    a_count = b_count = 0
    for c in candidates or []:
        meta = c.get("metadata") or {}
        override = bool(meta.get("requires_advisor_override"))
        role = ROLE_OVERRIDE if override else ROLE_WITHIN
        if override:
            b_count += 1
        else:
            a_count += 1
        options.append({
            "variant": c.get("variant", "?"),
            "option_role": role,
            "group_label": GROUP_B_LABEL if override else GROUP_A_LABEL,
            "rationale": _rationale(c, role),
        })

    if a_count and b_count:
        summary = (
            f"Tenés {a_count} cartera(s) dentro de tu capacidad (sin override) y "
            f"{b_count} que busca(n) más retorno pero requiere(n) override firmado. "
            "Si el cliente quiere más riesgo del que su perfil soporta, la decisión "
            "es del asesor y queda en auditoría."
        )
    elif a_count:
        summary = (
            f"Las {a_count} cartera(s) propuesta(s) están dentro de tu presupuesto de "
            "riesgo aprobado — ninguna requiere override."
        )
    elif b_count:
        summary = (
            f"Las {b_count} cartera(s) propuesta(s) exceden el presupuesto aprobado y "
            "requieren override firmado del asesor."
        )
    else:
        summary = "No hay carteras candidatas para encuadrar."

    return {
        "options": options,
        "group_a_count": a_count,
        "group_b_count": b_count,
        "summary": summary,
    }
