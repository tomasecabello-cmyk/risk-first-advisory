"""
Risk Number — número único de riesgo 0–100, comparable cliente ↔ cartera.

Idea unificadora (docs/RISK_NUMBER_DESIGN.md §5): anclar la escala en riesgo de
DOWNSIDE para que cliente y cartera sean comparables. La cartera produce un
downside real (CVaR a horizonte configurable); el cliente produce un downside
aceptable (del cuestionario Grable-Lytton y de la pregunta de trade-off vía
certainty equivalent → γ CRRA). Misma función de mapeo → mismo número 0–100 →
alineación ("tu número es 62, esta cartera es 68").

Método propio, diferenciado del patentado de Nitrogen/Riskalyze
(docs/RISK_SCORING_THEORY.md §2/§4). Ejes de diferenciación deliberados:
  - escala propia 0–100 en bandas de 20 (los 5 perfiles del sistema), NO 1–99;
  - métrica de cartera CVaR/Expected Shortfall (NO "rango 95% a 6 meses");
  - horizonte CONFIGURABLE (no fijo);
  - el cross-check declarado-vs-trade-off es una señal de INCONSISTENCIA para
    que el asesor confirme (Risk Gap), no una medición conductual.

Función pura: mismo input → mismo output. No usa OpenAI, no toca DB ni red.
AI/motor PROPONE, el asesor DECIDE (I-001): nada de este módulo aprueba nada.

Calibraciones (anchors) = supuestos DEMO, tuneables: los anclajes de downside
derivan de los max_drawdown de config/risk_profiles.yaml; los de γ, de rangos
típicos de aversión relativa al riesgo en la literatura CRRA. No reemplazan un
proceso de CMA ni la decisión de un comité de inversiones.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from risk_first_advisory.ai_layer.risk_scoring import (
    PROFILES,
    score_stated_profile,
)

# ---------------------------------------------------------------------------
# Escala y bandas
# ---------------------------------------------------------------------------

SCALE_MIN: float = 0.0
SCALE_MAX: float = 100.0

# Anclajes downside → número. Derivados de los max_drawdown por perfil en
# config/risk_profiles.yaml: el tope de cada banda de 20 puntos corresponde a
# la pérdida máxima tolerada por ese perfil (conservador -7% → 20, ...,
# agresivo -30% → 100). Pérdida como fracción POSITIVA.
DOWNSIDE_ANCHORS: tuple[tuple[float, float], ...] = (
    (0.00, 0.0),
    (0.07, 20.0),   # conservador: max_drawdown -0.070
    (0.10, 40.0),   # moderado-defensivo: -0.100
    (0.15, 60.0),   # moderado: -0.150
    (0.22, 80.0),   # moderado-agresivo: -0.220
    (0.30, 100.0),  # agresivo: -0.300
)

# Anclajes γ (CRRA) → número. γ alto = más averso al riesgo = número más bajo.
# Rangos típicos de la literatura: γ≈1 (log) inversor moderado-tolerante,
# γ 2–4 moderado, γ>8 muy averso, γ≤0 neutral/buscador de riesgo.
GAMMA_ANCHORS: tuple[tuple[float, float], ...] = (
    (-2.0, 100.0),
    (0.0, 95.0),
    (0.5, 85.0),
    (1.0, 70.0),
    (2.0, 55.0),
    (3.0, 45.0),
    (5.0, 30.0),
    (8.0, 15.0),
    (12.0, 5.0),
)

_GAMMA_MIN: float = -4.0
_GAMMA_MAX: float = 20.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def _piecewise_linear(x: float, anchors: tuple[tuple[float, float], ...]) -> float:
    """Interpola linealmente sobre anchors ordenados por x; clampa en los bordes."""
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:], strict=False):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return anchors[-1][1]  # inalcanzable con anchors ordenados


def number_to_band(number: float) -> str:
    """Mapea un número 0–100 a uno de los 5 perfiles por bandas de 20."""
    idx = int(_clamp(number, SCALE_MIN, SCALE_MAX) // 20)
    return PROFILES[min(idx, len(PROFILES) - 1)]


def _band_index(number: float) -> int:
    return PROFILES.index(number_to_band(number))


# ---------------------------------------------------------------------------
# Lado CARTERA — CVaR a horizonte configurable → número
# ---------------------------------------------------------------------------

_STD_NORMAL = NormalDist()


def _norm_pdf(z: float) -> float:
    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _norm_ppf(p: float) -> float:
    """Cuantil normal estándar (stdlib statistics.NormalDist)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p debe estar en (0,1). Recibido: {p}.")
    return _STD_NORMAL.inv_cdf(p)


def portfolio_downside(
    mu_annual: float | None = None,
    sigma_annual: float | None = None,
    returns: list[float] | None = None,
    horizon_years: float = 1.0,
    alpha: float = 0.95,
) -> dict[str, Any]:
    """
    Downside de la cartera: CVaR/Expected Shortfall al nivel `alpha` sobre un
    horizonte CONFIGURABLE (en años).

    Dos vías (exclusivas por prioridad):
      - `returns` (lista de retornos simples YA expresados al horizonte deseado,
        p.ej. retornos anuales/ventanas móviles): CVaR EMPÍRICO = media del peor
        (1-alpha) de la muestra. No se re-escala por horizonte.
      - `mu_annual` + `sigma_annual` (anuales): CVaR paramétrico normal
        escalado al horizonte: mu_h = mu·h, sigma_h = sigma·√h,
        ES = mu_h − sigma_h · φ(z_alpha)/(1−alpha).

    Returns dict: cvar (retorno esperado en la cola, con signo),
    downside_loss (fracción de pérdida POSITIVA, 0 si la cola es ganadora),
    method ('empirical'|'normal'), horizon_years, alpha, sample_size.
    Función pura, sin red.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha debe estar en (0,1). Recibido: {alpha}.")
    if horizon_years <= 0:
        raise ValueError(f"horizon_years debe ser > 0. Recibido: {horizon_years}.")

    if returns:
        rets = sorted(float(r) for r in returns)
        # floor con epsilon: evita que 20·0.05 = 1.0000000000000009 arrastre
        # una observación de más a la cola.
        tail_n = max(1, math.floor(len(rets) * (1.0 - alpha) + 1e-9))
        tail = rets[:tail_n]
        cvar = sum(tail) / len(tail)
        return {
            "cvar": cvar,
            "downside_loss": max(0.0, -cvar),
            "method": "empirical",
            "horizon_years": horizon_years,
            "alpha": alpha,
            "sample_size": len(rets),
        }

    if mu_annual is None or sigma_annual is None:
        raise ValueError(
            "Se requiere `returns` o el par `mu_annual` + `sigma_annual`."
        )
    if sigma_annual < 0:
        raise ValueError(f"sigma_annual debe ser >= 0. Recibido: {sigma_annual}.")

    mu_h = float(mu_annual) * horizon_years
    sigma_h = float(sigma_annual) * math.sqrt(horizon_years)
    z = _norm_ppf(alpha)
    es = mu_h - sigma_h * _norm_pdf(z) / (1.0 - alpha)
    return {
        "cvar": es,
        "downside_loss": max(0.0, -es),
        "method": "normal",
        "horizon_years": horizon_years,
        "alpha": alpha,
        "sample_size": 0,
    }


def downside_to_number(
    loss_fraction: float,
    anchors: tuple[tuple[float, float], ...] = DOWNSIDE_ANCHORS,
) -> float:
    """Mapea una pérdida (fracción positiva) al número 0–100 vía anchors documentados."""
    if loss_fraction < 0:
        raise ValueError(f"loss_fraction debe ser >= 0. Recibido: {loss_fraction}.")
    return round(_piecewise_linear(loss_fraction, anchors), 1)


def portfolio_risk_number(
    mu_annual: float | None = None,
    sigma_annual: float | None = None,
    returns: list[float] | None = None,
    horizon_years: float = 1.0,
    alpha: float = 0.95,
) -> dict[str, Any]:
    """
    Número de riesgo 0–100 de una cartera, desde su downside (CVaR).

    Returns dict: number, band (perfil equivalente), downside_loss, cvar,
    method, horizon_years, alpha, explanation (es).
    """
    d = portfolio_downside(
        mu_annual=mu_annual, sigma_annual=sigma_annual, returns=returns,
        horizon_years=horizon_years, alpha=alpha,
    )
    number = downside_to_number(d["downside_loss"])
    band = number_to_band(number)
    pct = d["downside_loss"] * 100.0
    horizon_label = (
        f"{horizon_years:g} año" if horizon_years == 1.0 else f"{horizon_years:g} años"
    )
    explanation = (
        f"En el peor {round((1 - alpha) * 100):d}% de los escenarios a {horizon_label}, "
        f"la pérdida esperada de esta cartera es {pct:.1f}%. En la escala del sistema "
        f"eso es un número de riesgo {number:.0f}/100 (banda «{band}»)."
    )
    return {
        "number": number,
        "band": band,
        "downside_loss": round(d["downside_loss"], 4),
        "cvar": round(d["cvar"], 4),
        "method": d["method"],
        "horizon_years": horizon_years,
        "alpha": alpha,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Lado CLIENTE — trade-off (certainty equivalent → γ CRRA) → número
# ---------------------------------------------------------------------------

def _crra_utility(x: float, gamma: float) -> float:
    if x <= 0:
        raise ValueError(f"La riqueza debe ser > 0 en toda rama. Recibido: {x}.")
    if abs(1.0 - gamma) < 1e-9:
        return math.log(x)
    return (x ** (1.0 - gamma)) / (1.0 - gamma)


def _crra_certainty_equivalent(
    wealth: float, gain: float, loss: float, gamma: float
) -> float:
    """CE (sobre la riqueza inicial) de la apuesta 50/50 ganar `gain` / perder `loss`."""
    eu = 0.5 * _crra_utility(wealth + gain, gamma) + 0.5 * _crra_utility(wealth - loss, gamma)
    if abs(1.0 - gamma) < 1e-9:
        ce_wealth = math.exp(eu)
    else:
        ce_wealth = ((1.0 - gamma) * eu) ** (1.0 / (1.0 - gamma))
    return ce_wealth - wealth


def crra_gamma_from_certainty_equivalent(
    wealth: float, gain: float, loss: float, certain_amount: float
) -> float:
    """
    Coeficiente de aversión al riesgo γ (CRRA) implícito en la respuesta a la
    pregunta de trade-off: "¿qué monto SEGURO te resulta indiferente frente a
    una apuesta 50/50 de ganar `gain` o perder `loss`?" (fórmula en
    docs/RISK_SCORING_THEORY.md §4). Resuelve por bisección:

        0.5·u(W+G) + 0.5·u(W−L) = u(W+C),  u(x) = x^(1−γ)/(1−γ)

    γ se clampa a [-4, 20] (fuera de eso la respuesta ya no discrimina).
    Función pura.
    """
    if wealth <= 0:
        raise ValueError(f"wealth debe ser > 0. Recibido: {wealth}.")
    if gain <= 0:
        raise ValueError(f"gain debe ser > 0. Recibido: {gain}.")
    if loss < 0:
        raise ValueError(f"loss debe ser >= 0. Recibido: {loss}.")
    if wealth - loss <= 0:
        raise ValueError("loss no puede dejar la riqueza en cero o negativa.")
    if not (-loss < certain_amount < gain):
        raise ValueError(
            f"certain_amount debe estar entre -loss y gain "
            f"({-loss} < C < {gain}). Recibido: {certain_amount}."
        )

    # CE(γ) es decreciente en γ: si ni el extremo más buscador de riesgo alcanza
    # el C declarado, clampamos al borde correspondiente.
    if _crra_certainty_equivalent(wealth, gain, loss, _GAMMA_MIN) <= certain_amount:
        return _GAMMA_MIN
    if _crra_certainty_equivalent(wealth, gain, loss, _GAMMA_MAX) >= certain_amount:
        return _GAMMA_MAX

    lo, hi = _GAMMA_MIN, _GAMMA_MAX
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _crra_certainty_equivalent(wealth, gain, loss, mid) > certain_amount:
            lo = mid  # el CE todavía es alto → falta aversión → subir γ
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    return round(0.5 * (lo + hi), 4)


def gamma_to_number(
    gamma: float,
    anchors: tuple[tuple[float, float], ...] = GAMMA_ANCHORS,
) -> float:
    """Mapea γ (CRRA) al número 0–100 (γ alto = averso = número bajo)."""
    return round(_clamp(_piecewise_linear(gamma, anchors), SCALE_MIN, SCALE_MAX), 1)


def tradeoff_risk_number(
    wealth: float, gain: float, loss: float, certain_amount: float
) -> dict[str, Any]:
    """
    Número de riesgo 0–100 desde la pregunta de trade-off (CE → γ CRRA → número).

    Returns dict: number, band, gamma, certainty_equivalent (el C declarado).
    """
    gamma = crra_gamma_from_certainty_equivalent(wealth, gain, loss, certain_amount)
    number = gamma_to_number(gamma)
    return {
        "number": number,
        "band": number_to_band(number),
        "gamma": gamma,
        "certainty_equivalent": certain_amount,
    }


# ---------------------------------------------------------------------------
# Lado CLIENTE — número combinado + cross-check de divergencia
# ---------------------------------------------------------------------------

_DIVERGENCE_QUESTIONS: tuple[str, ...] = (
    "En el cuestionario respondiste con más apetito de riesgo que en la pregunta "
    "de montos concretos (o al revés). ¿Con cuál te identificás más?",
    "Pensando en plata real tuya: ¿qué pérdida en un año te haría cambiar de estrategia?",
)


def client_risk_number(
    payload: dict[str, Any],
    tradeoff: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Número de riesgo 0–100 del CLIENTE, con las dos elicitaciones cruzadas:

      - willingness del KYC (cuestionario Grable-Lytton u objetivo declarado,
        vía score_stated_profile) → número declarado;
      - opcional `tradeoff` = {wealth, gain, loss, certain_amount} → número
        vía certainty equivalent → γ CRRA.

    Si ambas existen, el número es el promedio y la DIVERGENCIA entre ambas
    (en bandas de 20) se expone como señal de inconsistencia con preguntas de
    confirmación para el asesor — mismo espíritu que el Risk Gap: esto NO es
    una medición conductual, es una inconsistencia a confirmar.

    También expone el TECHO DE CAPACIDAD (ability) en la misma escala: el
    número de cartera no debería superarlo sin override explícito del asesor.

    Returns dict: number, band, willingness_number, tradeoff_number, gamma,
    divergence_bands, inconsistent, capacity_ceiling_number,
    capacity_ceiling_band, confirmation_questions, explanation (es).
    """
    stated = score_stated_profile(payload)
    willingness_number = round(stated["willingness"] * 100.0, 1)
    ceiling_number = round(stated["ability"] * 100.0, 1)

    tradeoff_number: float | None = None
    gamma: float | None = None
    if tradeoff:
        t = tradeoff_risk_number(
            wealth=float(tradeoff["wealth"]),
            gain=float(tradeoff["gain"]),
            loss=float(tradeoff["loss"]),
            certain_amount=float(tradeoff["certain_amount"]),
        )
        tradeoff_number = t["number"]
        gamma = t["gamma"]

    if tradeoff_number is not None:
        number = round(0.5 * willingness_number + 0.5 * tradeoff_number, 1)
        divergence_bands = abs(
            _band_index(willingness_number) - _band_index(tradeoff_number)
        )
    else:
        number = willingness_number
        divergence_bands = 0

    inconsistent = divergence_bands >= 1
    band = number_to_band(number)

    if inconsistent:
        explanation = (
            f"Las dos elicitaciones divergen: el cuestionario declara "
            f"{willingness_number:.0f}/100 pero la pregunta de trade-off implica "
            f"{tradeoff_number:.0f}/100 ({divergence_bands} banda(s) de diferencia). "
            f"Número combinado provisorio: {number:.0f}/100 («{band}»). Confirmar con "
            "el cliente antes de usarlo — esto es una inconsistencia, no una medición."
        )
    else:
        explanation = (
            f"Número de riesgo del cliente: {number:.0f}/100 («{band}»). "
            f"Su capacidad financiera soporta hasta {ceiling_number:.0f}/100 "
            f"(«{number_to_band(ceiling_number)}»)."
        )

    return {
        "number": number,
        "band": band,
        "willingness_number": willingness_number,
        "tradeoff_number": tradeoff_number,
        "gamma": gamma,
        "divergence_bands": divergence_bands,
        "inconsistent": inconsistent,
        "capacity_ceiling_number": ceiling_number,
        "capacity_ceiling_band": number_to_band(ceiling_number),
        "confirmation_questions": list(_DIVERGENCE_QUESTIONS) if inconsistent else [],
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Alineación cliente ↔ cartera ↔ capacidad
# ---------------------------------------------------------------------------

# Holgura en puntos para considerar cliente y cartera "alineados" (media banda).
ALIGNMENT_TOLERANCE_POINTS: float = 10.0


def align_numbers(
    client_number: float,
    capacity_ceiling_number: float,
    portfolio_number: float,
    tolerance_points: float = ALIGNMENT_TOLERANCE_POINTS,
) -> dict[str, Any]:
    """
    Compara los tres números en la misma escala 0–100 y clasifica la alineación.

    status:
      - 'over_capacity'   la cartera está en una banda MÁS riesgosa que el techo
                          de capacidad → requiere override explícito del asesor
                          (misma semántica de bandas que deterministic_ceiling);
      - 'over_tolerance'  dentro de capacidad, pero > tolerancia del cliente
                          + holgura → conversación de ajuste;
      - 'aligned'         dentro de ±holgura del número del cliente;
      - 'under_tolerance' más conservadora que la tolerancia − holgura → hay
                          margen para tomar más riesgo si el cliente quiere.

    Este módulo INFORMA la conversación; aprobar/elegir sigue siendo del asesor
    vía los endpoints humanos (I-001/I-016/I-019). Función pura.

    Returns dict: status, override_required, gap_points (cartera − cliente),
    capacity_gap_bands (bandas por encima del techo), explanation (es).
    """
    if tolerance_points < 0:
        raise ValueError(f"tolerance_points debe ser >= 0. Recibido: {tolerance_points}.")

    gap_points = round(portfolio_number - client_number, 1)
    capacity_gap_bands = max(
        0, _band_index(portfolio_number) - _band_index(capacity_ceiling_number)
    )

    if capacity_gap_bands > 0:
        status = "over_capacity"
        banda = "banda" if capacity_gap_bands == 1 else "bandas"
        explanation = (
            f"La cartera ({portfolio_number:.0f}/100) está {capacity_gap_bands} {banda} "
            f"por encima del techo de capacidad del cliente "
            f"({capacity_ceiling_number:.0f}/100). Elegirla requiere override explícito "
            "del asesor, firmado y auditado: el cliente asumiría más riesgo del que su "
            "situación financiera soporta."
        )
    elif gap_points > tolerance_points:
        status = "over_tolerance"
        explanation = (
            f"La cartera ({portfolio_number:.0f}/100) supera la tolerancia del cliente "
            f"({client_number:.0f}/100) en {gap_points:.0f} puntos, aunque está dentro "
            "de su capacidad. Conviene bajar el riesgo de la cartera o confirmar con el "
            "cliente que acepta la diferencia."
        )
    elif gap_points < -tolerance_points:
        status = "under_tolerance"
        explanation = (
            f"La cartera ({portfolio_number:.0f}/100) es más conservadora que la "
            f"tolerancia del cliente ({client_number:.0f}/100) por "
            f"{-gap_points:.0f} puntos. Hay margen para tomar más riesgo si el cliente "
            "lo quiere — o es una elección deliberada de prudencia."
        )
    else:
        status = "aligned"
        explanation = (
            f"La cartera ({portfolio_number:.0f}/100) está alineada con el número del "
            f"cliente ({client_number:.0f}/100) y dentro de su capacidad "
            f"({capacity_ceiling_number:.0f}/100)."
        )

    return {
        "status": status,
        "override_required": status == "over_capacity",
        "gap_points": gap_points,
        "capacity_gap_bands": capacity_gap_bands,
        "explanation": explanation,
    }


def assess_risk_alignment(
    payload: dict[str, Any],
    *,
    mu_annual: float | None = None,
    sigma_annual: float | None = None,
    returns: list[float] | None = None,
    horizon_years: float = 1.0,
    alpha: float = 0.95,
    tradeoff: dict[str, Any] | None = None,
    tolerance_points: float = ALIGNMENT_TOLERANCE_POINTS,
) -> dict[str, Any]:
    """
    Conveniencia end-to-end (pura): KYC + cartera → los dos números + alineación.

    Returns dict: client (client_risk_number), portfolio (portfolio_risk_number),
    alignment (align_numbers).
    """
    client = client_risk_number(payload, tradeoff=tradeoff)
    portfolio = portfolio_risk_number(
        mu_annual=mu_annual, sigma_annual=sigma_annual, returns=returns,
        horizon_years=horizon_years, alpha=alpha,
    )
    alignment = align_numbers(
        client_number=client["number"],
        capacity_ceiling_number=client["capacity_ceiling_number"],
        portfolio_number=portfolio["number"],
        tolerance_points=tolerance_points,
    )
    return {"client": client, "portfolio": portfolio, "alignment": alignment}
