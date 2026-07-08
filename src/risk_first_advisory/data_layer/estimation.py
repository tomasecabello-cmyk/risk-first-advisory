"""
estimation — μ y Σ conjuntos sobre series REALES: Ledoit-Wolf + Black-Litterman.

Portado del proyecto hermano `markowitz-optimizer` (engine/black_litterman.py y
data/market_data._estimate_cov), adaptado al contrato de este proyecto
(CovarianceMatrix, fetch_series_cached, normalización ARS→USD CCL).

QUÉ ARREGLA (vs. la estimación naive del path live anterior):
    - Σ: antes cada ticker traía su vol real pero las CORRELACIONES eran una
      tabla mock por asset_class (CovarianceEngine). Acá Σ se estima sobre la
      matriz de retornos diarios ALINEADA (inner join de fechas) con shrinkage
      de Ledoit-Wolf (2004): regulariza la covarianza muestral hacia una
      identidad escalada, lo que la hace bien condicionada y estabiliza al
      optimizador con ventanas cortas (típico ARG).
    - μ: antes era media histórica × 252 (garbage-in clásico: post-rally ARG
      daba 30-40% en soberanos y MAX_RETURN los perseguía). Acá μ es el
      posterior de Black-Litterman (1992): prior de equilibrio Π = δ Σ w_ref
      (w_ref = equal-weight) mezclado bayesianamente con la media histórica
      como view (P=I, Ω = diag(τΣ)/confianza, convención He & Litterman 2002).
      Para renta fija la view puede ser el YTM (parámetro `views`): un ancla
      forward-looking mucho mejor que la media histórica post-rally.
      Es shrinkage de la media histórica hacia un ancla con estructura
      económica — mismo espíritu que Ledoit-Wolf pero para μ.
    - Saltos de ratio: los rebasings multiplicativos de CEDEARs (cambio de
      ratio sin re-ajustar el histórico) se corrigen por back-scaling sobre la
      serie ya en USD (providers.adjust_ratio_jumps), con nota auditada por
      salto. Series con demasiados saltos se descartan.
    - Sanity bound: series con volatilidad anualizada absurda (> MAX_SANE_VOL)
      que sobreviven a lo anterior se DESCARTAN con razón auditada en vez de
      envenenar Σ y romper el solver.

Ledoit-Wolf se implementa en numpy puro (fórmula cerrada del paper, la misma
que sklearn.covariance.LedoitWolf) para no sumar scikit-learn como dependencia.

Referencias: Ledoit & Wolf (2004) "A well-conditioned estimator for
large-dimensional covariance matrices"; Black & Litterman (1992);
He & Litterman (2002); Idzorek (2007).
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from risk_first_advisory.data_layer.covariance import CovarianceMatrix
from risk_first_advisory.data_layer.providers import (
    PriceSeries,
    ProviderError,
    adjust_ratio_jumps,
    fetch_series_cached,
    usd_ars_history,
)

_TRADING_DAYS: int = 252

# Volatilidad anualizada máxima "sana". Por encima de esto la serie se asume
# corrupta (cambios de ratio de CEDEARs, splits sin ajustar, precios basura)
# y se descarta con razón auditada. 300% anual ya es el triple de una acción
# ARG volátil; ningún instrumento listado legítimo lo supera sostenidamente.
MAX_SANE_VOL: float = 3.0

_MIN_OBS: int = 40          # mismo umbral que LiveMarketDataProvider
_DEFAULT_RF: float = 0.04   # tasa libre de riesgo anual (igual que markowitz-optimizer)

DEFAULT_DELTA: float = 2.5  # aversión al riesgo del inversor representativo
DEFAULT_TAU: float = 0.05   # incertidumbre del prior de equilibrio


class EstimationError(RuntimeError):
    """No se pudieron estimar momentos conjuntos (series insuficientes/corruptas)."""


# ─────────────────────────────────────────────────────────────────────────────
# Ledoit-Wolf (2004) — shrinkage hacia identidad escalada, numpy puro
# ─────────────────────────────────────────────────────────────────────────────


def ledoit_wolf_covariance(daily: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Covarianza DIARIA con shrinkage de Ledoit-Wolf.

    Σ* = λ·m·I + (1−λ)·S, donde S es la covarianza muestral (ML, divisor T),
    m = tr(S)/N el target de identidad escalada, y λ ∈ [0,1] la intensidad
    óptima estimada según el paper (misma fórmula que sklearn LedoitWolf).

    Args:
        daily: matriz T×N de retornos diarios (T observaciones, N activos).

    Returns:
        (sigma_daily, lambda_shrinkage)
    """
    x = np.asarray(daily, dtype=float)
    if x.ndim != 2:
        raise ValueError(f"daily debe ser matriz T×N; shape recibido: {x.shape}.")
    t, n = x.shape
    if t < 2 or n < 1:
        raise ValueError(f"daily necesita T>=2 y N>=1; shape recibido: {x.shape}.")

    x = x - x.mean(axis=0)
    sample = (x.T @ x) / t                      # covarianza ML (divisor T)

    mu = float(np.trace(sample)) / n            # target: m·I
    delta_sq = float(((sample - mu * np.eye(n)) ** 2).sum()) / n

    if delta_sq <= 0.0:
        return sample, 0.0

    # β̄² = (1/T²) Σ_t ||x_t x_tᵀ − S||²_F / N   (dispersión muestral de S)
    beta_sq = 0.0
    for row in x:
        outer = np.outer(row, row)
        beta_sq += float(((outer - sample) ** 2).sum())
    beta_sq /= (t ** 2) * n
    beta_sq = min(beta_sq, delta_sq)

    lam = beta_sq / delta_sq
    shrunk = lam * mu * np.eye(n) + (1.0 - lam) * sample
    return shrunk, float(lam)


# ─────────────────────────────────────────────────────────────────────────────
# Black-Litterman — portado verbatim de markowitz-optimizer/engine/black_litterman.py
# ─────────────────────────────────────────────────────────────────────────────


def implied_equilibrium_returns(
    sigma: np.ndarray, w_ref: np.ndarray, delta: float = DEFAULT_DELTA
) -> np.ndarray:
    """Π = δ Σ w_ref — retornos de equilibrio implícitos (en exceso sobre r_f)."""
    return delta * (sigma @ w_ref)


def black_litterman_returns(
    sigma: np.ndarray,
    mu_hist: np.ndarray,
    rf: float = 0.0,
    w_ref: np.ndarray | None = None,
    delta: float = DEFAULT_DELTA,
    tau: float = DEFAULT_TAU,
    view_confidence: float = 1.0,
) -> np.ndarray:
    """
    Retorno esperado posterior de Black-Litterman (en niveles, incluye r_f).

    Prior de equilibrio Π = δ Σ w_ref (w_ref = equal-weight por defecto: no
    afirmamos conocer el "portafolio de mercado" de una canasta mixta ARG/US).
    Views: la media histórica por activo (P = I, Q = μ_hist − r_f) con
    incertidumbre Ω = diag(τΣ)/confianza (He & Litterman, 2002). Más
    view_confidence acerca μ a la media histórica; menos, al equilibrio.
    """
    sigma = np.asarray(sigma, dtype=float)
    mu_hist = np.asarray(mu_hist, dtype=float)
    n = sigma.shape[0]
    if w_ref is None:
        w_ref = np.full(n, 1.0 / n)
    w_ref = np.asarray(w_ref, dtype=float)

    pi = implied_equilibrium_returns(sigma, w_ref, delta)   # prior (exceso)
    tau_sigma = tau * sigma
    p = np.eye(n)
    q = mu_hist - rf                                         # views como exceso

    omega = np.diag(np.diag(p @ tau_sigma @ p.T)) / max(view_confidence, 1e-9)
    omega += np.eye(n) * 1e-12

    inv_tau_sigma = np.linalg.inv(tau_sigma)
    inv_omega = np.linalg.inv(omega)
    posterior_cov = np.linalg.inv(inv_tau_sigma + p.T @ inv_omega @ p)
    posterior_excess = posterior_cov @ (inv_tau_sigma @ pi + p.T @ inv_omega @ q)
    return posterior_excess + rf


# ─────────────────────────────────────────────────────────────────────────────
# Estimador conjunto: series reales → μ (BL) + Σ (LW) alineados
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class JointMomentResult:
    """
    Momentos conjuntos estimados sobre series reales alineadas.

    tickers preserva el ORDEN de estimación: covariance.tickers == tickers y
    mu/vol están indexados por esos mismos tickers. dropped registra cada
    instrumento descartado con su razón (auditables como warnings del proposal).
    """

    tickers: list[str]
    mu: dict[str, float]                # μ Black-Litterman anual, clip [-1, 1]
    mu_hist: dict[str, float]           # media histórica anual (trazabilidad)
    vol: dict[str, float]               # σ anual (diagonal de Σ Ledoit-Wolf)
    covariance: CovarianceMatrix        # Σ anual LW (correlaciones reales)
    shrinkage: float                    # λ de Ledoit-Wolf ∈ [0, 1]
    meta: dict[str, dict[str, Any]]     # ticker → {source, ccy_native, kind, obs}
    dropped: list[dict[str, str]]       # [{ticker, reason}]
    adjusted: list[dict[str, str]] = field(default_factory=list)  # [{ticker, note}] saltos de ratio
    notes: list[str] = field(default_factory=list)


def estimate_joint_moments(
    source_map: dict[str, str],
    period: str = "3y",
    rf: float = _DEFAULT_RF,
    min_obs: int = _MIN_OBS,
    max_sane_vol: float = MAX_SANE_VOL,
    views: dict[str, float] | None = None,
    max_workers: int = 16,
    _fetch: Callable[[str, str, str], PriceSeries] | None = None,
    _fx: Callable[[str, str], pd.Series] | None = None,
) -> JointMomentResult:
    """
    Estima μ (Black-Litterman) y Σ (Ledoit-Wolf) sobre las series reales de los
    tickers de `source_map`, alineadas por fechas comunes y normalizadas a USD
    (CCL) cuando cotizan en ARS.

    `views` permite reemplazar la view de BL por ticker (retorno anual esperado
    en decimal, p.ej. el YTM de un bono) en vez de la media histórica. P sigue
    siendo la identidad; solo cambia Q para esos tickers. Los que no aparecen
    en `views` conservan la media histórica como view. Queda trazado en
    `meta[ticker]["view"]` ("explicit" | "hist_mean").

    Corrige saltos de ratio (rebasings de CEDEARs) por back-scaling sobre la
    serie ya en USD, con nota auditada por salto en `adjusted`. Descarta, con
    razón auditada: series que no se pueden traer, con menos de `min_obs`
    observaciones, ARS sin FX disponible, series con demasiados saltos de
    ratio, y series con volatilidad anualizada > `max_sane_vol` (corrupción
    de datos).

    Raises:
        EstimationError: si quedan < 2 series utilizables o el solapamiento de
        fechas es insuficiente.
    """
    fetch = _fetch or fetch_series_cached
    fx_provider = _fx or usd_ars_history

    sources = {t.strip().upper(): s for t, s in source_map.items()}
    tickers = list(sources)
    dropped: list[dict[str, str]] = []
    notes: list[str] = []

    # ── 1. Fetch en paralelo (I/O puro; cache en disco por ticker) ──────────
    def _try_fetch(sym: str) -> PriceSeries | Exception:
        try:
            return fetch(sym, sources.get(sym, "us"), period)
        except Exception as exc:  # noqa: BLE001 — cada falla se registra por ticker
            return exc

    workers = max(1, min(max_workers, len(tickers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = list(pool.map(_try_fetch, tickers))

    series: list[PriceSeries] = []
    for sym, res in zip(tickers, fetched, strict=True):
        if isinstance(res, Exception):
            kind = "provider_error" if isinstance(res, ProviderError) else "fetch_error"
            dropped.append({"ticker": sym, "reason": f"{kind}: {res}"})
            continue
        if res is None or res.close is None or len(res.close) < min_obs:
            n_obs = 0 if res is None or res.close is None else len(res.close)
            dropped.append({"ticker": sym, "reason": f"short_history: {n_obs} obs < {min_obs}"})
            continue
        series.append(res)

    # ── 2. Normalización ARS→USD (una sola serie FX para todos) ─────────────
    fx: pd.Series | None = None
    if any(ps.currency == "ARS" for ps in series):
        try:
            fx = fx_provider("ccl", period)
        except Exception as exc:  # noqa: BLE001 — sin FX no se mezclan monedas
            fx = None
            notes.append(f"fx_unavailable: {exc}")

    native_ccy = {ps.symbol: ps.currency for ps in series}
    usable: list[PriceSeries] = []
    for ps in series:
        if ps.currency != "ARS":
            usable.append(ps)
            continue
        if fx is None:
            dropped.append({"ticker": ps.symbol, "reason": "ars_without_fx"})
            continue
        aligned = fx.reindex(ps.close.index.union(fx.index)).sort_index().ffill()
        aligned = aligned.reindex(ps.close.index)
        usd_close = (ps.close / aligned).dropna()
        if len(usd_close) < min_obs:
            dropped.append({"ticker": ps.symbol,
                            "reason": f"short_history_post_fx: {len(usd_close)} obs"})
            continue
        usable.append(PriceSeries(symbol=ps.symbol, source=ps.source,
                                  currency="USD", kind=ps.kind, close=usd_close))

    # ── 2b. Saltos de ratio (rebasings de CEDEARs) — sobre la serie ya en USD ─
    adjusted: list[dict[str, str]] = []
    cleaned: list[PriceSeries] = []
    for ps in usable:
        adj = adjust_ratio_jumps(ps.close)
        if adj.suspect:
            dropped.append({"ticker": ps.symbol, "reason": adj.notes[0]})
            continue
        if adj.n_jumps:
            adjusted.extend({"ticker": ps.symbol, "note": n} for n in adj.notes)
            ps = PriceSeries(symbol=ps.symbol, source=ps.source,
                             currency=ps.currency, kind=ps.kind, close=adj.close)
        cleaned.append(ps)
    usable = cleaned

    if len(usable) < 2:
        raise EstimationError(
            f"Series utilizables insuficientes para estimación conjunta: "
            f"{len(usable)} (se requieren >= 2). Descartes: "
            + "; ".join(f"{d['ticker']}={d['reason']}" for d in dropped)
        )

    # ── 3. Alinear por fechas comunes y derivar retornos diarios ────────────
    frame = pd.concat({ps.symbol: ps.close for ps in usable}, axis=1)
    frame = frame.sort_index().ffill().dropna()
    if len(frame) < min_obs:
        raise EstimationError(
            f"Solapamiento de fechas insuficiente: {len(frame)} filas comunes "
            f"< {min_obs}. Probar un período más largo."
        )
    daily = frame.pct_change().dropna()
    if len(daily) < min_obs:
        raise EstimationError(
            f"Retornos diarios insuficientes tras alinear: {len(daily)} < {min_obs}."
        )

    # ── 4. Sanity bound de volatilidad (descarta series corruptas) ──────────
    sample_vol = daily.std() * float(np.sqrt(_TRADING_DAYS))
    absurd = [c for c in daily.columns if float(sample_vol[c]) > max_sane_vol]
    for c in absurd:
        dropped.append({
            "ticker": str(c),
            "reason": f"volatility_absurd: {float(sample_vol[c]):.0%} anual "
                      f"> {max_sane_vol:.0%} (serie corrupta)",
        })
    if absurd:
        daily = daily.drop(columns=absurd)
    if daily.shape[1] < 2:
        raise EstimationError(
            "Menos de 2 series sanas tras el sanity bound de volatilidad. "
            + "; ".join(f"{d['ticker']}={d['reason']}" for d in dropped)
        )

    ordered = [str(c) for c in daily.columns]

    # ── 5. Σ Ledoit-Wolf + μ Black-Litterman (anuales) ──────────────────────
    sigma_daily, lam = ledoit_wolf_covariance(daily.to_numpy())
    sigma_annual = sigma_daily * _TRADING_DAYS
    mu_hist_arr = daily.mean().to_numpy() * _TRADING_DAYS

    # Views de BL: media histórica por defecto; explícita (p.ej. YTM) si viene.
    view_map = {t.strip().upper(): float(v) for t, v in (views or {}).items()
                if v is not None}
    q_arr = mu_hist_arr.copy()
    explicit_view: set[str] = set()
    for i, t in enumerate(ordered):
        if t in view_map:
            q_arr[i] = view_map[t]
            explicit_view.add(t)

    mu_bl_arr = black_litterman_returns(sigma_annual, q_arr, rf=rf)
    mu_bl_arr = np.clip(mu_bl_arr, -1.0, 1.0)

    d = np.sqrt(np.clip(np.diag(sigma_annual), 0.0, None))
    denom = np.outer(d, d)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(denom > 0.0, sigma_annual / denom, 0.0)
    np.fill_diagonal(corr, 1.0)

    window_note = (
        f"window={frame.index[0].date()}..{frame.index[-1].date()} "
        f"({len(daily)} retornos diarios comunes)"
    )
    method_notes = [
        f"sigma=ledoit_wolf(lambda={lam:.3f})",
        f"mu=black_litterman(delta={DEFAULT_DELTA}, tau={DEFAULT_TAU}, rf={rf})",
        window_note,
    ]
    if explicit_view:
        method_notes.append(
            f"views=explicit para {len(explicit_view)} tickers (resto: media histórica)"
        )

    covariance = CovarianceMatrix(
        tickers=ordered,
        covariance=[[float(v) for v in row] for row in sigma_annual],
        correlation=[[float(v) for v in row] for row in corr],
        annualized=True,
        notes=method_notes,
    )

    by_symbol = {ps.symbol: ps for ps in usable}
    meta = {
        t: {
            "source": by_symbol[t].source,
            "ccy_native": native_ccy.get(t, by_symbol[t].currency),
            "kind": by_symbol[t].kind,
            "obs": int(len(daily)),
            "view": "explicit" if t in explicit_view else "hist_mean",
        }
        for t in ordered
    }

    return JointMomentResult(
        tickers=ordered,
        mu={t: float(mu_bl_arr[i]) for i, t in enumerate(ordered)},
        mu_hist={t: float(mu_hist_arr[i]) for i, t in enumerate(ordered)},
        vol={t: float(d[i]) for i, t in enumerate(ordered)},
        covariance=covariance,
        shrinkage=lam,
        meta=meta,
        dropped=dropped,
        adjusted=adjusted,
        notes=notes + method_notes,
    )
