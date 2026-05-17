"""Capa B — reglas deterministas. Sin IA, sin datos de mercado."""

from risk_first_advisory.rules_layer.product_governance import (
    ApprovedProductUniverse,
    ProductGovernanceRecord,
    ProductGovernanceStatus,
    is_watchlist,
)
from risk_first_advisory.rules_layer.risk_budget_builder import (
    PROFILE_BASE_PARAMS,
    VALID_PROFILES,
    RiskBudgetBuilder,
)

__all__ = [
    "ApprovedProductUniverse",
    "PROFILE_BASE_PARAMS",
    "ProductGovernanceRecord",
    "ProductGovernanceStatus",
    "RiskBudgetBuilder",
    "VALID_PROFILES",
    "is_watchlist",
]