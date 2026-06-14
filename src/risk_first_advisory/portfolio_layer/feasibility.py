"""
PortfolioFeasibilityChecker — diagnóstico de factibilidad pre-optimizer.

INVARIANTE CENTRAL: el optimizador NO debe ser la primera capa que detecta
infactibilidad. Debe existir un diagnóstico previo, explicable y auditable,
que rechace problemas mal planteados antes de que SLSQP devuelva mensajes
crípticos como "Positive directional derivative for linesearch".

Esta capa NO resuelve la optimización del cliente: solo determina si el
problema es matemáticamente bien planteado. Si lo es, el optimizador podrá
buscar el óptimo; si no, se devuelven failed_checks legibles y
suggested_actions para que la capa humana decida cómo proceder (en la
arquitectura M1, ese es uno de los 4 caminos de infeasibility resolution).

Checks aplicados (en orden):
    A. PORTFOLIO_NO_ASSETS              — return_estimates vacío.
    B. PORTFOLIO_TICKER_MISMATCH        — tickers desalineados con cov matrix.
    C. PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW — N * cap < 1.0 → sum(w)=1 imposible.
    D. PORTFOLIO_MIN_VOL_EXCEEDS_BUDGET — vol mínima alcanzable > max_vol.
    E. PORTFOLIO_LOW_DIVERSIFICATION_UNIVERSE — asset_count < 3 (warning).
    F. PORTFOLIO_CONCENTRATION_REQUIRED — required cap > 0.25 (warning).

Política sobre cálculo de min vol:
    Se intenta resolver un problema MIN_VARIANCE auxiliar long-only con bounds
    [0, max_single_asset] y sum(w)=1, SIN la restricción de max_volatility.
    Si el solver falla, se devuelve None para min_achievable_volatility y se
    omite el check D (no se considera failed_check), pero se agrega un
    warning para que la auditoría refleje la incertidumbre.

Tolerancia numérica:
    Se admite hasta 1e-6 de holgura en N*cap >= 1 y en min_vol <= max_vol,
    para evitar falsos positivos por aritmética de punto flotante.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from scipy.optimize import minimize

from risk_first_advisory.data_layer.covariance import CovarianceMatrix
from risk_first_advisory.data_layer.return_estimator import ReturnEstimate
from risk_first_advisory.models.risk_budget import RiskBudget

# ─────────────────────────────────────────────────────────────────────────
# Códigos de check (failed_checks y warnings)
# ─────────────────────────────────────────────────────────────────────────

FC_NO_ASSETS = "PORTFOLIO_NO_ASSETS"
FC_TICKER_MISMATCH = "PORTFOLIO_TICKER_MISMATCH"
FC_MAX_SINGLE_ASSET_TOO_LOW = "PORTFOLIO_MAX_SINGLE_ASSET_TOO_LOW"
FC_MIN_VOL_EXCEEDS_BUDGET = "PORTFOLIO_MIN_VOL_EXCEEDS_BUDGET"

WARN_LOW_DIVERSIFICATION = "PORTFOLIO_LOW_DIVERSIFICATION_UNIVERSE"
WARN_CONCENTRATION_REQUIRED = "PORTFOLIO_CONCENTRATION_REQUIRED"
WARN_MIN_VOL_UNDETERMINED = "PORTFOLIO_MIN_VOL_UNDETERMINED"


# ─────────────────────────────────────────────────────────────────────────
# Constantes numéricas
# ─────────────────────────────────────────────────────────────────────────

CAP_FEASIBILITY_TOL = 1e-6
VOL_FEASIBILITY_TOL = 1e-6
LOW_DIVERSIFICATION_THRESHOLD = 3
HIGH_CONCENTRATION_THRESHOLD = 0.25


# ─────────────────────────────────────────────────────────────────────────
# Enum de estado
# ─────────────────────────────────────────────────────────────────────────


class PortfolioFeasibilityStatus(str, Enum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    WARNING = "warning"


# ─────────────────────────────────────────────────────────────────────────
# Resultado
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class PortfolioFeasibilityResult:
    """
    Resultado del diagnóstico de factibilidad.

    Campos:
        status                       : enum consolidado.
        is_feasible                  : True si status != INFEASIBLE.
        asset_count                  : número de activos en el universo.
        required_min_single_asset_cap: cap mínimo necesario para sum(w)=1
                                       (= 1.0 / asset_count si asset_count > 0).
                                       0.0 si asset_count == 0.
        actual_max_single_asset      : risk_budget.max_single_asset tal cual.
        min_achievable_volatility    : vol mínima estimada (None si no se
                                       pudo calcular).
        max_allowed_volatility       : risk_budget.max_volatility tal cual.
        failed_checks                : códigos de checks fallidos.
        warnings                     : códigos de warnings.
        suggested_actions            : acciones recomendadas para resolver.
        notes                        : notas libres de auditoría.
    """

    status: PortfolioFeasibilityStatus
    is_feasible: bool
    asset_count: int
    required_min_single_asset_cap: float
    actual_max_single_asset: float
    min_achievable_volatility: float | None
    max_allowed_volatility: float
    failed_checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.status, PortfolioFeasibilityStatus):
            raise ValueError(
                f"status debe ser PortfolioFeasibilityStatus. Recibido: "
                f"{type(self.status).__name__}."
            )
        if not isinstance(self.is_feasible, bool):
            raise ValueError(
                f"is_feasible debe ser bool. Recibido: "
                f"{type(self.is_feasible).__name__}."
            )
        if not isinstance(self.asset_count, int) or self.asset_count < 0:
            raise ValueError(
                f"asset_count debe ser int >= 0. Recibido: {self.asset_count}."
            )

        if not isinstance(self.required_min_single_asset_cap, (int, float)):
            raise ValueError(
                "required_min_single_asset_cap debe ser numérico. Recibido: "
                f"{type(self.required_min_single_asset_cap).__name__}."
            )
        if not 0.0 <= float(self.required_min_single_asset_cap) <= 1.0:
            raise ValueError(
                "required_min_single_asset_cap debe estar en [0.0, 1.0]. "
                f"Recibido: {self.required_min_single_asset_cap}."
            )

        if not isinstance(self.actual_max_single_asset, (int, float)):
            raise ValueError(
                "actual_max_single_asset debe ser numérico. Recibido: "
                f"{type(self.actual_max_single_asset).__name__}."
            )
        if not 0.0 <= float(self.actual_max_single_asset) <= 1.0:
            raise ValueError(
                "actual_max_single_asset debe estar en [0.0, 1.0]. "
                f"Recibido: {self.actual_max_single_asset}."
            )

        if self.min_achievable_volatility is not None:
            if not isinstance(self.min_achievable_volatility, (int, float)):
                raise ValueError(
                    "min_achievable_volatility debe ser numérico o None. "
                    f"Recibido: {type(self.min_achievable_volatility).__name__}."
                )
            if float(self.min_achievable_volatility) < 0.0:
                raise ValueError(
                    "min_achievable_volatility no puede ser negativo. "
                    f"Recibido: {self.min_achievable_volatility}."
                )

        if not isinstance(self.max_allowed_volatility, (int, float)):
            raise ValueError(
                "max_allowed_volatility debe ser numérico. Recibido: "
                f"{type(self.max_allowed_volatility).__name__}."
            )
        if float(self.max_allowed_volatility) < 0.0:
            raise ValueError(
                "max_allowed_volatility no puede ser negativo. "
                f"Recibido: {self.max_allowed_volatility}."
            )

        if not isinstance(self.failed_checks, list):
            raise ValueError("failed_checks debe ser una lista.")
        if not isinstance(self.warnings, list):
            raise ValueError("warnings debe ser una lista.")
        if not isinstance(self.suggested_actions, list):
            raise ValueError("suggested_actions debe ser una lista.")
        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    @property
    def has_failed_checks(self) -> bool:
        return len(self.failed_checks) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "is_feasible": self.is_feasible,
            "asset_count": self.asset_count,
            "required_min_single_asset_cap": self.required_min_single_asset_cap,
            "actual_max_single_asset": self.actual_max_single_asset,
            "min_achievable_volatility": self.min_achievable_volatility,
            "max_allowed_volatility": self.max_allowed_volatility,
            "failed_checks": list(self.failed_checks),
            "warnings": list(self.warnings),
            "suggested_actions": list(self.suggested_actions),
            "notes": list(self.notes),
        }


# ─────────────────────────────────────────────────────────────────────────
# Checker
# ─────────────────────────────────────────────────────────────────────────


class PortfolioFeasibilityChecker:
    """
    Diagnóstico de factibilidad pre-optimizer.

    No tiene estado. Una instancia puede reusarse para todos los chequeos
    de la sesión.

    `evaluate()` NO muta sus inputs. Retorna un PortfolioFeasibilityResult
    nuevo en cada llamada.
    """

    LOW_DIVERSIFICATION_THRESHOLD: int = LOW_DIVERSIFICATION_THRESHOLD
    HIGH_CONCENTRATION_THRESHOLD: float = HIGH_CONCENTRATION_THRESHOLD

    def evaluate(
        self,
        return_estimates: list[ReturnEstimate],
        covariance_matrix: CovarianceMatrix,
        risk_budget: RiskBudget,
    ) -> PortfolioFeasibilityResult:
        # ── Validación de tipos ───────────────────────────────────────
        if not isinstance(covariance_matrix, CovarianceMatrix):
            raise ValueError(
                "covariance_matrix debe ser CovarianceMatrix. Recibido: "
                f"{type(covariance_matrix).__name__}."
            )
        if not isinstance(risk_budget, RiskBudget):
            raise ValueError(
                "risk_budget debe ser RiskBudget. Recibido: "
                f"{type(risk_budget).__name__}."
            )

        failed_checks: list[str] = []
        warnings: list[str] = []
        suggested_actions: list[str] = []
        notes: list[str] = []

        asset_count = len(return_estimates)
        actual_max_single = float(risk_budget.max_single_asset)
        max_vol = float(risk_budget.max_volatility)

        # ── Check A: universo vacío ───────────────────────────────────
        if asset_count == 0:
            failed_checks.append(FC_NO_ASSETS)
            suggested_actions.append(
                "Ampliar universo elegible o revisar filtros previos."
            )
            return PortfolioFeasibilityResult(
                status=PortfolioFeasibilityStatus.INFEASIBLE,
                is_feasible=False,
                asset_count=0,
                required_min_single_asset_cap=0.0,
                actual_max_single_asset=actual_max_single,
                min_achievable_volatility=None,
                max_allowed_volatility=max_vol,
                failed_checks=failed_checks,
                warnings=warnings,
                suggested_actions=suggested_actions,
                notes=[
                    "return_estimates está vacío; no hay activos para "
                    "construir cartera."
                ],
            )

        required_cap = 1.0 / asset_count

        # ── Check B: tickers desalineados ─────────────────────────────
        est_tickers = [e.ticker for e in return_estimates]
        cov_tickers = list(covariance_matrix.tickers)
        if est_tickers != cov_tickers:
            failed_checks.append(FC_TICKER_MISMATCH)
            suggested_actions.append(
                "Alinear el orden de tickers entre return_estimates y "
                "covariance_matrix antes de evaluar factibilidad."
            )
            notes.append(
                f"return_estimates tickers: {est_tickers}; "
                f"covariance_matrix tickers: {cov_tickers}."
            )
            # No seguimos con C/D porque cualquier cálculo de vol sobre
            # tickers desalineados sería ruido. Devolvemos ahora.
            return PortfolioFeasibilityResult(
                status=PortfolioFeasibilityStatus.INFEASIBLE,
                is_feasible=False,
                asset_count=asset_count,
                required_min_single_asset_cap=required_cap,
                actual_max_single_asset=actual_max_single,
                min_achievable_volatility=None,
                max_allowed_volatility=max_vol,
                failed_checks=failed_checks,
                warnings=warnings,
                suggested_actions=suggested_actions,
                notes=notes,
            )

        # ── Check C: max_single_asset insuficiente ────────────────────
        # N * cap >= 1.0 (con tolerancia numérica) para que sum(w)=1 sea
        # alcanzable bajo bounds [0, cap].
        if asset_count * actual_max_single < 1.0 - CAP_FEASIBILITY_TOL:
            failed_checks.append(FC_MAX_SINGLE_ASSET_TOO_LOW)
            suggested_actions.append(
                "Aumentar max_single_asset, ampliar universo o permitir "
                "posición residual en cash."
            )
            notes.append(
                f"N * max_single_asset = {asset_count} * "
                f"{actual_max_single:.6f} = "
                f"{asset_count * actual_max_single:.6f} < 1.0. "
                f"Se requiere cap mínimo de {required_cap:.6f}."
            )

        # ── Check D: volatilidad mínima alcanzable ────────────────────
        # Solo lo intentamos si C no falló, porque con bounds infactibles
        # el solver no devuelve nada útil.
        min_vol: float | None = None
        if FC_MAX_SINGLE_ASSET_TOO_LOW not in failed_checks:
            min_vol = self._compute_min_achievable_volatility(
                covariance=covariance_matrix.covariance,
                max_single_asset=actual_max_single,
            )

            if min_vol is None:
                warnings.append(WARN_MIN_VOL_UNDETERMINED)
                notes.append(
                    "min_achievable_volatility no pudo calcularse "
                    "(solver auxiliar falló). El check de techo de vol no "
                    "se aplica; auditoría queda registrada."
                )
            elif min_vol > max_vol + VOL_FEASIBILITY_TOL:
                failed_checks.append(FC_MIN_VOL_EXCEEDS_BUDGET)
                suggested_actions.append(
                    "Ampliar universo defensivo, aumentar cash-like assets "
                    "o revisar max_volatility con el asesor."
                )
                notes.append(
                    f"min_achievable_volatility ≈ {min_vol:.6f} > "
                    f"max_volatility = {max_vol:.6f}."
                )

        # ── Check E: universo chico (solo si no infeasible aún) ──────
        if not failed_checks and asset_count < self.LOW_DIVERSIFICATION_THRESHOLD:
            warnings.append(WARN_LOW_DIVERSIFICATION)
            suggested_actions.append(
                "Ampliar el universo a >= 3 instrumentos para mejorar "
                "diversificación."
            )

        # ── Check F: concentración alta requerida (solo si no infeas.) ─
        if not failed_checks and required_cap > self.HIGH_CONCENTRATION_THRESHOLD:
            warnings.append(WARN_CONCENTRATION_REQUIRED)
            suggested_actions.append(
                "Ampliar universo para reducir la concentración mínima "
                "obligatoria por activo."
            )

        # ── Status final ──────────────────────────────────────────────
        if failed_checks:
            status = PortfolioFeasibilityStatus.INFEASIBLE
            is_feasible = False
        elif warnings:
            status = PortfolioFeasibilityStatus.WARNING
            is_feasible = True
        else:
            status = PortfolioFeasibilityStatus.FEASIBLE
            is_feasible = True

        return PortfolioFeasibilityResult(
            status=status,
            is_feasible=is_feasible,
            asset_count=asset_count,
            required_min_single_asset_cap=required_cap,
            actual_max_single_asset=actual_max_single,
            min_achievable_volatility=min_vol,
            max_allowed_volatility=max_vol,
            failed_checks=failed_checks,
            warnings=warnings,
            suggested_actions=suggested_actions,
            notes=notes,
        )

    # ── Cálculo auxiliar de min vol ───────────────────────────────────────

    @staticmethod
    def _compute_min_achievable_volatility(
        covariance: list[list[float]],
        max_single_asset: float,
    ) -> float | None:
        """
        Resuelve un MIN_VARIANCE auxiliar long-only con bounds [0, cap]
        y sum(w)=1. SIN restricción de max_volatility, porque el objetivo
        es JUSTAMENTE descubrir si el universo puede bajar de ese piso.

        Devuelve la volatilidad anualizada (raíz de la varianza óptima)
        o None si el solver falla.
        """
        Sigma = np.array(covariance, dtype=float)
        n = Sigma.shape[0]
        if n == 0:
            return None

        # Si el cap es infeasible (N*cap < 1), el solver no encontrará
        # solución factible. El caller debe haberlo filtrado antes.
        if n * max_single_asset < 1.0 - CAP_FEASIBILITY_TOL:
            return None

        bounds = [(0.0, float(max_single_asset))] * n
        constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w)) - 1.0}]

        def obj(w: np.ndarray) -> float:
            return float(w @ Sigma @ w)

        def grad(w: np.ndarray) -> np.ndarray:
            return 2.0 * (Sigma @ w)

        w0 = np.full(n, 1.0 / n)

        try:
            result = minimize(
                obj,
                w0,
                jac=grad,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-12, "maxiter": 2000},
            )
        except Exception:  # pragma: no cover — defensive
            return None

        if not result.success:
            return None

        variance = float(result.fun)
        if variance < 0.0:
            # Defensa contra ruido numérico
            variance = 0.0
        return math.sqrt(variance)
