"""
CovarianceEngine — construye una matriz de covarianza anualizada.

Regla central: el optimizador no inventa riesgo. Recibe explícitamente
volatilidades, correlaciones y covarianza desde esta capa testeada.

Correlaciones mock por asset_class. Diagonal: corr=1.0, cov=vol^2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from risk_first_advisory.data_layer.market_data import MarketDataSnapshot

# ---------------------------------------------------------------------------
# Normalización de asset_class
# ---------------------------------------------------------------------------

_ASSET_CLASS_ALIASES: dict[str, str] = {
    "cash": "cash",
    "bond": "bond",
    "fixed_income": "bond",
    "aggregate_bond": "bond",
    "equity": "equity",
    "global_equity": "equity",
    "high_yield": "high_yield",
    "thematic_equity": "thematic_equity",
    "sector_equity": "sector_equity",
}

_KNOWN_CLASSES = frozenset(_ASSET_CLASS_ALIASES.values())


def _normalize_class(asset_class: str) -> str:
    return _ASSET_CLASS_ALIASES.get(asset_class.lower().strip(), "unknown")


# ---------------------------------------------------------------------------
# Tabla de correlaciones mock (clase canónica → clase canónica → float)
# ---------------------------------------------------------------------------

_CORR_TABLE: dict[tuple[str, str], float] = {
    ("cash", "cash"): 0.10,
    ("cash", "bond"): 0.05,
    ("cash", "equity"): 0.00,
    ("cash", "high_yield"): 0.05,
    ("cash", "thematic_equity"): 0.00,
    ("cash", "sector_equity"): 0.00,
    ("bond", "bond"): 0.80,
    ("bond", "equity"): 0.25,
    ("bond", "high_yield"): 0.45,
    ("bond", "thematic_equity"): 0.20,
    ("bond", "sector_equity"): 0.20,
    ("equity", "equity"): 0.85,
    ("equity", "high_yield"): 0.60,
    ("equity", "thematic_equity"): 0.75,
    ("equity", "sector_equity"): 0.80,
    ("high_yield", "high_yield"): 0.75,
    ("high_yield", "thematic_equity"): 0.55,
    ("high_yield", "sector_equity"): 0.60,
    ("thematic_equity", "thematic_equity"): 0.80,
    ("thematic_equity", "sector_equity"): 0.75,
    ("sector_equity", "sector_equity"): 0.80,
}

_UNKNOWN_CORR_DEFAULT = 0.75
_UNKNOWN_CORR_VS_CASH = 0.00


def _lookup_correlation(class_a: str, class_b: str) -> float:
    """Devuelve correlación entre dos clases normalizadas."""
    if class_a == class_b:
        # diagonal — caller debe reemplazar por 1.0
        key = (class_a, class_b)
        return _CORR_TABLE.get(key, 1.0)

    # unknown handling
    if class_a == "unknown" or class_b == "unknown":
        other = class_b if class_a == "unknown" else class_a
        return _UNKNOWN_CORR_VS_CASH if other == "cash" else _UNKNOWN_CORR_DEFAULT

    key = (class_a, class_b)
    if key in _CORR_TABLE:
        return _CORR_TABLE[key]
    key_rev = (class_b, class_a)
    if key_rev in _CORR_TABLE:
        return _CORR_TABLE[key_rev]
    return _UNKNOWN_CORR_DEFAULT


# ---------------------------------------------------------------------------
# CovarianceMatrix
# ---------------------------------------------------------------------------

@dataclass
class CovarianceMatrix:
    """
    Matriz de covarianza anualizada para una lista de tickers.

    Invariantes:
        - tickers no vacío
        - covariance y correlation son matrices NxN donde N = len(tickers)
        - diagonal de correlation es 1.0
        - annualized es bool
        - notes es lista
    """

    tickers: list[str]
    covariance: list[list[float]]
    correlation: list[list[float]]
    annualized: bool
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tickers:
            raise ValueError("tickers no puede estar vacío.")

        n = len(self.tickers)

        if not isinstance(self.annualized, bool):
            raise ValueError(
                f"annualized debe ser bool. Recibido: {type(self.annualized).__name__}."
            )
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")

        # Validar covariance
        if len(self.covariance) != n:
            raise ValueError(
                f"covariance debe tener {n} filas, tiene {len(self.covariance)}."
            )
        for i, row in enumerate(self.covariance):
            if len(row) != n:
                raise ValueError(
                    f"covariance fila {i} debe tener {n} columnas, tiene {len(row)}."
                )

        # Validar correlation
        if len(self.correlation) != n:
            raise ValueError(
                f"correlation debe tener {n} filas, tiene {len(self.correlation)}."
            )
        for i, row in enumerate(self.correlation):
            if len(row) != n:
                raise ValueError(
                    f"correlation fila {i} debe tener {n} columnas, tiene {len(row)}."
                )
            if abs(row[i] - 1.0) > 1e-9:
                raise ValueError(
                    f"correlation diagonal [{i}][{i}] debe ser 1.0, "
                    f"es {row[i]}."
                )

    # ── Accesores ──────────────────────────────────────────────────────────

    def _index(self, ticker: str) -> int:
        try:
            return self.tickers.index(ticker)
        except ValueError:
            raise KeyError(f"Ticker no encontrado en CovarianceMatrix: {ticker!r}.")

    def get_covariance(self, ticker_a: str, ticker_b: str) -> float:
        i = self._index(ticker_a)
        j = self._index(ticker_b)
        return self.covariance[i][j]

    def get_correlation(self, ticker_a: str, ticker_b: str) -> float:
        i = self._index(ticker_a)
        j = self._index(ticker_b)
        return self.correlation[i][j]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tickers": list(self.tickers),
            "covariance": [list(row) for row in self.covariance],
            "correlation": [list(row) for row in self.correlation],
            "annualized": self.annualized,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# CovarianceEngine
# ---------------------------------------------------------------------------

class CovarianceEngine:
    """
    Construye una CovarianceMatrix anualizada a partir de MarketDataSnapshot.

    Correlaciones son mock por asset_class; covarianza se calcula como
        cov[i][j] = corr(i,j) * vol_i * vol_j
    """

    def build(self, snapshots: list[MarketDataSnapshot]) -> CovarianceMatrix:
        """
        Construye CovarianceMatrix desde una lista de snapshots.

        Raises:
            ValueError: lista vacía, tickers duplicados, o snapshot no usable.
        """
        if not snapshots:
            raise ValueError(
                "CovarianceEngine.build requiere al menos un snapshot; "
                "se recibió una lista vacía."
            )

        # Validar duplicados
        seen: set[str] = set()
        for snap in snapshots:
            if snap.ticker in seen:
                raise ValueError(
                    f"Ticker duplicado en snapshots: {snap.ticker!r}."
                )
            seen.add(snap.ticker)

        # Validar usabilidad
        for snap in snapshots:
            if not snap.is_usable:
                raise ValueError(
                    f"Snapshot para {snap.ticker!r} no es usable "
                    f"(stale={snap.stale}, missing_fields={snap.missing_fields})."
                )

        n = len(snapshots)
        tickers = [s.ticker for s in snapshots]
        vols = [s.volatility_annual for s in snapshots]
        classes = [_normalize_class(s.asset_class) for s in snapshots]

        # Construir matrices
        corr: list[list[float]] = [[0.0] * n for _ in range(n)]
        cov: list[list[float]] = [[0.0] * n for _ in range(n)]

        for i in range(n):
            for j in range(n):
                if i == j:
                    corr[i][j] = 1.0
                    cov[i][j] = vols[i] ** 2
                else:
                    c = _lookup_correlation(classes[i], classes[j])
                    corr[i][j] = c
                    cov[i][j] = c * vols[i] * vols[j]

        notes = [
            "Correlaciones mock por asset_class. No usar en producción sin calibración real.",
            f"Tickers: {', '.join(tickers)}",
        ]

        return CovarianceMatrix(
            tickers=tickers,
            covariance=cov,
            correlation=corr,
            annualized=True,
            notes=notes,
        )
