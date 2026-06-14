"""Capa de optimización de portfolios.

En M1 contiene PortfolioOptimizer con objetivos MIN_VARIANCE, MAX_RETURN y
MAX_UTILITY. En sprints posteriores se agregará PortfolioGenerationCoordinator
para generar múltiples carteras candidatas.
"""
"""Capa C — portfolios.

Contiene optimizador, coordinador de generación y compuerta de factibilidad
pre-optimizer.
"""
from risk_first_advisory.portfolio_layer.feasibility import (
    FC_MAX_SINGLE_ASSET_TOO_LOW,
    FC_MIN_VOL_EXCEEDS_BUDGET,
    FC_NO_ASSETS,
    FC_TICKER_MISMATCH,
    HIGH_CONCENTRATION_THRESHOLD,
    LOW_DIVERSIFICATION_THRESHOLD,
    WARN_CONCENTRATION_REQUIRED,
    WARN_LOW_DIVERSIFICATION,
    WARN_MIN_VOL_UNDETERMINED,
    PortfolioFeasibilityChecker,
    PortfolioFeasibilityResult,
    PortfolioFeasibilityStatus,
)
from risk_first_advisory.portfolio_layer.generation import (
    RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET,
    RC_VARIANT_INFEASIBLE,
    PortfolioCandidateSet,
    PortfolioGenerationCoordinator,
    PortfolioVariant,
    PortfolioVariantMetadata,
)
from risk_first_advisory.portfolio_layer.optimizer import (
    UTILITY_LAMBDA,
    WEIGHT_CLEANUP_THRESHOLD,
    OptimizationInput,
    OptimizationObjective,
    OptimizedPortfolio,
    PortfolioOptimizer,
)

__all__ = [
    "FC_MAX_SINGLE_ASSET_TOO_LOW",
    "FC_MIN_VOL_EXCEEDS_BUDGET",
    "FC_NO_ASSETS",
    "FC_TICKER_MISMATCH",
    "HIGH_CONCENTRATION_THRESHOLD",
    "LOW_DIVERSIFICATION_THRESHOLD",
    "OptimizationInput",
    "OptimizationObjective",
    "OptimizedPortfolio",
    "PortfolioCandidateSet",
    "PortfolioFeasibilityChecker",
    "PortfolioFeasibilityResult",
    "PortfolioFeasibilityStatus",
    "PortfolioGenerationCoordinator",
    "PortfolioOptimizer",
    "PortfolioVariant",
    "PortfolioVariantMetadata",
    "RC_GROWTH_EXCEEDS_APPROVED_RISK_BUDGET",
    "RC_VARIANT_INFEASIBLE",
    "WARN_CONCENTRATION_REQUIRED",
    "WARN_LOW_DIVERSIFICATION",
    "WARN_MIN_VOL_UNDETERMINED",
    "UTILITY_LAMBDA",
    "WEIGHT_CLEANUP_THRESHOLD",
]
