"""
PortfolioOptimizer — optimizador long-only usando scipy.optimize.

Regla central: recibe instrumentos ya filtrados y datos ya validados.
No decide suitability, governance, ESG ni data quality.

Objetivos soportados:
    MIN_VARIANCE  : minimizar w.T @ Σ @ w
    MAX_RETURN    : maximizar retorno esperado s.t. vol <= max_volatility
    MAX_UTILITY   : maximizar μ.T @ w - λ * w.T @ Σ @ w  (λ=3.0)

Implementación:
    Usa scipy.optimize.minimize con SLSQP (soporta QP convexo con bounds
    y restricciones de igualdad/desigualdad). Equivalente a cvxpy para este
    tipo de problema. Si el proyecto ya tiene cvxpy disponible, se puede
    migrar sin cambiar la interfaz.
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

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WEIGHT_CLEANUP_THRESHOLD: float = 1e-6
UTILITY_LAMBDA: float = 3.0
FEASIBILITY_TOL: float = 1e-4


# ---------------------------------------------------------------------------
# Enum de objetivo
# ---------------------------------------------------------------------------

class OptimizationObjective(Enum):
    MIN_VARIANCE = "MIN_VARIANCE"
    MAX_RETURN = "MAX_RETURN"
    MAX_UTILITY = "MAX_UTILITY"


# ---------------------------------------------------------------------------
# OptimizationInput
# ---------------------------------------------------------------------------

@dataclass
class OptimizationInput:
    """
    Datos de entrada para el optimizador.

    Invariante: return_estimates y covariance_matrix deben estar alineados
    (mismo orden de tickers).
    """

    return_estimates: list[ReturnEstimate]
    covariance_matrix: CovarianceMatrix
    risk_budget: RiskBudget
    objective: OptimizationObjective
    max_assets: int | None = None
    min_weight: float = 0.0
    max_weight: float | None = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.return_estimates:
            raise ValueError("return_estimates no puede estar vacío.")

        est_tickers = [e.ticker for e in self.return_estimates]
        cov_tickers = self.covariance_matrix.tickers
        if est_tickers != cov_tickers:
            raise ValueError(
                f"Los tickers de return_estimates {est_tickers} no coinciden "
                f"con los de covariance_matrix {cov_tickers} (orden incluido)."
            )

        if not isinstance(self.risk_budget, RiskBudget):
            raise ValueError(
                f"risk_budget debe ser RiskBudget. "
                f"Recibido: {type(self.risk_budget).__name__}."
            )

        if not isinstance(self.objective, OptimizationObjective):
            raise ValueError(
                f"objective debe ser OptimizationObjective. "
                f"Recibido: {type(self.objective).__name__}."
            )

        if self.max_assets is not None and self.max_assets <= 0:
            raise ValueError(
                f"max_assets debe ser None o > 0. Recibido: {self.max_assets}."
            )

        if not 0.0 <= self.min_weight <= 1.0:
            raise ValueError(
                f"min_weight debe estar entre 0 y 1. Recibido: {self.min_weight}."
            )

        if self.max_weight is not None:
            if not 0.0 <= self.max_weight <= 1.0:
                raise ValueError(
                    f"max_weight debe ser None o estar entre 0 y 1. "
                    f"Recibido: {self.max_weight}."
                )
            if self.max_weight < self.min_weight:
                raise ValueError(
                    f"max_weight ({self.max_weight}) debe ser >= "
                    f"min_weight ({self.min_weight})."
                )

        if not isinstance(self.notes, list):
            raise ValueError("notes debe ser una lista.")


# ---------------------------------------------------------------------------
# OptimizedPortfolio
# ---------------------------------------------------------------------------

@dataclass
class OptimizedPortfolio:
    """Resultado del optimizador: cartera candidata con métricas."""

    objective: OptimizationObjective
    weights: dict[str, float]
    expected_return_annual: float
    volatility_annual: float
    risk_score: float
    constraints_satisfied: bool
    reason_codes: list[str]
    notes: list[str] = field(default_factory=list)

    @property
    def invested_weight(self) -> float:
        return sum(self.weights.values())

    @property
    def number_of_assets(self) -> int:
        return sum(1 for w in self.weights.values() if w > 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective.value,
            "weights": dict(self.weights),
            "expected_return_annual": self.expected_return_annual,
            "volatility_annual": self.volatility_annual,
            "risk_score": self.risk_score,
            "constraints_satisfied": self.constraints_satisfied,
            "reason_codes": list(self.reason_codes),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# PortfolioOptimizer
# ---------------------------------------------------------------------------

class PortfolioOptimizer:
    """
    Optimizador de portfolios long-only usando scipy.optimize (SLSQP).

    No decide qué instrumentos incluir: solo optimiza sobre lo que recibe.
    """

    def optimize(self, input_data: OptimizationInput) -> OptimizedPortfolio:
        """
        Construye cartera óptima según el objetivo especificado.

        Raises:
            ValueError: si no existe solución factible dado el problema.
        """
        n = len(input_data.return_estimates)
        tickers = [e.ticker for e in input_data.return_estimates]
        mu = np.array(
            [e.adjusted_expected_return_annual for e in input_data.return_estimates],
            dtype=float,
        )
        Sigma = np.array(input_data.covariance_matrix.covariance, dtype=float)
        rb = input_data.risk_budget
        max_vol = rb.max_volatility

        # Bounds: [0, upper] per asset
        upper = rb.max_single_asset
        if input_data.max_weight is not None:
            upper = min(upper, input_data.max_weight)
        bounds = [(0.0, upper)] * n

        # Constraints
        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {"type": "ineq", "fun": lambda w: max_vol ** 2 - float(w @ Sigma @ w)},
        ]

        # Objective + gradient
        if input_data.objective == OptimizationObjective.MIN_VARIANCE:
            def obj(w): return float(w @ Sigma @ w)
            def grad(w): return 2.0 * (Sigma @ w)

        elif input_data.objective == OptimizationObjective.MAX_RETURN:
            def obj(w): return -float(mu @ w)
            def grad(w): return -mu

        else:  # MAX_UTILITY
            lam = UTILITY_LAMBDA
            def obj(w): return -(float(mu @ w) - lam * float(w @ Sigma @ w))
            def grad(w): return -(mu - 2.0 * lam * (Sigma @ w))

        w0 = np.full(n, 1.0 / n)

        result = minimize(
            obj,
            w0,
            jac=grad,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"ftol": 1e-10, "maxiter": 2000},
        )

        if not result.success:
            raise ValueError(
                f"No existe solución factible para el problema de optimización. "
                f"Mensaje del solver: {result.message!r}. "
                f"Verificar restricciones: max_single_asset={rb.max_single_asset}, "
                f"max_volatility={rb.max_volatility}."
            )

        raw_weights = np.array(result.x, dtype=float)
        raw_weights[raw_weights < WEIGHT_CLEANUP_THRESHOLD] = 0.0

        total = raw_weights.sum()
        if total < WEIGHT_CLEANUP_THRESHOLD:
            raise ValueError(
                "La solución del optimizador colapsó a pesos nulos tras la limpieza."
            )
        raw_weights = raw_weights / total

        weights_dict = {t: float(raw_weights[i]) for i, t in enumerate(tickers)}

        expected_return = float(mu @ raw_weights)
        variance = float(raw_weights @ Sigma @ raw_weights)
        volatility = math.sqrt(max(variance, 0.0))
        risk_score = volatility / max_vol if max_vol > 0 else 0.0

        sum_ok = abs(raw_weights.sum() - 1.0) < FEASIBILITY_TOL
        nonneg_ok = bool(np.all(raw_weights >= -FEASIBILITY_TOL))
        vol_ok = volatility <= max_vol + FEASIBILITY_TOL
        constraints_satisfied = sum_ok and nonneg_ok and vol_ok

        reason_codes: list[str] = []
        if not sum_ok:
            reason_codes.append("WEIGHTS_DO_NOT_SUM_TO_ONE")
        if not nonneg_ok:
            reason_codes.append("NEGATIVE_WEIGHT_DETECTED")
        if not vol_ok:
            reason_codes.append("VOLATILITY_EXCEEDS_MAX")

        notes = [
            f"Objective: {input_data.objective.value}",
            f"Assets: {n}",
            "Solver: SLSQP (scipy.optimize)",
        ]
        if input_data.min_weight > 0:
            notes.append(
                f"min_weight={input_data.min_weight} especificado; "
                "en M1 se aplica como límite inferior pasivo. "
                "Para selección binaria usar versión futura con variables mixtas."
            )

        return OptimizedPortfolio(
            objective=input_data.objective,
            weights=weights_dict,
            expected_return_annual=expected_return,
            volatility_annual=volatility,
            risk_score=risk_score,
            constraints_satisfied=constraints_satisfied,
            reason_codes=reason_codes,
            notes=notes,
        )
