"""Capa de optimización de portfolios.

En M1 contiene PortfolioOptimizer con objetivos MIN_VARIANCE, MAX_RETURN y
MAX_UTILITY. En sprints posteriores se agregará PortfolioGenerationCoordinator
para generar múltiples carteras candidatas.
"""

from risk_first_advisory.portfolio_layer.optimizer import (
    UTILITY_LAMBDA,
    WEIGHT_CLEANUP_THRESHOLD,
    OptimizationInput,
    OptimizationObjective,
    OptimizedPortfolio,
    PortfolioOptimizer,
)

__all__ = [
    "OptimizationInput",
    "OptimizationObjective",
    "OptimizedPortfolio",
    "PortfolioOptimizer",
    "UTILITY_LAMBDA",
    "WEIGHT_CLEANUP_THRESHOLD",
]