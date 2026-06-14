"""
MockMarketDataProvider — provee datos cuantitativos por ticker desde YAML.

INVARIANTE CENTRAL: el optimizador y las capas cuantitativas posteriores
NO dependen ni de YAML ni de Bloomberg directamente. Dependen del contrato
expuesto por este módulo (MarketDataSnapshot + Provider).

En M1 solo existe MockMarketDataProvider. Sprints siguientes agregarán
CSVMarketDataProvider y BloombergMarketDataProvider implementando el mismo
contrato. Cambiar de proveedor no debe requerir cambios en quant_layer.

Sobre is_complete vs is_usable:
    - is_complete: el snapshot tiene todos los datos esperados y no está
      marcado stale. Es la condición ideal.
    - is_usable: el snapshot puede pasar al pipeline cuantitativo. Permite
      que falten campos NO críticos (por ejemplo, duration en activos
      equity). is_usable es estricto sobre stale: stale → no usable.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Campos críticos: si falta cualquiera de estos, el snapshot NO es usable
# por la capa cuantitativa. Otros campos (como `duration`) pueden faltar
# legítimamente para ciertos asset_classes (por ejemplo, equity).
CRITICAL_FIELDS: frozenset[str] = frozenset(
    {
        "expected_return_annual",
        "volatility_annual",
        "liquidity_score",
        "asset_class",
        "currency",
    }
)


@dataclass
class MarketDataSnapshot:
    """
    Snapshot inmutable de datos de mercado para un ticker.

    Convenciones:
        - expected_return_annual: retorno anualizado esperado, en decimal.
          0.07 = 7% anual. Rango aceptado: [-1.0, 1.0].
        - volatility_annual: desvío estándar anualizado, en decimal.
          Mínimo 0.0. Sin tope superior duro (instrumentos exóticos pueden
          tener vol > 1.0).
        - liquidity_score: estimación de liquidez en [0.0, 1.0]. 1.0 = muy
          líquido (ej. T-Bills, ETFs grandes). 0.0 = ilíquido.
        - expense_ratio: en decimal anual. 0.0009 = 9 bps.
        - duration: años de duration modificada para renta fija. None para
          equity y otros instrumentos sin duration aplicable.
        - asset_class: clasificación cuantitativa (cash, bond, equity,
          high_yield, sector_equity, etc.). No es lo mismo que
          instrument_type de la matriz de suitability, aunque suelen
          relacionarse.
        - stale: True si el dato es viejo y no debe usarse en producción.
        - missing_fields: lista de nombres de campos cuyo valor presente
          es un placeholder o desconocido. El consumidor decide qué hacer.
        - notes: notas operativas (origen del dato, ajustes, etc.).
    """

    ticker: str
    expected_return_annual: float
    volatility_annual: float
    liquidity_score: float
    expense_ratio: float
    duration: float | None
    asset_class: str
    currency: str
    stale: bool = False
    missing_fields: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker no puede estar vacío.")

        if not isinstance(self.expected_return_annual, (int, float)):
            raise ValueError(
                "expected_return_annual debe ser numérico. Recibido: "
                f"{type(self.expected_return_annual).__name__}."
            )
        if not -1.0 <= float(self.expected_return_annual) <= 1.0:
            raise ValueError(
                f"expected_return_annual debe estar en [-1.0, 1.0]. "
                f"Recibido: {self.expected_return_annual}."
            )

        if not isinstance(self.volatility_annual, (int, float)):
            raise ValueError(
                "volatility_annual debe ser numérico. Recibido: "
                f"{type(self.volatility_annual).__name__}."
            )
        if float(self.volatility_annual) < 0.0:
            raise ValueError(
                f"volatility_annual no puede ser negativo. Recibido: "
                f"{self.volatility_annual}."
            )

        if not isinstance(self.liquidity_score, (int, float)):
            raise ValueError(
                "liquidity_score debe ser numérico. Recibido: "
                f"{type(self.liquidity_score).__name__}."
            )
        if not 0.0 <= float(self.liquidity_score) <= 1.0:
            raise ValueError(
                f"liquidity_score debe estar en [0.0, 1.0]. Recibido: "
                f"{self.liquidity_score}."
            )

        if not isinstance(self.expense_ratio, (int, float)):
            raise ValueError(
                "expense_ratio debe ser numérico. Recibido: "
                f"{type(self.expense_ratio).__name__}."
            )
        if float(self.expense_ratio) < 0.0:
            raise ValueError(
                f"expense_ratio no puede ser negativo. Recibido: "
                f"{self.expense_ratio}."
            )

        if self.duration is not None:
            if not isinstance(self.duration, (int, float)):
                raise ValueError(
                    "duration debe ser numérico o None. Recibido: "
                    f"{type(self.duration).__name__}."
                )
            if float(self.duration) < 0.0:
                raise ValueError(
                    f"duration no puede ser negativo. Recibido: {self.duration}."
                )

        if not self.asset_class or not self.asset_class.strip():
            raise ValueError("asset_class no puede estar vacío.")
        if not self.currency or not self.currency.strip():
            raise ValueError("currency no puede estar vacío.")

        if not isinstance(self.missing_fields, list):
            raise ValueError("missing_fields debe ser una lista.")
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")
        if not isinstance(self.stale, bool):
            raise ValueError(
                f"stale debe ser bool. Recibido: {type(self.stale).__name__}."
            )

    @property
    def is_complete(self) -> bool:
        """True si no hay missing_fields y el dato no es stale."""
        return (not self.stale) and (len(self.missing_fields) == 0)

    @property
    def is_usable(self) -> bool:
        """
        True si el snapshot puede pasar al pipeline cuantitativo.

        Reglas:
            - Si stale → no usable.
            - Si falta cualquier campo crítico → no usable.
            - Si solo faltan campos NO críticos → usable (con notas).
        """
        if self.stale:
            return False
        missing_critical = set(self.missing_fields) & CRITICAL_FIELDS
        return len(missing_critical) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "expected_return_annual": self.expected_return_annual,
            "volatility_annual": self.volatility_annual,
            "liquidity_score": self.liquidity_score,
            "expense_ratio": self.expense_ratio,
            "duration": self.duration,
            "asset_class": self.asset_class,
            "currency": self.currency,
            "stale": self.stale,
            "missing_fields": list(self.missing_fields),
            "notes": list(self.notes),
        }


class MockMarketDataProvider:
    """
    Proveedor de MarketDataSnapshot desde YAML.

    Es la implementación mínima del contrato de "market data provider" para
    M1. Permite probar todo el pipeline cuantitativo sin Bloomberg ni CSV
    reales.
    """

    def __init__(self, snapshots: list[MarketDataSnapshot]):
        self._snapshots: dict[str, MarketDataSnapshot] = {}
        for s in snapshots:
            if s.ticker in self._snapshots:
                raise ValueError(
                    f"Ticker duplicado en market data: {s.ticker!r}."
                )
            self._snapshots[s.ticker] = s

    # ── Carga desde YAML ──────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MockMarketDataProvider":
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(
                f"Archivo de market data no encontrado: {yaml_path}."
            )

        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML inválido en {yaml_path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"YAML inválido en {yaml_path}: el documento raíz debe ser un mapping."
            )
        if "snapshots" not in data:
            raise ValueError(
                f"YAML inválido en {yaml_path}: falta la clave 'snapshots' en la raíz."
            )
        if not isinstance(data["snapshots"], list):
            raise ValueError(
                f"YAML inválido en {yaml_path}: 'snapshots' debe ser una lista."
            )

        snapshots: list[MarketDataSnapshot] = []
        for idx, raw in enumerate(data["snapshots"]):
            if not isinstance(raw, dict):
                raise ValueError(
                    f"YAML inválido en {yaml_path}: snapshot #{idx} no es un mapping."
                )
            snapshots.append(cls._snapshot_from_dict(raw, source=str(yaml_path), index=idx))
        return cls(snapshots)

    @staticmethod
    def _snapshot_from_dict(
        raw: dict[str, Any],
        source: str,
        index: int,
    ) -> MarketDataSnapshot:
        try:
            return MarketDataSnapshot(
                ticker=raw["ticker"],
                expected_return_annual=float(raw["expected_return_annual"]),
                volatility_annual=float(raw["volatility_annual"]),
                liquidity_score=float(raw["liquidity_score"]),
                expense_ratio=float(raw["expense_ratio"]),
                duration=(
                    float(raw["duration"])
                    if raw.get("duration") is not None
                    else None
                ),
                asset_class=raw["asset_class"],
                currency=raw["currency"],
                stale=bool(raw.get("stale", False)),
                missing_fields=list(raw.get("missing_fields", [])),
                notes=list(raw.get("notes", [])),
            )
        except KeyError as exc:
            raise ValueError(
                f"YAML inválido en {source}: snapshot #{index} falta el campo "
                f"{exc.args[0]!r}."
            ) from exc
        except ValueError as exc:
            raise ValueError(
                f"YAML inválido en {source}: snapshot #{index} es inválido: {exc}"
            ) from exc

    # ── Consultas ─────────────────────────────────────────────────────────

    def contains(self, ticker: str) -> bool:
        return ticker in self._snapshots

    def get_snapshot(self, ticker: str) -> MarketDataSnapshot | None:
        return self._snapshots.get(ticker)

    def all_snapshots(self) -> list[MarketDataSnapshot]:
        """Copia defensiva: modificar la lista no altera el provider."""
        return list(self._snapshots.values())

    def get_many(self, tickers: list[str]) -> list[MarketDataSnapshot]:
        """
        Devuelve los snapshots de los tickers solicitados, en el orden pedido.

        Tickers ausentes se OMITEN del resultado (no se devuelve None ni se
        lanza error). Para saber cuáles faltan, usar `missing_tickers`.
        """
        result: list[MarketDataSnapshot] = []
        for t in tickers:
            snap = self._snapshots.get(t)
            if snap is not None:
                result.append(snap)
        return result

    def missing_tickers(self, tickers: list[str]) -> list[str]:
        """Devuelve los tickers de la lista que NO están en el provider."""
        return [t for t in tickers if t not in self._snapshots]

    def __len__(self) -> int:
        return len(self._snapshots)

    def __contains__(self, ticker: str) -> bool:
        return self.contains(ticker)
