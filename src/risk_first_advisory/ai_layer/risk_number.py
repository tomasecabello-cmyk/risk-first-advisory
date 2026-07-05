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

Función pura: mismo input → mismo output. No usa OpenAI, no toca DB ni red
(la única I/O es la lectura cacheada de config/risk_profiles.yaml al importar,
mismo patrón que rules_layer/risk_budget_builder). AI/motor PROPONE, el asesor
DECIDE (I-001): nada de este módulo aprueba nada — la alineación es
INFORMATIVA; el override formal lo gobiernan los mecanismos existentes
(profile-approval y metadata.requires_advisor_override en la selección, I-018).

Calibración de la escala (DD-012): los anclajes downside se DERIVAN al importar
del max_volatility por perfil de config/risk_profiles.yaml, transformado con el
mismo CVaR (α=0.95, 1 año) que mide las carteras. Eso garantiza por
construcción que una cartera dentro del budget de su perfil (σ ≤ max_volatility,
μ ≥ 0) nunca banda por encima de ese perfil — la escala y los budgets no pueden
divergir porque salen del mismo archivo. Los anclajes de γ vienen de rangos
típicos de aversión relativa al riesgo (CRRA) en la literatura. Supuestos DEMO:
no reemplazan un proceso de CMA ni la decisión de un comité de inversiones.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from risk_first_advisory.ai_layer.risk_scoring import (
    PROFILES,
    _profile_from_score,
    score_stated_profile,
)
from risk_first_advisory.config_layer.risk_assumptions import (
    get_default_gamma_anchors,
    get_default_risk_profile_params,
)

# ---------------------------------------------------------------------------
# Escala y bandas
# ---------------------------------------------------------------------------

SCALE_MIN: float = 0.0
SCALE_MAX: float = 100.0

# Nivel de confianza al que está CALIBRADA la escala (los anchors se computan
# con este α a horizonte 1 año). portfolio_downside acepta otros α/horizontes,
# pero el mapeo a 0-100 conserva el significado de la calibración por defecto.
DEFAULT_ALPHA: float = 0.95

_STD_NORMAL = NormalDist()


def _norm_pdf(z: float) -> float:
    return _STD_NORMAL.pdf(z)


def _norm_ppf(p: float) -> float:
    """Cuantil normal estándar (stdlib statistics.NormalDist)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p debe estar en (0,1). Recibido: {p}.")
    return _STD_NORMAL.inv_cdf(p)


def _cvar_loss_multiplier(alpha: float) -> float:
    """k tal que la pérdida CVaR_α de una N(0, σ) es k·σ (≈2.063 para α=0.95)."""
    z = _norm_ppf(alpha)
    return _norm_pdf(z) / (1.0 - alpha)


def _downside_anchors_from_config() -> tuple[tuple[float, float], ...]:
    """
    Anclajes downside → número, DERIVADOS de config/risk_profiles.yaml (DD-012).

    El tope de la banda de cada perfil es la pérdida CVaR(α=0.95, 1 año) de una
    cartera al max_volatility de ese perfil con μ=0: pérdida = k·max_volatility.
    Así, una cartera que respeta el budget de su perfil (σ ≤ max_volatility,
    μ ≥ 0) mapea por construcción dentro de la banda de ese perfil, y editar el
    YAML recalibra escala y budgets JUNTOS (no pueden divergir en silencio).
    Pérdida como fracción POSITIVA. Lectura cacheada, una vez al importar.
    """
    params = get_default_risk_profile_params()
    k = _cvar_loss_multiplier(DEFAULT_ALPHA)
    anchors: list[tuple[float, float]] = [(0.0, 0.0)]
    for i, profile in enumerate(PROFILES):
        max_vol = float(params[profile]["max_volatility"])
        anchors.append((k * max_vol, (i + 1) * 20.0))
    return tuple(anchors)


DOWNSIDE_ANCHORS: tuple[tuple[float, float], ...] = _downside_anchors_from_config()

# Anclajes γ (CRRA) → número, DERIVADOS de config/gamma_anchors.yaml (mismo
# patrón que DOWNSIDE_ANCHORS y que los demás supuestos de config_layer:
# lectura cacheada, una vez al importar). γ alto = más averso al riesgo =
# número más bajo. Rangos típicos de la literatura: γ≈1 (log) inversor
# moderado-tolerante, γ 2–4 moderado, γ>8 muy averso, γ≤0 neutral/buscador
# de riesgo. Editar el YAML recalibra el mapeo sin tocar Python.
GAMMA_ANCHORS: tuple[tuple[float, float], ...] = get_default_gamma_anchors()

_GAMMA_MIN: float = -4.0
_GAMMA_MAX: float = 20.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def _piecewise_linear(x: float, anchors: tuple[tuple[float, float], ...]) -> float:
    """Interpola linealmente sobre anchors ESTRICTAMENTE crecientes en x;
    clampa en los bordes."""
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:], strict=False):
        if x0 <= x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    raise ValueError(f"anchors deben estar ordenados crecientes en x: {anchors!r}")


def number_to_band(number: float) -> str:
    """
    Mapea un número 0–100 a uno de los 5 perfiles. Delegado en
    risk_scoring._profile_from_score para que exista UNA sola definición de
    las bandas en todo el motor (cliente y cartera bandan igual por diseño).
    """
    return _profile_from_score(_clamp(number, SCALE_MIN, SCALE_MAX))


# ---------------------------------------------------------------------------
# Lado CARTERA — CVaR a horizonte configurable → número
# ---------------------------------------------------------------------------


def portfolio_downside(
    mu_annual: float | None = None,
    sigma_annual: float | None = None,
    returns: list[float] | None = None,
    horizon_years: float = 1.0,
    alpha: float = DEFAULT_ALPHA,
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

    # `is not None` (no truthiness): una lista vacía ES un error explícito de
    # muestra, no un fallback silencioso al método paramétrico.
    if returns is not None:
        rets = sorted(float(r) for r in returns)
        if not rets:
            raise ValueError(
                "`returns` fue provisto pero está vacío: no hay muestra para "
                "el CVaR empírico."
            )
        if not all(math.isfinite(r) for r in rets):
            raise ValueError(
                "`returns` contiene valores no finitos (NaN/inf): datos de "
                "mercado corruptos — no se computa el downside."
            )
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
    # isfinite ANTES del chequeo de signo: NaN < 0 es False y se colaría.
    if not (math.isfinite(mu_annual) and math.isfinite(sigma_annual)):
        raise ValueError(
            f"mu_annual/sigma_annual deben ser finitos (no NaN/inf): datos de "
            f"mercado corruptos. Recibido: mu={mu_annual}, sigma={sigma_annual}."
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


def risk_scoring_downside(
    sigma_annual: float | None = None,
    returns: list[float] | None = None,
    horizon_years: float = 1.0,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    """
    Downside de SCORING (μ=0): la pérdida de cola SIN restar el retorno esperado.

    Distinto de `portfolio_downside` (que sí incluye el drift μ como Expected
    Shortfall honesto): para el NÚMERO de riesgo 0-100 medimos dispersión pura,
    porque (a) los anclajes DOWNSIDE_ANCHORS se derivan a μ=0 (DD-012) — usar el
    μ real acá haría que el número y la escala no calcen — y (b) un puntaje de
    riesgo no debe "descontar" un retorno esperado optimista: un retorno trailing
    inflado NO reduce el riesgo real de la cartera el año que viene. Así el número
    es monótono en la volatilidad (más vol ⇒ número más alto), como debe ser.

    - paramétrico: pérdida = k(α)·σ·√h, con k(α)=φ(z_α)/(1−α) (≈2.063 a α=0.95).
    - empírico: se CENTRAN los retornos (r − media) antes de tomar la cola, para
      medir dispersión y no drift.

    Returns dict: loss (fracción positiva), method ('normal'|'empirical'),
    horizon_years, alpha, sample_size.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha debe estar en (0,1). Recibido: {alpha}.")
    if horizon_years <= 0:
        raise ValueError(f"horizon_years debe ser > 0. Recibido: {horizon_years}.")

    if returns is not None:
        rets = [float(r) for r in returns]
        if not rets:
            raise ValueError(
                "`returns` fue provisto pero está vacío: no hay muestra."
            )
        if not all(math.isfinite(r) for r in rets):
            raise ValueError(
                "`returns` contiene valores no finitos (NaN/inf): datos corruptos."
            )
        mean = sum(rets) / len(rets)
        centered = sorted(r - mean for r in rets)  # dispersión, sin drift
        tail_n = max(1, math.floor(len(centered) * (1.0 - alpha) + 1e-9))
        tail_mean = sum(centered[:tail_n]) / tail_n
        return {
            "loss": max(0.0, -tail_mean),
            "method": "empirical",
            "horizon_years": horizon_years,
            "alpha": alpha,
            "sample_size": len(rets),
        }

    if sigma_annual is None:
        raise ValueError("Se requiere `returns` o `sigma_annual`.")
    if not math.isfinite(sigma_annual):
        raise ValueError(
            f"sigma_annual debe ser finito (no NaN/inf). Recibido: {sigma_annual}."
        )
    if sigma_annual < 0:
        raise ValueError(f"sigma_annual debe ser >= 0. Recibido: {sigma_annual}.")

    sigma_h = float(sigma_annual) * math.sqrt(horizon_years)
    loss = _cvar_loss_multiplier(alpha) * sigma_h
    return {
        "loss": max(0.0, loss),
        "method": "normal",
        "horizon_years": horizon_years,
        "alpha": alpha,
        "sample_size": 0,
    }


def portfolio_risk_number(
    mu_annual: float | None = None,
    sigma_annual: float | None = None,
    returns: list[float] | None = None,
    horizon_years: float = 1.0,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    """
    Número de riesgo 0–100 de una cartera, desde su downside de SCORING (μ=0,
    dispersión pura — ver `risk_scoring_downside`). `mu_annual` se acepta por
    compatibilidad de firma pero NO entra al número (un retorno esperado alto no
    baja el riesgo del puntaje); el retorno esperado se muestra por separado.

    Returns dict: number, band (perfil equivalente), downside_loss, method,
    horizon_years, alpha, explanation (es).
    """
    d = risk_scoring_downside(
        sigma_annual=sigma_annual, returns=returns,
        horizon_years=horizon_years, alpha=alpha,
    )
    number = downside_to_number(d["loss"])
    band = number_to_band(number)
    pct = d["loss"] * 100.0
    horizon_label = (
        f"{horizon_years:g} año" if horizon_years == 1.0 else f"{horizon_years:g} años"
    )
    # :g y no round(): con α=0.996 la cola es 0.4%, no "0%".
    tail_pct = f"{(1 - alpha) * 100:g}"
    explanation = (
        f"En un año malo (el peor {tail_pct}% de los escenarios a {horizon_label}), "
        f"una cartera con esta volatilidad podría caer alrededor de {pct:.1f}%. "
        f"En la escala del sistema eso es un número de riesgo {number:.0f}/100 "
        f"(banda «{band}»)."
    )
    return {
        "number": number,
        "band": band,
        "downside_loss": round(d["loss"], 4),
        "method": d["method"],
        "horizon_years": horizon_years,
        "alpha": alpha,
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Lado CARTERA — de una cartera candidata REAL (pesos + datos de mercado)
# ---------------------------------------------------------------------------
#
# Slice 2 (docs/RISK_NUMBER_DESIGN.md §5): cierra el gap de
# `InstrumentMarketDataAdapter`, que solo produce retorno/volatilidad reales
# para renta fija (el proxy CSV no cubre ETF/STOCK/CEDEAR). El camino real
# para equities ya existe — `LiveMarketDataProvider` (yfinance/data912,
# opt-in vía RFA_LIVE_DATA) computa expected_return_annual/volatility_annual
# reales para cualquier MarketDataSnapshot, y `CovarianceEngine` arma la
# matriz de covarianza sobre esos snapshots. Lo que faltaba era combinar los
# PESOS de una cartera candidata (OptimizedPortfolio.weights) con esos datos
# para obtener los momentos DE LA CARTERA (no de cada activo por separado).
# Estas funciones no importan tipos de data_layer/portfolio_layer a propósito
# (mantener ai_layer/risk_number.py sin acoplar capas); el caller (Slice 3,
# wiring) adapta CovarianceMatrix.tickers/.covariance y
# {ReturnEstimate.ticker: .adjusted_expected_return_annual} a listas planas.


def portfolio_moments_from_weights(
    weights: dict[str, float],
    expected_returns: dict[str, float],
    tickers: list[str],
    covariance: list[list[float]],
) -> dict[str, Any]:
    """
    Momentos DE LA CARTERA (mu_annual, sigma_annual) a partir de pesos +
    retornos esperados por ticker + matriz de covarianza anualizada:

        mu_annual    = Σ w_i · μ_i
        sigma_annual = sqrt(w' Σ w)

    Con `expected_returns`/`covariance` provenientes de datos reales (vía
    LiveMarketDataProvider + CovarianceEngine), estos momentos son reales
    para cualquier tipo de instrumento, incluidas equities.

    Solo se usan los tickers con peso > 0 que están presentes tanto en
    `tickers` (índice de la matriz de covarianza) como en `expected_returns`;
    los que falten se listan en `missing_tickers` en vez de fallar en
    silencio — el caller decide si eso es aceptable. NO renormaliza los
    pesos: `invested_weight_used` expone cuánto peso efectivamente entró al
    cálculo, para que quede auditable.

    Función pura. Raises ValueError si las dimensiones no calzan o si
    ningún ticker con peso > 0 tiene datos disponibles.
    """
    if not weights:
        raise ValueError("weights no puede estar vacío.")
    if len(covariance) != len(tickers):
        raise ValueError(
            f"covariance debe tener {len(tickers)} filas (una por ticker), "
            f"tiene {len(covariance)}."
        )
    for i, row in enumerate(covariance):
        if len(row) != len(tickers):
            raise ValueError(
                f"covariance fila {i} debe tener {len(tickers)} columnas, "
                f"tiene {len(row)}."
            )

    index = {t: i for i, t in enumerate(tickers)}
    used: list[str] = []
    missing: list[str] = []
    for ticker, w in weights.items():
        if w <= 0:
            continue
        if ticker in index and ticker in expected_returns:
            used.append(ticker)
        else:
            missing.append(ticker)

    if not used:
        raise ValueError(
            "Ninguno de los tickers con peso > 0 tiene retorno esperado y "
            "covarianza disponibles; no se puede computar la cartera."
        )

    mu = sum(weights[t] * expected_returns[t] for t in used)
    variance = 0.0
    for a in used:
        wa, ia = weights[a], index[a]
        for b in used:
            wb, ib = weights[b], index[b]
            variance += wa * wb * covariance[ia][ib]
    # ANTES del clamp: max(0.0, nan) devuelve 0.0 y un NaN de datos corruptos
    # se disfrazaría de cartera sin riesgo (número 0, «conservador»).
    if not (math.isfinite(mu) and math.isfinite(variance)):
        raise ValueError(
            "Retornos/covarianza con valores no finitos (NaN/inf) en los "
            "tickers con peso: datos de mercado corruptos — no se computa "
            "el número de la cartera."
        )
    sigma = math.sqrt(max(0.0, variance))

    return {
        "mu_annual": round(mu, 6),
        "sigma_annual": round(sigma, 6),
        "used_tickers": used,
        "missing_tickers": missing,
        "invested_weight_used": round(sum(weights[t] for t in used), 4),
    }


def portfolio_risk_number_from_weights(
    weights: dict[str, float],
    expected_returns: dict[str, float],
    tickers: list[str],
    covariance: list[list[float]],
    horizon_years: float = 1.0,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    """
    Conveniencia: pesos + datos de mercado de una cartera candidata real →
    número de riesgo 0–100 (misma forma que `portfolio_risk_number`, más
    `missing_tickers`/`invested_weight_used` de `portfolio_moments_from_weights`
    para que el caller pueda mostrar de qué datos salió el número).
    """
    moments = portfolio_moments_from_weights(weights, expected_returns, tickers, covariance)
    result = portfolio_risk_number(
        mu_annual=moments["mu_annual"], sigma_annual=moments["sigma_annual"],
        horizon_years=horizon_years, alpha=alpha,
    )
    result["missing_tickers"] = moments["missing_tickers"]
    result["invested_weight_used"] = moments["invested_weight_used"]
    return result


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
    for name, v in (("wealth", wealth), ("gain", gain), ("loss", loss),
                    ("certain_amount", certain_amount)):
        if not math.isfinite(v):
            raise ValueError(f"{name} debe ser finito (no NaN/inf). Recibido: {v}.")
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

    # CRRA es homotética: escalar (W, G, L, C) por una constante no cambia γ.
    # Normalizamos a riqueza 1 para que x**(1-γ) no sub/desborde el float con
    # riquezas grandes (sin esto, wealth ≳ 1e17 crashea en el borde γ=20).
    gain_n = gain / wealth
    loss_n = loss / wealth
    certain_n = certain_amount / wealth

    # CE(γ) es decreciente en γ: si ni el extremo más buscador de riesgo alcanza
    # el C declarado, clampamos al borde correspondiente.
    if _crra_certainty_equivalent(1.0, gain_n, loss_n, _GAMMA_MIN) <= certain_n:
        return _GAMMA_MIN
    if _crra_certainty_equivalent(1.0, gain_n, loss_n, _GAMMA_MAX) >= certain_n:
        return _GAMMA_MAX

    lo, hi = _GAMMA_MIN, _GAMMA_MAX
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _crra_certainty_equivalent(1.0, gain_n, loss_n, mid) > certain_n:
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


# Divergencia entre elicitaciones que amerita confirmar con el cliente:
# una banda entera (20 puntos) de desacuerdo REAL, medido en puntos — no en
# índices de banda, para que 0.2 puntos cruzando un borde no dispare la señal
# y 19.9 puntos dentro de una banda no pasen en silencio.
DIVERGENCE_THRESHOLD_POINTS: float = 20.0


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

    `tolerance_number` combina ambas (promedio si las dos existen); la
    DIVERGENCIA entre ellas (en puntos) se expone como señal de inconsistencia
    con preguntas de confirmación para el asesor — mismo espíritu que el Risk
    Gap: NO es una medición conductual, es una inconsistencia a confirmar.

    `number` (el Risk Number) es el OPERATIVO: la capacidad acota la
    tolerancia — number = min(tolerance_number, capacity_ceiling_number) —
    con la misma regla que el perfil efectivo del motor (score_stated_profile:
    effective = min(willingness, ability)). Así este número y el
    `deterministic.score` que viaja al lado en el análisis no se contradicen.

    Returns dict: number, band, willingness_number, tradeoff_number, gamma,
    tolerance_number, divergence_bands, inconsistent, capacity_ceiling_number,
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
        tolerance_number = round(0.5 * willingness_number + 0.5 * tradeoff_number, 1)
        divergence_points = abs(willingness_number - tradeoff_number)
    else:
        tolerance_number = willingness_number
        divergence_points = 0.0

    divergence_bands = int(divergence_points // 20)
    inconsistent = divergence_points >= DIVERGENCE_THRESHOLD_POINTS

    # La capacidad acota: el número operativo nunca supera el techo.
    number = round(min(tolerance_number, ceiling_number), 1)
    band = number_to_band(number)
    capacity_bound = tolerance_number > ceiling_number

    if inconsistent:
        explanation = (
            f"Las dos elicitaciones divergen: el cuestionario declara "
            f"{willingness_number:.0f}/100 pero la pregunta de trade-off implica "
            f"{tradeoff_number:.0f}/100 ({divergence_points:.0f} puntos de "
            f"diferencia). Número operativo provisorio: {number:.0f}/100 "
            f"(«{band}»). Confirmar con el cliente antes de usarlo — esto es "
            "una inconsistencia, no una medición."
        )
    elif capacity_bound:
        explanation = (
            f"El cliente tolera {tolerance_number:.0f}/100, pero su capacidad "
            f"financiera soporta hasta {ceiling_number:.0f}/100: su número de "
            f"riesgo operativo es {number:.0f}/100 («{band}»). La capacidad "
            "acota la tolerancia — la diferencia es tema de conversación con "
            "el asesor, no un permiso para asumir más riesgo."
        )
    else:
        explanation = (
            f"Número de riesgo del cliente: {number:.0f}/100 («{band}»), "
            f"dentro de su capacidad financiera "
            f"({ceiling_number:.0f}/100, «{number_to_band(ceiling_number)}»)."
        )

    return {
        "number": number,
        "band": band,
        "willingness_number": willingness_number,
        "tradeoff_number": tradeoff_number,
        "gamma": gamma,
        "tolerance_number": tolerance_number,
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
    Todas las comparaciones son POR PUNTOS con la misma holgura (media banda por
    defecto) — no por índices de banda, que en los bordes disparaban con 0.1
    puntos de diferencia y callaban con 19.9.

    status:
      - 'over_capacity'   la cartera supera el techo de capacidad por más de la
                          holgura: el cliente asumiría más riesgo del que su
                          situación financiera soporta — conversación obligada;
      - 'over_tolerance'  dentro de capacidad, pero > número del cliente
                          + holgura → conversación de ajuste;
      - 'aligned'         dentro de ±holgura del número del cliente;
      - 'under_tolerance' más conservadora que el número del cliente − holgura;
                          el margen para subir riesgo se informa ACOTADO por el
                          techo de capacidad, nunca más allá.

    SEÑAL INFORMATIVA, no de enforcement: este módulo informa la conversación
    asesor↔cliente. El override formal lo gobiernan los mecanismos existentes —
    la aprobación de perfil por encima del techo (profile-approval) y
    metadata.requires_advisor_override en la selección de cartera (I-018).
    Aprobar/elegir sigue siendo del asesor vía los endpoints humanos
    (I-001/I-016/I-019). Función pura.

    Returns dict: status, gap_points (cartera − cliente), capacity_gap_points
    (cartera − techo), explanation (es).
    """
    if tolerance_points < 0:
        raise ValueError(f"tolerance_points debe ser >= 0. Recibido: {tolerance_points}.")

    gap_points = round(portfolio_number - client_number, 1)
    capacity_gap_points = round(portfolio_number - capacity_ceiling_number, 1)

    if capacity_gap_points > tolerance_points:
        status = "over_capacity"
        explanation = (
            f"La cartera ({portfolio_number:.0f}/100) queda {capacity_gap_points:.0f} "
            f"puntos por encima del techo de capacidad del cliente "
            f"({capacity_ceiling_number:.0f}/100): asumiría más riesgo del que su "
            "situación financiera soporta. Revisarlo con el cliente antes de "
            "considerarla; si además excede el presupuesto de riesgo aprobado, "
            "la selección exige el override formal del asesor."
        )
    elif gap_points > tolerance_points:
        status = "over_tolerance"
        explanation = (
            f"La cartera ({portfolio_number:.0f}/100) supera el número del cliente "
            f"({client_number:.0f}/100) en {gap_points:.0f} puntos, aunque está dentro "
            "de su capacidad. Conviene bajar el riesgo de la cartera o confirmar con el "
            "cliente que acepta la diferencia."
        )
    elif gap_points < -tolerance_points:
        status = "under_tolerance"
        # El margen real para subir riesgo termina en el techo de capacidad,
        # no en la tolerancia declarada.
        headroom = round(
            min(client_number, capacity_ceiling_number) - portfolio_number, 1
        )
        if headroom > tolerance_points:
            explanation = (
                f"La cartera ({portfolio_number:.0f}/100) es más conservadora que el "
                f"número del cliente ({client_number:.0f}/100). Hay margen de "
                f"{headroom:.0f} puntos para tomar más riesgo sin exceder su capacidad "
                f"({capacity_ceiling_number:.0f}/100) — o es una elección deliberada "
                "de prudencia."
            )
        else:
            explanation = (
                f"La cartera ({portfolio_number:.0f}/100) es más conservadora que el "
                f"número del cliente ({client_number:.0f}/100), pero el techo de "
                f"capacidad ({capacity_ceiling_number:.0f}/100) deja poco margen "
                "adicional: subir el riesgo no es una opción real para este cliente."
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
        "gap_points": gap_points,
        "capacity_gap_points": capacity_gap_points,
        "explanation": explanation,
    }


def assess_risk_alignment(
    payload: dict[str, Any],
    *,
    mu_annual: float | None = None,
    sigma_annual: float | None = None,
    returns: list[float] | None = None,
    horizon_years: float = 1.0,
    alpha: float = DEFAULT_ALPHA,
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
