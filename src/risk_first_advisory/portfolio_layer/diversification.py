"""
diversification — descomposición de diversificación de una cartera candidata.

Función pura: toma las holdings (ticker + weight + metadata del instrumento) y
computa concentración (HHI), reparto por ejes (clase de activo / sector / moneda),
un score 0-100 y una explicación en español. NO usa red, NO usa LLM, NO toca DB.

Misma idea que el framework de riesgo de 10 dimensiones de markowitz-optimizer
(concentración, single-stock, sector), pero sobre la metadata del universo de
risk-first — sin necesitar matriz de covarianza ni series de precios. Eso la hace
determinística y auditable: mismas holdings → mismo resultado.

Se usa para anotar cada cartera candidata del flujo case-scoped y para proponer
opciones de diversificación (slice 2): contrasta la variante dentro de capacidad
(A) vs la de override (B), explicando el porqué al asesor.
"""

from __future__ import annotations

from typing import Any

# Umbrales de banda de concentración sobre el HHI (Herfindahl-Hirschman, 0-1).
_HHI_BAJA = 0.15   # < → bien diversificado
_HHI_ALTA = 0.30   # > → concentrado

# Umbral de peso para contar una clase/sector como "presente" (ignora ruido).
_PRESENCE_MIN = 0.05


def _weights_by(holdings: list[dict[str, Any]], key: str) -> dict[str, float]:
    """Suma de pesos (normalizados) por valor de `key` (asset_class/sector/...)."""
    out: dict[str, float] = {}
    for h in holdings:
        label = str(h.get(key) or "Desconocido")
        out[label] = out.get(label, 0.0) + float(h.get("weight") or 0.0)
    return out


def assess_diversification(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Descompone la diversificación de una cartera.

    `holdings`: lista de dicts con al menos `ticker` y `weight` (0-1); opcional
    `asset_class`, `sector`, `currency`, `country`. Los pesos se normalizan
    internamente (no hace falta que sumen exactamente 1).

    Returns dict: holdings_count, hhi, effective_holdings, max_weight,
    max_weight_ticker, by_asset_class, by_sector, by_currency,
    concentration_band ("baja"|"media"|"alta"), diversification_score (0-100),
    flags (list[str]), summary (es).
    """
    items = [
        (str(h.get("ticker") or "—"), float(h.get("weight") or 0.0))
        for h in holdings
        if float(h.get("weight") or 0.0) > 0.0
    ]
    if not items:
        return {
            "holdings_count": 0,
            "hhi": 0.0,
            "effective_holdings": 0.0,
            "max_weight": 0.0,
            "max_weight_ticker": None,
            "by_asset_class": {},
            "by_sector": {},
            "by_currency": {},
            "concentration_band": "alta",
            "diversification_score": 0.0,
            "flags": ["cartera_vacia"],
            "summary": "La cartera no tiene posiciones con peso positivo.",
        }

    total = sum(w for _, w in items)
    norm = [(t, w / total) for t, w in items]  # pesos normalizados a 1

    hhi = sum(w * w for _, w in norm)
    effective = 1.0 / hhi if hhi > 0 else 0.0
    max_ticker, max_weight = max(norm, key=lambda kv: kv[1])

    # Normalizar holdings con pesos ya normalizados para los repartos por eje.
    norm_holdings = [
        {**h, "weight": float(h.get("weight") or 0.0) / total}
        for h in holdings
        if float(h.get("weight") or 0.0) > 0.0
    ]
    by_class = _weights_by(norm_holdings, "asset_class")
    by_sector = _weights_by(norm_holdings, "sector")
    by_currency = _weights_by(norm_holdings, "currency")

    if hhi < _HHI_BAJA:
        band = "baja"
    elif hhi <= _HHI_ALTA:
        band = "media"
    else:
        band = "alta"

    # Score 0-100 (mayor = mejor diversificado). Base: 1-HHI (concentración global).
    # Penalización extra por una sola clase de activo dominante (riesgo sistémico
    # no diluido). Auditable y monótono.
    classes_present = [c for c, w in by_class.items() if w >= _PRESENCE_MIN]
    score = (1.0 - hhi) * 100.0
    if len(classes_present) <= 1:
        score *= 0.85  # una sola clase: aunque haya muchos tickers, no diversifica riesgo
    score = round(max(0.0, min(100.0, score)), 1)

    flags: list[str] = []
    if max_weight > 0.35:
        flags.append("concentracion_single_asset")
    if len(classes_present) <= 1:
        flags.append("clase_unica")
    if len(items) < 4:
        flags.append("pocas_posiciones")
    max_sector_w = max(by_sector.values()) if by_sector else 0.0
    if max_sector_w > 0.50:
        flags.append("concentracion_sectorial")

    partes = [
        f"{len(items)} posiciones (equivalente diversificado ~{effective:.1f})",
        f"concentración {band} (HHI {hhi:.2f})",
        f"posición mayor {max_ticker} {max_weight * 100:.0f}%",
    ]
    if len(classes_present) <= 1:
        unica = classes_present[0] if classes_present else "una sola clase"
        partes.append(f"todo en {unica}: el riesgo de clase no está diluido")
    elif max_sector_w > 0.50:
        partes.append(f"sector dominante {max_sector_w * 100:.0f}%")
    summary = "; ".join(partes) + "."

    return {
        "holdings_count": len(items),
        "hhi": round(hhi, 4),
        "effective_holdings": round(effective, 2),
        "max_weight": round(max_weight, 4),
        "max_weight_ticker": max_ticker,
        "by_asset_class": {k: round(v, 4) for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])},
        "by_sector": {k: round(v, 4) for k, v in sorted(by_sector.items(), key=lambda kv: -kv[1])},
        "by_currency": {k: round(v, 4) for k, v in sorted(by_currency.items(), key=lambda kv: -kv[1])},
        "concentration_band": band,
        "diversification_score": score,
        "flags": flags,
        "summary": summary,
    }
