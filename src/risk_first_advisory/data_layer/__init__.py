"""Capa de datos de mercado.

En M1 contiene `MockMarketDataProvider`, `DataQualityGate`, `ReturnEstimator`
y `CovarianceEngine`.
En sprints posteriores se agregarán CSVMarketDataProvider y
BloombergMarketDataProvider, todos implementando el mismo contrato de provider.
"""

from risk_first_advisory.data_layer.covariance import (
    CovarianceEngine,
    CovarianceMatrix,
)
from risk_first_advisory.data_layer.data_quality import (
    LOW_LIQUIDITY_THRESHOLD,
    REASON_CRITICAL_FIELD_MISSING,
    REASON_DATA_STALE,
    REASON_LOW_LIQUIDITY,
    REASON_NON_CRITICAL_FIELD_MISSING,
    REASON_ZERO_VOLATILITY_NON_CASH,
    DataQualityGate,
    DataQualityResult,
    DataQualityStatus,
)
from risk_first_advisory.data_layer.market_data import (
    CRITICAL_FIELDS,
    MarketDataSnapshot,
    MockMarketDataProvider,
)
from risk_first_advisory.data_layer.return_estimator import (
    RC_COST_EXPENSE_RATIO,
    RC_DATA_QUALITY_WARNING,
    RC_ESG_UNKNOWN,
    RC_RETURN_CLIPPED,
    ReturnEstimate,
    ReturnEstimator,
)

__all__ = [
    "CovarianceEngine",
    "CovarianceMatrix",
    "CRITICAL_FIELDS",
    "DataQualityGate",
    "DataQualityResult",
    "DataQualityStatus",
    "LOW_LIQUIDITY_THRESHOLD",
    "MarketDataSnapshot",
    "MockMarketDataProvider",
    "RC_COST_EXPENSE_RATIO",
    "RC_DATA_QUALITY_WARNING",
    "RC_ESG_UNKNOWN",
    "RC_RETURN_CLIPPED",
    "REASON_CRITICAL_FIELD_MISSING",
    "REASON_DATA_STALE",
    "REASON_LOW_LIQUIDITY",
    "REASON_NON_CRITICAL_FIELD_MISSING",
    "REASON_ZERO_VOLATILITY_NON_CASH",
    "ReturnEstimate",
    "ReturnEstimator",
]