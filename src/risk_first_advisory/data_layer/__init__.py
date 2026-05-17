"""Capa de datos de mercado.

En M1 contiene `MockMarketDataProvider` y `DataQualityGate`. En sprints
posteriores se agregarán CSVMarketDataProvider y BloombergMarketDataProvider,
todos implementando el mismo contrato de provider.
"""

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

__all__ = [
    "CRITICAL_FIELDS",
    "DataQualityGate",
    "DataQualityResult",
    "DataQualityStatus",
    "LOW_LIQUIDITY_THRESHOLD",
    "MarketDataSnapshot",
    "MockMarketDataProvider",
    "REASON_CRITICAL_FIELD_MISSING",
    "REASON_DATA_STALE",
    "REASON_LOW_LIQUIDITY",
    "REASON_NON_CRITICAL_FIELD_MISSING",
    "REASON_ZERO_VOLATILITY_NON_CASH",
]