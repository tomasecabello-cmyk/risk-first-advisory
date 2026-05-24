"""
GoalFeasibilityEngine — calcula si un objetivo financiero es viable dado un perfil aprobado.

Principio central (DD-002 / DD-003):
    El retorno requerido se calcula EXCLUSIVAMENTE desde FinancialGoal.
    No usa declared_return_expectation_pct ni ningún campo verbal del KYC.
    El engine no recibe KYCData.

Método de cálculo:
    Bisección numérica sobre la ecuación de valor futuro:

        FV(r) = P * (1+r)^n + c * [(1+r_period)^N - 1] / r_period

    donde:
        P        = initial_capital_usd
        n        = horizon_years
        c        = periodic_contribution_usd
        r_period = (1+r)^contribution_frequency_years - 1
        N        = horizon_years / contribution_frequency_years

    Si r_period ≈ 0 (caso r = 0), la fórmula degenera a FV = P + c * N.

Supuestos de retorno alcanzable por perfil:
    Hardcodeados. En sprint posterior vendrán de CMA (Capital Market Assumptions).

Clasificación:
    gap = required_return - achievable_return
    gap <= -MARGINAL_BAND : VIABLE   (holgura suficiente)
    -MARGINAL_BAND < gap <= MARGINAL_BAND : MARGINAL
    gap > MARGINAL_BAND   : INVIABLE
    Error numérico        : UNDETERMINED
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from risk_first_advisory.config_layer.risk_assumptions import (
    get_default_achievable_returns,
)
from risk_first_advisory.kyc.models import FinancialGoal

# ── Constantes públicas ──────────────────────────────────────────────────────

DISCLAIMER = (
    "Los retornos futuros no están garantizados. "
    "Este análisis usa supuestos técnicos de mercado y no constituye predicción."
)

# Retornos anuales alcanzables estimados por perfil.
#
# Fase 1: estos valores se externalizan a `config/achievable_returns.yaml` y se
# cargan acá vía el loader auditable. La constante DEFAULT_ACHIEVABLE_RETURNS
# sigue existiendo y exportándose con la misma forma (`dict[profile, rate]`)
# para no romper consumidores que la importan directamente.
#
# Siguen siendo supuestos demo internos — no reemplazan un CMA productivo
# ni la decisión de un comité de inversiones.
DEFAULT_ACHIEVABLE_RETURNS: dict[str, float] = get_default_achievable_returns()

# ── Parámetros internos ──────────────────────────────────────────────────────

MARGINAL_BAND: float = 0.015  # ±1.5 pp definen la zona marginal
BISECTION_MAX_RATE: float = 5.0  # 500 % — techo absurdo; si no alcanza → UNDETERMINED
BISECTION_TOLERANCE: float = 1e-9
BISECTION_MAX_ITER: int = 200


# ── Modelos de output ────────────────────────────────────────────────────────


class FeasibilityStatus(str, Enum):
    VIABLE = "viable"
    MARGINAL = "marginal"
    INVIABLE = "inviable"
    UNDETERMINED = "undetermined"


@dataclass
class FeasibilityReport:
    """
    Resultado del análisis de viabilidad de un objetivo financiero.

    Campos:
        status                   : resultado de la evaluación.
        required_return_annual   : retorno anual necesario para alcanzar el objetivo.
                                   NaN si status = UNDETERMINED.
        achievable_return_annual : retorno estimado para el perfil aprobado.
        gap                      : required - achievable (negativo = cómodo).
                                   NaN si status = UNDETERMINED.
        reason                   : descripción legible del resultado.
        suggested_actions        : lista de acciones recomendadas (vacía si VIABLE).
        block_portfolio_generation: True solo si status = INVIABLE o UNDETERMINED.
        disclaimer               : texto de advertencia regulatoria.
    """

    status: FeasibilityStatus
    required_return_annual: float
    achievable_return_annual: float
    gap: float
    reason: str
    suggested_actions: list[str]
    block_portfolio_generation: bool
    disclaimer: str

    def to_dict(self) -> dict[str, Any]:
        """
        Serializa el reporte a dict JSON-serializable.

        Los valores NaN (caso UNDETERMINED) se convierten a None.
        """

        def _safe(v: float) -> float | None:
            return None if (isinstance(v, float) and math.isnan(v)) else v

        return {
            "status": self.status.value,
            "required_return_annual": _safe(self.required_return_annual),
            "achievable_return_annual": _safe(self.achievable_return_annual),
            "gap": _safe(self.gap),
            "reason": self.reason,
            "suggested_actions": list(self.suggested_actions),
            "block_portfolio_generation": self.block_portfolio_generation,
            "disclaimer": self.disclaimer,
        }


# ── Motor principal ──────────────────────────────────────────────────────────


class GoalFeasibilityEngine:
    """
    Evalúa la viabilidad de un FinancialGoal para un perfil de riesgo aprobado.

    INVARIANTE: no recibe KYCData. Solo opera con FinancialGoal + profile_name.
    """

    def __init__(
        self,
        achievable_returns: dict[str, float] | None = None,
    ) -> None:
        """
        Args:
            achievable_returns: supuestos de retorno por perfil. Si None, usa
                                DEFAULT_ACHIEVABLE_RETURNS.
        """
        self._achievable: dict[str, float] = (
            achievable_returns if achievable_returns is not None else DEFAULT_ACHIEVABLE_RETURNS
        )

    def evaluate(
        self,
        goal: FinancialGoal,
        approved_profile_name: str,
    ) -> FeasibilityReport:
        """
        Calcula el retorno requerido y emite un FeasibilityReport.

        Args:
            goal: objetivo financiero. Única fuente de verdad para el cálculo.
            approved_profile_name: nombre del perfil aprobado por el asesor.

        Returns:
            FeasibilityReport con status, retornos, gap, narrativa y disclaimer.

        Raises:
            ValueError: si approved_profile_name no está en el catálogo de perfiles.
        """
        if approved_profile_name not in self._achievable:
            raise ValueError(
                f"Perfil desconocido: {approved_profile_name!r}. "
                f"Perfiles válidos: {sorted(self._achievable)}."
            )

        achievable = self._achievable[approved_profile_name]

        # ── Calcular retorno requerido ──────────────────────────────────
        try:
            required = self._required_return(goal)
        except _ImpossibleGoalError:
            return FeasibilityReport(
                status=FeasibilityStatus.UNDETERMINED,
                required_return_annual=float("nan"),
                achievable_return_annual=achievable,
                gap=float("nan"),
                reason=(
                    "El objetivo financiero no es numéricamente alcanzable. "
                    "Verifique la coherencia entre capital inicial, objetivo y horizonte."
                ),
                suggested_actions=[
                    "Revisar la coherencia entre capital inicial, objetivo y horizonte.",
                    "Considerar reducir el objetivo o extender el horizonte.",
                ],
                block_portfolio_generation=True,
                disclaimer=DISCLAIMER,
            )

        # ── Clasificar según gap ────────────────────────────────────────
        gap = required - achievable

        if gap <= -MARGINAL_BAND:
            status = FeasibilityStatus.VIABLE
        elif gap <= MARGINAL_BAND:
            status = FeasibilityStatus.MARGINAL
        else:
            status = FeasibilityStatus.INVIABLE

        reason, actions, block = self._build_narrative(
            status, required, achievable, approved_profile_name
        )

        return FeasibilityReport(
            status=status,
            required_return_annual=required,
            achievable_return_annual=achievable,
            gap=gap,
            reason=reason,
            suggested_actions=actions,
            block_portfolio_generation=block,
            disclaimer=DISCLAIMER,
        )

    # ── Matemática ──────────────────────────────────────────────────────────

    @staticmethod
    def _future_value(rate: float, goal: FinancialGoal) -> float:
        """
        Valor futuro de capital + aportes a tasa anual `rate`.

        FV = P*(1+r)^n + c*[(1+r_period)^N - 1] / r_period

        Caso degenerado r = 0: FV = P + c * N (sin división por cero).
        """
        P = goal.initial_capital_usd
        n = goal.horizon_years
        c = goal.periodic_contribution_usd
        freq = goal.contribution_frequency_years

        fv_initial = P * (1.0 + rate) ** n

        if c == 0.0:
            return fv_initial

        n_periods = n / freq
        r_period = (1.0 + rate) ** freq - 1.0

        if abs(r_period) < 1e-12:
            # Caso r ≈ 0: suma simple de aportes
            fv_contributions = c * n_periods
        else:
            fv_contributions = c * ((1.0 + r_period) ** n_periods - 1.0) / r_period

        return fv_initial + fv_contributions

    def _required_return(self, goal: FinancialGoal) -> float:
        """
        Retorno anual r tal que FV(r) = target_capital_usd.

        Si FV(0) >= target → retorna 0.0.
        Si FV(BISECTION_MAX_RATE) < target → lanza _ImpossibleGoalError.
        """
        target = goal.target_capital_usd

        fv_at_zero = self._future_value(0.0, goal)
        if fv_at_zero >= target:
            return 0.0

        fv_at_max = self._future_value(BISECTION_MAX_RATE, goal)
        if fv_at_max < target:
            raise _ImpossibleGoalError(
                f"El objetivo ({target:,.0f}) no es alcanzable "
                f"incluso al {BISECTION_MAX_RATE:.0%} anual."
            )

        r_low, r_high = 0.0, BISECTION_MAX_RATE
        for _ in range(BISECTION_MAX_ITER):
            r_mid = (r_low + r_high) / 2.0
            if self._future_value(r_mid, goal) < target:
                r_low = r_mid
            else:
                r_high = r_mid
            if r_high - r_low < BISECTION_TOLERANCE:
                break

        return (r_low + r_high) / 2.0

    # ── Narrativa ────────────────────────────────────────────────────────────

    @staticmethod
    def _build_narrative(
        status: FeasibilityStatus,
        required: float,
        achievable: float,
        profile_name: str,
    ) -> tuple[str, list[str], bool]:
        """
        Construye (reason, suggested_actions, block_portfolio_generation).
        """
        req_pct = f"{required:.1%}"
        ach_pct = f"{achievable:.1%}"

        if status == FeasibilityStatus.VIABLE:
            reason = (
                f"El retorno requerido ({req_pct}) se encuentra dentro del rango "
                f"alcanzable para el perfil '{profile_name}' ({ach_pct}). "
                "El objetivo es financieramente viable con margen suficiente."
            )
            actions: list[str] = []
            block = False

        elif status == FeasibilityStatus.MARGINAL:
            reason = (
                f"El retorno requerido ({req_pct}) está próximo al límite estimado "
                f"para el perfil '{profile_name}' ({ach_pct}). "
                "El objetivo es alcanzable pero con escaso margen ante desvíos de mercado."
            )
            actions = [
                "Revisar el plan financiero para aumentar el margen de seguridad.",
                "Considerar incrementar los aportes periódicos.",
                "Evaluar si el horizonte de inversión puede extenderse.",
            ]
            block = False

        else:  # INVIABLE
            reason = (
                f"El retorno requerido ({req_pct}) supera el retorno alcanzable estimado "
                f"para el perfil '{profile_name}' ({ach_pct}). "
                "El objetivo no es viable con los parámetros actuales."
            )
            actions = [
                "Extender el horizonte de inversión.",
                "Reducir el capital objetivo.",
                "Aumentar los aportes periódicos.",
                (
                    "Revisar el perfil de riesgo solo si el asesor valida "
                    "que la tolerancia y capacidad reales del cliente lo permiten."
                ),
            ]
            block = True

        return reason, actions, block


# ── Excepción interna ────────────────────────────────────────────────────────


class _ImpossibleGoalError(Exception):
    """Objetivo no alcanzable numéricamente dentro del rango de bisección."""
