"""
ReturnEstimator — capa de ajuste de retornos esperados antes del optimizador.

INVARIANTE CENTRAL: el retorno esperado que usa el optimizador NO es
directamente el `expected_return_annual` crudo del MarketDataSnapshot.
Pasa siempre por esta capa, que aplica:

    adjusted = raw - expense_ratio + esg_adjustment + data_quality_adjustment

donde:
    raw              : snapshot.expected_return_annual
    expense_ratio    : snapshot.expense_ratio (siempre se resta)
    esg_adjustment   : ∈ [-0.01, 0.0] derivado de ESGComplianceResult
    data_quality_adj : ∈ [-0.0025, 0.0] derivado de DataQualityResult

Toda diferencia entre raw y adjusted queda documentada en reason_codes.

Política ante BLOCKED / FAIL:
    Si ESGComplianceResult.status == BLOCKED: levantar ValueError.
    Si DataQualityResult.status == FAIL:       levantar ValueError.
    Un instrumento bloqueado o con datos fallidos no debe entrar al
    optimizador. El caller (pipeline de construcción de cartera) es
    responsable de filtrar antes; si lo pasa igual, el error es intencional.

Clipping:
    El valor ajustado se recorta a [-1.0, 1.0].
    Si se aplica clipping se agrega RETURN_CLIPPED a reason_codes.
    Con inputs válidos el límite superior difícilmente se alcanza,
    pero la capa lo soporta para futura extensibilidad.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from risk_first_advisory.data_layer.data_quality import (
    DataQualityResult,
    DataQualityStatus,
)
from risk_first_advisory.data_layer.market_data import MarketDataSnapshot
from risk_first_advisory.rules_layer.esg_compliance import (
    ESGComplianceResult,
    ESGComplianceStatus,
)

# ── Reason codes propios de esta capa ────────────────────────────────────────

RC_COST_EXPENSE_RATIO = "COST_EXPENSE_RATIO_APPLIED"
RC_ESG_UNKNOWN = "ESG_UNKNOWN_ADJUSTMENT"
RC_DATA_QUALITY_WARNING = "DATA_QUALITY_WARNING_ADJUSTMENT"
RC_RETURN_CLIPPED = "RETURN_CLIPPED"


# ── Parámetros de ajuste ─────────────────────────────────────────────────────

# Penalización fija cuando no hay metadata ESG (UNKNOWN).
ESG_UNKNOWN_PENALTY: float = -0.005

# Factor de escala para SOFT_WARNING: soft_score_adjustment * ESG_SOFT_SCALE.
# soft_score_adjustment ∈ [-1.0, 0.0] → esg_adjustment ∈ [-0.01, 0.0].
ESG_SOFT_SCALE: float = 0.01

# Penalización fija cuando DataQuality es WARNING.
DQ_WARNING_PENALTY: float = -0.0025


# ── Modelo de output ─────────────────────────────────────────────────────────


@dataclass
class ReturnEstimate:
    """
    Retorno ajustado de un instrumento, listo para el optimizador.

    Campos:
        ticker                    : identificador del instrumento.
        raw_expected_return_annual: retorno crudo del snapshot (sin ajustes).
        expense_ratio             : ratio de costos, siempre restado.
        esg_adjustment            : ∈ [-1.0, 0.0]; 0.0 si sin penalización ESG.
        data_quality_adjustment   : ∈ [-1.0, 0.0]; 0.0 si calidad OK.
        adjusted_expected_return_annual : retorno final ∈ [-1.0, 1.0].
        reason_codes              : lista de códigos auditables.
        notes                     : notas operativas libres.

    Invariante de signo:
        esg_adjustment <= 0.0
        data_quality_adjustment <= 0.0
        expense_ratio >= 0.0
        → adjusted <= raw (nunca se infla el retorno crudo)
    """

    ticker: str
    raw_expected_return_annual: float
    expense_ratio: float
    esg_adjustment: float
    data_quality_adjustment: float
    adjusted_expected_return_annual: float
    reason_codes: list[str]
    notes: list[str]

    def __post_init__(self) -> None:
        if not self.ticker or not self.ticker.strip():
            raise ValueError("ticker no puede estar vacío.")

        if not isinstance(self.raw_expected_return_annual, (int, float)):
            raise ValueError(
                "raw_expected_return_annual debe ser numérico. "
                f"Recibido: {type(self.raw_expected_return_annual).__name__}."
            )
        if not -1.0 <= float(self.raw_expected_return_annual) <= 1.0:
            raise ValueError(
                "raw_expected_return_annual debe estar en [-1.0, 1.0]. "
                f"Recibido: {self.raw_expected_return_annual}."
            )

        if not isinstance(self.expense_ratio, (int, float)):
            raise ValueError(
                "expense_ratio debe ser numérico. "
                f"Recibido: {type(self.expense_ratio).__name__}."
            )
        if float(self.expense_ratio) < 0.0:
            raise ValueError(
                f"expense_ratio no puede ser negativo. "
                f"Recibido: {self.expense_ratio}."
            )

        if not isinstance(self.esg_adjustment, (int, float)):
            raise ValueError(
                "esg_adjustment debe ser numérico. "
                f"Recibido: {type(self.esg_adjustment).__name__}."
            )
        if not -1.0 <= float(self.esg_adjustment) <= 0.0:
            raise ValueError(
                "esg_adjustment debe estar en [-1.0, 0.0]. "
                f"Recibido: {self.esg_adjustment}."
            )

        if not isinstance(self.data_quality_adjustment, (int, float)):
            raise ValueError(
                "data_quality_adjustment debe ser numérico. "
                f"Recibido: {type(self.data_quality_adjustment).__name__}."
            )
        if not -1.0 <= float(self.data_quality_adjustment) <= 0.0:
            raise ValueError(
                "data_quality_adjustment debe estar en [-1.0, 0.0]. "
                f"Recibido: {self.data_quality_adjustment}."
            )

        if not isinstance(self.adjusted_expected_return_annual, (int, float)):
            raise ValueError(
                "adjusted_expected_return_annual debe ser numérico. "
                f"Recibido: {type(self.adjusted_expected_return_annual).__name__}."
            )
        if not -1.0 <= float(self.adjusted_expected_return_annual) <= 1.0:
            raise ValueError(
                "adjusted_expected_return_annual debe estar en [-1.0, 1.0]. "
                f"Recibido: {self.adjusted_expected_return_annual}."
            )

        if not isinstance(self.reason_codes, list):
            raise ValueError(
                "reason_codes debe ser una lista. "
                f"Recibido: {type(self.reason_codes).__name__}."
            )
        if not isinstance(self.notes, list):
            raise ValueError(
                "notes debe ser una lista. "
                f"Recibido: {type(self.notes).__name__}."
            )

    @property
    def has_penalties(self) -> bool:
        """
        True si se aplicó algún ajuste negativo o si hay costo de expense ratio.

        Cualquiera de las siguientes condiciones activa la propiedad:
            - esg_adjustment < 0.0
            - data_quality_adjustment < 0.0
            - expense_ratio > 0.0
        """
        return (
            self.esg_adjustment < 0.0
            or self.data_quality_adjustment < 0.0
            or self.expense_ratio > 0.0
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialización JSON-compatible. Todos los valores son tipos primitivos."""
        return {
            "ticker": self.ticker,
            "raw_expected_return_annual": self.raw_expected_return_annual,
            "expense_ratio": self.expense_ratio,
            "esg_adjustment": self.esg_adjustment,
            "data_quality_adjustment": self.data_quality_adjustment,
            "adjusted_expected_return_annual": self.adjusted_expected_return_annual,
            "reason_codes": list(self.reason_codes),
            "notes": list(self.notes),
            "has_penalties": self.has_penalties,
        }


# ── Motor de estimación ──────────────────────────────────────────────────────


class ReturnEstimator:
    """
    Aplica ajustes explícitos sobre retornos crudos de MarketDataSnapshot.

    No tiene estado. Una instancia puede reutilizarse para todos los
    snapshots de la sesión.

    Flujo de `estimate()`:
        1. Verificar que ESG no está BLOCKED y DataQuality no está FAIL.
           Si lo están, levantar ValueError — el instrumento no debe entrar.
        2. Calcular esg_adjustment, data_quality_adjustment y expense_ratio.
        3. Acumular reason_codes por cada ajuste aplicado.
        4. Calcular adjusted = raw - expense + esg_adj + dq_adj.
        5. Clip a [-1.0, 1.0]; si se aplicó, agregar RETURN_CLIPPED.
        6. Construir y devolver ReturnEstimate.
    """

    # ── Interfaz pública ─────────────────────────────────────────────────────

    def estimate(
        self,
        snapshot: MarketDataSnapshot,
        esg_result: ESGComplianceResult | None = None,
        data_quality_result: DataQualityResult | None = None,
    ) -> ReturnEstimate:
        """
        Calcula el retorno ajustado para un único snapshot.

        Args:
            snapshot             : datos de mercado del instrumento.
            esg_result           : resultado ESG; None = sin penalización.
            data_quality_result  : resultado de calidad; None = sin penalización.

        Returns:
            ReturnEstimate con retorno ajustado y reason_codes completos.

        Raises:
            ValueError: si esg_result.status == BLOCKED.
            ValueError: si data_quality_result.status == FAIL.
        """
        # ── Guardas tempranas: instrumentos no elegibles ──────────────
        if (
            esg_result is not None
            and esg_result.status == ESGComplianceStatus.BLOCKED
        ):
            raise ValueError(
                f"El ticker {snapshot.ticker!r} está BLOCKED por ESG compliance "
                "y no puede estimarse. Debe ser filtrado antes de llegar al estimador."
            )

        if (
            data_quality_result is not None
            and data_quality_result.status == DataQualityStatus.FAIL
        ):
            raise ValueError(
                f"El ticker {snapshot.ticker!r} tiene DataQuality FAIL "
                "y no puede estimarse. Verifique el snapshot antes de estimar."
            )

        # ── Cálculo de ajustes ────────────────────────────────────────
        reason_codes: list[str] = []
        notes: list[str] = []

        esg_adj = self._compute_esg_adjustment(esg_result, reason_codes, notes)
        dq_adj = self._compute_dq_adjustment(data_quality_result, reason_codes, notes)

        expense = snapshot.expense_ratio
        if expense > 0.0:
            reason_codes.append(RC_COST_EXPENSE_RATIO)

        # ── Fórmula central ───────────────────────────────────────────
        raw = snapshot.expected_return_annual
        pre_adjusted = raw - expense + esg_adj + dq_adj

        # ── Clipping ──────────────────────────────────────────────────
        adjusted, reason_codes = self._clip_and_annotate(pre_adjusted, reason_codes)

        return ReturnEstimate(
            ticker=snapshot.ticker,
            raw_expected_return_annual=raw,
            expense_ratio=expense,
            esg_adjustment=esg_adj,
            data_quality_adjustment=dq_adj,
            adjusted_expected_return_annual=adjusted,
            reason_codes=reason_codes,
            notes=notes,
        )

    def estimate_many(
        self,
        snapshots: list[MarketDataSnapshot],
        esg_results_by_ticker: dict[str, ESGComplianceResult] | None = None,
        data_quality_results_by_ticker: dict[str, DataQualityResult] | None = None,
    ) -> list[ReturnEstimate]:
        """
        Calcula retornos ajustados para una lista de snapshots.

        Preserva el orden de `snapshots`. Si falta ESG o DataQuality para
        un ticker, ese componente se trata como None (sin penalización para
        ese eje). Errores (BLOCKED / FAIL) se propagan sin silenciar.

        Args:
            snapshots                      : lista de snapshots a estimar.
            esg_results_by_ticker          : dict ticker → ESGComplianceResult.
            data_quality_results_by_ticker : dict ticker → DataQualityResult.

        Returns:
            Lista de ReturnEstimate en el mismo orden que `snapshots`.

        Raises:
            ValueError: si cualquier snapshot genera un error (BLOCKED / FAIL).
        """
        esg_map = esg_results_by_ticker or {}
        dq_map = data_quality_results_by_ticker or {}

        return [
            self.estimate(
                snapshot=snap,
                esg_result=esg_map.get(snap.ticker),
                data_quality_result=dq_map.get(snap.ticker),
            )
            for snap in snapshots
        ]

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_esg_adjustment(
        esg_result: ESGComplianceResult | None,
        reason_codes: list[str],
        notes: list[str],
    ) -> float:
        """
        Calcula el ajuste ESG y muta reason_codes/notes según corresponda.

        Precondición: esg_result.status != BLOCKED (ya verificado por caller).
        """
        if esg_result is None:
            return 0.0

        if esg_result.status == ESGComplianceStatus.PASS:
            return 0.0

        if esg_result.status == ESGComplianceStatus.UNKNOWN:
            reason_codes.append(RC_ESG_UNKNOWN)
            notes.append(
                f"Sin metadata ESG para {esg_result.ticker!r}. "
                f"Penalización fija aplicada: {ESG_UNKNOWN_PENALTY:.4%}."
            )
            return ESG_UNKNOWN_PENALTY

        if esg_result.status == ESGComplianceStatus.SOFT_WARNING:
            adj = esg_result.soft_score_adjustment * ESG_SOFT_SCALE
            if adj < 0.0:
                notes.append(
                    f"ESG soft_score_adjustment={esg_result.soft_score_adjustment} "
                    f"→ esg_adjustment={adj:.6f}."
                )
            return adj

        # Caso BLOCKED ya fue chequeado: no debería llegar aquí.
        return 0.0  # pragma: no cover

    @staticmethod
    def _compute_dq_adjustment(
        data_quality_result: DataQualityResult | None,
        reason_codes: list[str],
        notes: list[str],
    ) -> float:
        """
        Calcula el ajuste de calidad de datos y muta reason_codes/notes.

        Precondición: data_quality_result.status != FAIL (ya verificado).
        """
        if data_quality_result is None:
            return 0.0

        if data_quality_result.status == DataQualityStatus.PASS:
            return 0.0

        if data_quality_result.status == DataQualityStatus.WARNING:
            reason_codes.append(RC_DATA_QUALITY_WARNING)
            notes.append(
                f"DataQuality WARNING para {data_quality_result.ticker!r}. "
                f"Penalización fija aplicada: {DQ_WARNING_PENALTY:.4%}."
            )
            return DQ_WARNING_PENALTY

        # Caso FAIL ya fue chequeado: no debería llegar aquí.
        return 0.0  # pragma: no cover

    @staticmethod
    def _clip_and_annotate(
        pre_adjusted: float,
        reason_codes: list[str],
    ) -> tuple[float, list[str]]:
        """
        Recorta pre_adjusted a [-1.0, 1.0] y agrega RETURN_CLIPPED si aplica.

        Devuelve una NUEVA lista de reason_codes (no muta la entrada).
        Esto permite llamar a este método en tests unitarios sin efectos laterales.
        """
        codes = list(reason_codes)
        if pre_adjusted > 1.0:
            codes.append(RC_RETURN_CLIPPED)
            return 1.0, codes
        if pre_adjusted < -1.0:
            codes.append(RC_RETURN_CLIPPED)
            return -1.0, codes
        return pre_adjusted, codes
