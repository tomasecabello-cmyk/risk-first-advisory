"""
DataQualityGate — compuerta de calidad de datos de mercado.

INVARIANTE CENTRAL: un instrumento puede estar aprobado por governance,
ser suitable para el perfil y ser ESG-compliant, y aun así NO debe pasar
al optimizador si sus datos de mercado son stale o tienen campos críticos
faltantes. Esta capa es la última verificación antes de que un snapshot
entre al pipeline cuantitativo.

Política sobre acumulación de status:
    Cuando un snapshot dispara simultáneamente reglas FAIL y reglas
    WARNING, el status final es FAIL (lo peor gana). Los reason_codes
    de TODAS las reglas que dispararon se acumulan, no se reemplazan,
    para que la auditoría quede completa.

Política sobre cash con volatilidad cero:
    Para asset_class == "cash" aceptamos volatility_annual = 0.0 sin
    warning, dado que ese es el comportamiento esperado de instrumentos
    de cash equivalente. Para cualquier otro asset_class, volatilidad
    cero es sospechosa y genera DATA_ZERO_VOLATILITY_NON_CASH.

Política sobre liquidity_score bajo:
    Umbral de "baja liquidez": liquidity_score < 0.20. Es WARNING, no
    FAIL: el optimizador puede usar el instrumento pero el resultado
    debería incluir una nota visible para el asesor.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from risk_first_advisory.data_layer.market_data import (
    CRITICAL_FIELDS,
    MarketDataSnapshot,
)

# Códigos de motivo específicos de la capa de calidad de datos.
REASON_DATA_STALE = "DATA_STALE"
REASON_CRITICAL_FIELD_MISSING = "DATA_CRITICAL_FIELD_MISSING"
REASON_NON_CRITICAL_FIELD_MISSING = "DATA_NON_CRITICAL_FIELD_MISSING"
REASON_LOW_LIQUIDITY = "DATA_LOW_LIQUIDITY"
REASON_ZERO_VOLATILITY_NON_CASH = "DATA_ZERO_VOLATILITY_NON_CASH"


# Umbral por debajo del cual liquidity_score se considera bajo.
LOW_LIQUIDITY_THRESHOLD = 0.20


class DataQualityStatus(str, Enum):
    """Resultado consolidado de la evaluación de calidad de datos."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass
class DataQualityResult:
    """
    Resultado de evaluar un MarketDataSnapshot.

    Reglas:
        - is_usable refleja si el snapshot puede pasar al optimizador.
          FAIL ⇒ is_usable False. WARNING/PASS ⇒ is_usable True.
        - failed_fields lista los nombres de campos críticos que faltan
          (subconjunto de CRITICAL_FIELDS).
        - warnings es la lista legible de advertencias.
        - reason_codes acumula códigos de TODAS las reglas que dispararon.
        - notes es libre para anotaciones del consumidor.
    """

    ticker: str
    status: DataQualityStatus
    is_usable: bool
    failed_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker no puede estar vacío.")
        if not isinstance(self.status, DataQualityStatus):
            raise ValueError(
                f"status debe ser DataQualityStatus. Recibido: "
                f"{type(self.status).__name__}."
            )
        if not isinstance(self.is_usable, bool):
            raise ValueError(
                f"is_usable debe ser bool. Recibido: "
                f"{type(self.is_usable).__name__}."
            )
        if not isinstance(self.failed_fields, list):
            raise ValueError("failed_fields debe ser una lista.")
        if not isinstance(self.warnings, list):
            raise ValueError("warnings debe ser una lista.")
        if not isinstance(self.reason_codes, list):
            raise ValueError("reason_codes debe ser una lista.")
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def is_failed(self) -> bool:
        return self.status == DataQualityStatus.FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "status": self.status.value,
            "is_usable": self.is_usable,
            "failed_fields": list(self.failed_fields),
            "warnings": list(self.warnings),
            "reason_codes": list(self.reason_codes),
            "notes": list(self.notes),
        }


class DataQualityGate:
    """
    Compuerta de calidad. Aplica reglas deterministas sobre snapshots.

    No tiene estado. Se puede instanciar una sola vez y usar para todos
    los snapshots de la sesión.
    """

    LOW_LIQUIDITY_THRESHOLD: float = LOW_LIQUIDITY_THRESHOLD
    CASH_ASSET_CLASS: str = "cash"

    # ── Evaluación individual ─────────────────────────────────────────────

    def evaluate(self, snapshot: MarketDataSnapshot) -> DataQualityResult:
        if not isinstance(snapshot, MarketDataSnapshot):
            raise ValueError(
                f"snapshot debe ser MarketDataSnapshot. Recibido: "
                f"{type(snapshot).__name__}."
            )

        failed_fields: list[str] = []
        warnings: list[str] = []
        reason_codes: list[str] = []

        has_fail = False
        has_warning = False

        # ── Regla 1: stale → FAIL ────────────────────────────────────
        if snapshot.stale:
            warnings.append(
                f"Snapshot de {snapshot.ticker!r} está marcado stale. "
                "No es apto para el pipeline cuantitativo."
            )
            reason_codes.append(REASON_DATA_STALE)
            has_fail = True

        # ── Regla 2: campos críticos faltantes → FAIL ────────────────
        missing_critical = [
            f for f in snapshot.missing_fields if f in CRITICAL_FIELDS
        ]
        if missing_critical:
            failed_fields.extend(missing_critical)
            warnings.append(
                f"Faltan campos críticos en {snapshot.ticker!r}: "
                f"{missing_critical}."
            )
            reason_codes.append(REASON_CRITICAL_FIELD_MISSING)
            has_fail = True

        # ── Regla 3: campos no críticos faltantes → WARNING ──────────
        missing_non_critical = [
            f for f in snapshot.missing_fields if f not in CRITICAL_FIELDS
        ]
        if missing_non_critical:
            warnings.append(
                f"Faltan campos no críticos en {snapshot.ticker!r}: "
                f"{missing_non_critical}. El instrumento puede usarse pero "
                "con datos parciales."
            )
            reason_codes.append(REASON_NON_CRITICAL_FIELD_MISSING)
            has_warning = True

        # ── Regla 4: low liquidity → WARNING ─────────────────────────
        if snapshot.liquidity_score < self.LOW_LIQUIDITY_THRESHOLD:
            warnings.append(
                f"liquidity_score={snapshot.liquidity_score} está por debajo "
                f"del umbral mínimo de {self.LOW_LIQUIDITY_THRESHOLD}. "
                "El instrumento puede tener fricción operativa."
            )
            reason_codes.append(REASON_LOW_LIQUIDITY)
            has_warning = True

        # ── Regla 5: zero volatility para no-cash → WARNING ──────────
        if (
            snapshot.volatility_annual == 0.0
            and snapshot.asset_class != self.CASH_ASSET_CLASS
        ):
            warnings.append(
                f"volatility_annual=0.0 inesperada para asset_class="
                f"{snapshot.asset_class!r}. Revisar fuente de datos."
            )
            reason_codes.append(REASON_ZERO_VOLATILITY_NON_CASH)
            has_warning = True

        # ── Consolidación de status ──────────────────────────────────
        if has_fail:
            status = DataQualityStatus.FAIL
            is_usable = False
        elif has_warning:
            status = DataQualityStatus.WARNING
            is_usable = True
        else:
            status = DataQualityStatus.PASS
            is_usable = True

        return DataQualityResult(
            ticker=snapshot.ticker,
            status=status,
            is_usable=is_usable,
            failed_fields=failed_fields,
            warnings=warnings,
            reason_codes=reason_codes,
            notes=[],
        )

    # ── Evaluación en lote ────────────────────────────────────────────────

    def evaluate_many(
        self,
        snapshots: list[MarketDataSnapshot],
    ) -> list[DataQualityResult]:
        """
        Evalúa una lista de snapshots y preserva el orden.

        No deduplica por ticker; el caller decide si llama con duplicados.
        """
        return [self.evaluate(s) for s in snapshots]

    # ── Filtros sobre resultados ──────────────────────────────────────────

    @staticmethod
    def passed(results: list[DataQualityResult]) -> list[str]:
        """Tickers con status PASS."""
        return [r.ticker for r in results if r.status == DataQualityStatus.PASS]

    @staticmethod
    def failed(results: list[DataQualityResult]) -> list[str]:
        """Tickers con status FAIL."""
        return [r.ticker for r in results if r.status == DataQualityStatus.FAIL]

    @staticmethod
    def warning(results: list[DataQualityResult]) -> list[str]:
        """Tickers con status WARNING."""
        return [
            r.ticker for r in results if r.status == DataQualityStatus.WARNING
        ]
