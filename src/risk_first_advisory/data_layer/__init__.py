"""Capa de datos de mercado.

En M1 contiene únicamente `MockMarketDataProvider`. En sprints posteriores
se agregarán CSVMarketDataProvider y BloombergMarketDataProvider, todos
implementando el mismo contrato.
"""

from risk_first_advisory.data_layer.market_data import (
    CRITICAL_FIELDS,
    MarketDataSnapshot,
    MockMarketDataProvider,
)

__all__ = [
    "CRITICAL_FIELDS",
    "MarketDataSnapshot",
    "MockMarketDataProvider",
]