"""
providers — fuentes de datos de mercado en vivo (híbrido ARG + US), todo gratis.

Portado desde el proyecto hermano `markowitz-optimizer` (mismo universo y fuentes).
A futuro, un proveedor BYO (p. ej. terminales Bloomberg de la facultad) puede
implementar la misma interfaz `fetch_series(symbol, source, period) -> PriceSeries`.

Fuentes (sin API key, salvo PPI opcional):
  - US (AAPL, SPY, ETFs)                  → yfinance
  - Acciones / CEDEARs ARG               → data912 (fallback yfinance .BA)
  - Bonos soberanos ARG (AL30, GD30)     → data912
  - Obligaciones Negociables (ONs)       → Rava Bursátil (PPI fallback con creds)
  - Tipo de cambio ARS→USD (CCL/MEP)     → argentinadatos

Las series salen en moneda nativa; la normalización a USD (para μ/Σ) la hace la
capa superior con `usd_ars_history`. NO usar en producción sin revisar rate limits,
calidad/frescura y ausencia de SLA. Demo educativo.
"""

from __future__ import annotations

import datetime as _dt
import os
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import requests
import urllib3
import yfinance as yf

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA912_BASE = "https://data912.com"
PPI_BASE = "https://clientapi.portfoliopersonal.com"
ARGENTINADATOS_BASE = "https://api.argentinadatos.com/v1/cotizaciones/dolares"
RAVA_BASE = "https://www.rava.com"
_HTTP_TIMEOUT = 25
_HEADERS = {"User-Agent": "risk-first-advisory/0.1"}

# source -> (proveedor, categoría/handler)
SOURCES: dict[str, dict] = {
    "us":        {"label": "US (yfinance)", "currency": "USD", "kind": "equity"},
    "arg_stock": {"label": "Acción ARG", "currency": "ARS", "kind": "equity",
                  "d912": "stocks", "d912_live": "arg_stocks", "yf_suffix": ".BA"},
    "arg_cedear": {"label": "CEDEAR ARG", "currency": "ARS", "kind": "equity",
                   "d912": "cedears", "d912_live": "arg_cedears", "yf_suffix": ".BA"},
    "arg_bond":  {"label": "Bono soberano ARG", "currency": "ARS", "kind": "bond",
                  "d912": "bonds", "d912_live": "arg_bonds"},
    "arg_corp":  {"label": "Bono corporativo ARG (ON)", "currency": "ARS", "kind": "bond",
                  "d912": "corp", "d912_live": "arg_corp"},
}

_PERIOD_DAYS = {"1y": 365, "3y": 1095, "5y": 1825, "max": None}


@dataclass
class PriceSeries:
    symbol: str
    source: str
    currency: str
    kind: str            # equity | bond
    close: pd.Series     # cierres diarios indexados por fecha (DatetimeIndex)


class ProviderError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Saltos de ratio (rebasings multiplicativos) — típico de CEDEARs cuando cambia
# el ratio CEDEAR:acción y el proveedor no re-ajusta el histórico. El sanity
# bound de vol (estimation.MAX_SANE_VOL) ataja las series destruidas; esto
# corrige las que tienen UN salto dentro del umbral que infla σ sin volverla
# absurda (p.ej. IBM/NFLX ~140% anual por un único día de -80%).
#
# IMPORTANTE: aplicar sobre la serie YA normalizada a USD. En ARS un día de
# devaluación fuerte es un movimiento real que la conversión CCL cancela;
# ajustarlo antes del FX crearía un salto inverso en la serie USD.
# ---------------------------------------------------------------------------

RATIO_JUMP_THRESHOLD: float = 0.40    # |retorno diario| mínimo para ser salto
RATIO_JUMP_MAD_MULTIPLE: float = 8.0  # outlier vs escala robusta de la serie
# Más saltos que esto = serie sospechosa, no se ajusta. Calibrado con data912
# 3y (2026-07): NFLX real acumula 4 glitches/rebasings legítimos; una serie
# con más de 5 días absurdos aislados ya no es creíble como rebasing.
RATIO_JUMP_MAX: int = 5


@dataclass
class RatioJumpAdjustment:
    """Resultado de adjust_ratio_jumps: serie (ajustada o no) + auditoría."""

    close: pd.Series
    notes: list[str] = field(default_factory=list)  # una nota auditable por salto
    n_jumps: int = 0
    suspect: bool = False   # demasiados saltos: no se ajusta, el caller descarta


def adjust_ratio_jumps(
    close: pd.Series,
    jump_threshold: float = RATIO_JUMP_THRESHOLD,
    mad_multiple: float = RATIO_JUMP_MAD_MULTIPLE,
    max_jumps: int = RATIO_JUMP_MAX,
) -> RatioJumpAdjustment:
    """
    Detecta y corrige saltos de ratio en una serie de cierres.

    Un salto es un retorno diario absurdo y AISLADO: |r| > jump_threshold, que
    además es outlier extremo respecto de la escala robusta (MAD) de la propia
    serie, y cuyos vecinos inmediatos son días normales. Un crash genuino con
    rebote tiene días grandes contiguos y NO se toca; una serie genuinamente
    salvaje tiene MAD alto y tampoco.

    Corrección: back-scaling — todo el segmento previo al salto se reescala
    por el factor implícito (p_t / p_{t-1}), el ajuste estándar de rebasing.
    El retorno de ese día queda en 0 (el retorno real del día se pierde: es la
    aproximación estándar y queda anotado); el resto de la serie no cambia.

    Con más de max_jumps saltos la serie se considera sospechosa y NO se
    ajusta (suspect=True): el caller decide descartarla con razón auditada.
    """
    s = close.dropna()
    s = s[s > 0]
    if len(s) < 3:
        return RatioJumpAdjustment(close=s)

    rets = s.to_numpy(dtype=float)[1:] / s.to_numpy(dtype=float)[:-1] - 1.0
    abs_rets = np.abs(rets)
    med = float(np.median(rets))
    sigma_rob = 1.4826 * float(np.median(np.abs(rets - med)))

    jumps: list[int] = []   # i = salto entre s[i] y s[i+1] (retorno rets[i])
    for i, r in enumerate(rets):
        if abs(r) <= jump_threshold:
            continue
        if sigma_rob > 0.0 and abs(r - med) <= mad_multiple * sigma_rob:
            continue
        prev_ok = i == 0 or abs_rets[i - 1] <= jump_threshold
        next_ok = i == len(rets) - 1 or abs_rets[i + 1] <= jump_threshold
        if prev_ok and next_ok:
            jumps.append(i)

    if not jumps:
        return RatioJumpAdjustment(close=s)
    if len(jumps) > max_jumps:
        return RatioJumpAdjustment(
            close=s,
            notes=[
                f"ratio_jumps_excessive: {len(jumps)} saltos aislados con "
                f"|r| > {jump_threshold:.0%} (> {max_jumps}); serie no "
                "confiable, no se ajusta"
            ],
            n_jumps=len(jumps),
            suspect=True,
        )

    values = s.to_numpy(dtype=float).copy()
    notes: list[str] = []
    for i in jumps:
        factor = values[i + 1] / values[i]
        values[: i + 1] *= factor
        notes.append(
            f"ratio_jump_adjusted: {pd.Timestamp(s.index[i + 1]).date()} "
            f"r={rets[i]:+.1%} factor={factor:.4g} (prefijo reescalado)"
        )
    adjusted = pd.Series(values, index=s.index, name=s.name)
    return RatioJumpAdjustment(
        close=adjusted, notes=notes, n_jumps=len(jumps), suspect=False
    )


def _cutoff(period: str) -> _dt.date | None:
    days = _PERIOD_DAYS.get(period, 1095)
    if days is None:
        return None
    return _dt.date.today() - _dt.timedelta(days=days)


# ---------------------------------------------------------------------------
# data912 (Argentina)
# ---------------------------------------------------------------------------

def data912_history(symbol: str, category: str, period: str) -> pd.Series:
    """Cierres diarios de data912: GET /historical/{category}/{symbol}."""
    url = f"{DATA912_BASE}/historical/{category}/{symbol}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderError(f"data912 no respondió para {symbol}: {exc}") from exc
    if resp.status_code == 404:
        raise ProviderError(f"data912 sin histórico para {category}/{symbol}.")
    if not resp.ok:
        raise ProviderError(f"data912 error {resp.status_code} para {symbol}.")
    try:
        rows = resp.json()
    except ValueError as exc:
        raise ProviderError(f"data912 formato no-JSON para {symbol}: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise ProviderError(f"data912 sin histórico utilizable para {symbol}.")

    pts = {
        pd.Timestamp(r["date"]): float(r["c"])
        for r in rows
        if isinstance(r, dict) and r.get("date") and r.get("c")
    }
    if not pts:
        raise ProviderError(f"data912 sin datos para {symbol}.")

    s = pd.Series(pts, name=symbol).sort_index()
    cut = _cutoff(period)
    if cut is not None:
        s = s[s.index >= pd.Timestamp(cut)]
    return s[s > 0]


# ---------------------------------------------------------------------------
# Rava Bursátil — histórico de ONs gratis vía /api/chart-history
# ---------------------------------------------------------------------------
_rava_session: requests.Session | None = None
_RAVA_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _rava_get_session() -> requests.Session:
    global _rava_session
    if _rava_session is None:
        s = requests.Session()
        s.headers.update(_RAVA_HEADERS)
        try:
            s.get(RAVA_BASE + "/", timeout=_HTTP_TIMEOUT, verify=False)
        except requests.RequestException:
            pass
        _rava_session = s
    return _rava_session


def rava_history(symbol: str, period: str) -> pd.Series:
    """Histórico de cierres diarios (ARS) de Rava para un símbolo (ej. una ON)."""
    sym = symbol.strip().upper()
    s = _rava_get_session()
    try:
        resp = s.post(
            RAVA_BASE + "/api/chart-history",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Referer": f"{RAVA_BASE}/perfil/{sym}"},
            data={"especie": sym}, timeout=_HTTP_TIMEOUT, verify=False,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"Rava no respondió para {sym}: {exc}") from exc

    rows = payload.get("body") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ProviderError(f"Rava sin histórico para {sym}.")

    pts = {}
    for r in rows:
        fecha, cierre = r.get("fecha"), r.get("cierre")
        if fecha and cierre:
            pts[pd.Timestamp(fecha)] = float(cierre)
    if not pts:
        raise ProviderError(f"Rava: formato inesperado para {sym}.")

    s_close = pd.Series(pts, name=sym).sort_index()
    cut = _cutoff(period)
    if cut is not None:
        s_close = s_close[s_close.index >= pd.Timestamp(cut)]
    return s_close[s_close > 0]


# ---------------------------------------------------------------------------
# yfinance (US + .BA) + tipo de cambio
# ---------------------------------------------------------------------------

FX_KINDS = {
    "ccl": ("contadoconliqui", "Dólar CCL (contado con liquidación)"),
    "mep": ("bolsa", "Dólar MEP (bolsa)"),
    "blue": ("blue", "Dólar blue"),
    "oficial": ("oficial", "Dólar oficial"),
    "mayorista": ("mayorista", "Dólar mayorista"),
}
_fx_cache: dict[str, tuple[float, pd.Series]] = {}


def usd_ars_history(kind: str = "ccl", period: str = "max") -> pd.Series:
    """Serie histórica USD/ARS (ARS por dólar), precio medio. Default CCL. Cachea 1h."""
    casa = FX_KINDS.get(kind, FX_KINDS["ccl"])[0]
    cached = _fx_cache.get(casa)
    if cached and (time.time() - cached[0]) < 3600:
        s = cached[1]
    else:
        url = f"{ARGENTINADATOS_BASE}/{casa}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_HTTP_TIMEOUT)
            resp.raise_for_status()
            rows = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"No se pudo obtener USD/ARS ({casa}): {exc}") from exc
        pts = {}
        for r in rows:
            v, b = r.get("venta"), r.get("compra")
            if r.get("fecha") and (v or b):
                mid = (float(v or b) + float(b or v)) / 2.0
                if mid > 0:
                    pts[pd.Timestamp(r["fecha"])] = mid
        if not pts:
            raise ProviderError(f"USD/ARS ({casa}) sin datos utilizables.")
        s = pd.Series(pts, name=f"USDARS_{kind}").sort_index()
        _fx_cache[casa] = (time.time(), s)

    cut = _cutoff(period)
    if cut is not None:
        s = s[s.index >= pd.Timestamp(cut)]
    return s


def yfinance_history(symbol: str, period: str) -> pd.Series:
    """Cierres diarios ajustados de yfinance para un único símbolo."""
    try:
        raw = yf.download(symbol, period=period, interval="1d",
                          auto_adjust=True, progress=False, threads=False)
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"yfinance falló para {symbol}: {exc}") from exc
    if raw is None or raw.empty:
        raise ProviderError(f"yfinance sin datos para {symbol}.")
    col = "Close" if "Close" in raw.columns else "Adj Close"
    s = raw[col]
    if isinstance(s, pd.DataFrame):  # MultiIndex con un solo ticker
        s = s.iloc[:, 0]
    s = s.dropna()
    s.name = symbol
    return s[s > 0]


# ---------------------------------------------------------------------------
# Resolver unificado
# ---------------------------------------------------------------------------

def fetch_series(symbol: str, source: str, period: str) -> PriceSeries:
    """
    Serie de cierres para un instrumento según su `source`.

    ARG: data912 (histórico) y, para acciones/CEDEARs, fallback yfinance .BA.
    ONs: Rava (PPI fallback con creds). US: yfinance. Lanza ProviderError si no hay
    histórico utilizable.
    """
    symbol = symbol.strip().upper()
    meta = SOURCES.get(source)
    if meta is None:
        raise ProviderError(f"source desconocido: {source!r}")

    if source == "us":
        close = yfinance_history(symbol, period)
        return PriceSeries(symbol, source, "USD", "equity", close)

    if source == "arg_corp":
        err: Exception | None = None
        try:
            close = rava_history(symbol, period)
            if len(close) >= 20:
                return PriceSeries(symbol, source, meta["currency"], meta["kind"], close)
            err = ProviderError(f"{symbol}: Rava devolvió muy pocos datos.")
        except ProviderError as e:
            err = e
        if ppi_credentials_present():
            close = ppi_history(symbol, period)
            return PriceSeries(symbol, source, meta["currency"], meta["kind"], close)
        raise ProviderError(
            f"{symbol}: sin histórico de ON utilizable ({err}). "
            "Su precio/datos en vivo se muestran igual (BYMA)."
        )

    err = None
    cat = meta.get("d912")
    if cat:
        try:
            close = data912_history(symbol, cat, period)
            if len(close) >= 30:
                return PriceSeries(symbol, source, meta["currency"], meta["kind"], close)
            err = ProviderError(f"data912 con muy pocos datos para {symbol}.")
        except ProviderError as e:
            err = e

    suffix = meta.get("yf_suffix")
    if suffix:
        try:
            close = yfinance_history(symbol + suffix, period)
            return PriceSeries(symbol, source, meta["currency"], meta["kind"], close)
        except ProviderError as e:
            err = e

    raise ProviderError(str(err) if err else f"sin datos para {symbol} ({source}).")


# ---------------------------------------------------------------------------
# Cache en disco para fetch_series (para no pegarle a la red en cada request)
# ---------------------------------------------------------------------------
import hashlib as _hashlib  # noqa: E402
import pickle as _pickle  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_DEFAULT_CACHE_DIR = _Path("data") / "market_cache"
_CACHE_TTL_SECONDS = 86400  # 24h: data diaria, no hace falta intradía para el demo


def fetch_series_cached(
    symbol: str, source: str, period: str,
    *, cache_dir: _Path | str | None = None, ttl: int = _CACHE_TTL_SECONDS,
) -> PriceSeries:
    """
    fetch_series con cache en disco (TTL por defecto 24h). Evita re-descargar las
    mismas series en cada propuesta. Si el cache falla, cae a la red (fetch_series).
    Los errores NO se cachean (se propaga ProviderError).
    """
    cdir = _Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
    key = _hashlib.sha256(f"{symbol.strip().upper()}|{source}|{period}".encode()).hexdigest()[:16]
    fpath = cdir / f"{key}.pkl"
    try:
        # ttl <= 0 significa "no usar cache". El guard explícito evita el falso hit
        # en Windows cuando el mtime queda un tick adelante del reloj (edad negativa).
        if ttl > 0 and fpath.exists() and (time.time() - fpath.stat().st_mtime) < ttl:
            with open(fpath, "rb") as fh:
                return _pickle.load(fh)
    except Exception:  # noqa: BLE001 — cache corrupto → re-fetch
        pass
    ps = fetch_series(symbol, source, period)  # puede lanzar ProviderError
    try:
        cdir.mkdir(parents=True, exist_ok=True)
        with open(fpath, "wb") as fh:
            _pickle.dump(ps, fh)
    except Exception:  # noqa: BLE001 — sin cache, igual devolvemos la serie
        pass
    return ps


# ---------------------------------------------------------------------------
# PPI — histórico de ONs (requiere credenciales PPI_API_KEY / PPI_API_SECRET)
# ---------------------------------------------------------------------------

_PPI_CLIENT = {"AuthorizedClient": "API_CLI", "ClientKey": "pp_client"}
_ppi_token: dict[str, Any] = {"token": None, "exp": 0.0}


def ppi_credentials_present() -> bool:
    return bool(os.environ.get("PPI_API_KEY") and os.environ.get("PPI_API_SECRET"))


def _ppi_login() -> str:
    now = time.time()
    if _ppi_token["token"] and now < float(_ppi_token["exp"]):
        return str(_ppi_token["token"])
    headers = {
        **_PPI_CLIENT,
        "Content-Type": "application/json",
        "ApiKey": os.environ["PPI_API_KEY"],
        "ApiSecret": os.environ["PPI_API_SECRET"],
    }
    resp = requests.post(
        f"{PPI_BASE}/api/1.0/Account/LoginApi", headers=headers, json={}, timeout=_HTTP_TIMEOUT
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("accessToken") or data.get("access_token")
    if not token:
        raise ProviderError("PPI: login sin accessToken.")
    _ppi_token["token"] = token
    _ppi_token["exp"] = now + 600
    return token


def ppi_history(symbol: str, period: str, instrument_type: str = "BONOS",
                settlement: str = "A-24") -> pd.Series:
    """Histórico de cierres de una ON vía PPI MarketData/Historical. Requiere creds."""
    try:
        token = _ppi_login()
    except requests.RequestException as exc:
        raise ProviderError(f"PPI login falló: {exc}") from exc

    cut = _cutoff(period) or (_dt.date.today() - _dt.timedelta(days=3650))
    headers = {**_PPI_CLIENT, "Authorization": f"Bearer {token}"}
    params = {
        "ticker": symbol.strip().upper(),
        "type": instrument_type,
        "settlement": settlement,
        "dateFrom": cut.strftime("%m/%d/%Y"),
        "dateTo": _dt.date.today().strftime("%m/%d/%Y"),
    }
    try:
        resp = requests.get(
            f"{PPI_BASE}/api/1.0/MarketData/Historical",
            headers=headers, params=params, timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        rows = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"PPI histórico falló para {symbol}: {exc}") from exc

    if not rows:
        raise ProviderError(f"PPI sin datos para {symbol} ({instrument_type}/{settlement}).")

    points = {}
    for r in rows:
        date = r.get("date") or r.get("Date")
        price = r.get("price") or r.get("Price") or r.get("close") or r.get("settlementPrice")
        if date and price:
            points[pd.Timestamp(date)] = float(price)
    if not points:
        raise ProviderError(f"PPI: formato inesperado para {symbol}.")
    s = pd.Series(points, name=symbol).sort_index()
    return s[s > 0]
