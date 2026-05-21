"""
universe_layer — instrument universe model and providers.

Exports the main domain classes for convenient import:

    from risk_first_advisory.universe_layer import (
        AssetClass,
        CSVInstrumentUniverseProvider,
        FinancialInstrument,
        InstrumentExclusion,
        InstrumentType,
        InstrumentUniverse,
        PreferenceFilterEngine,
        PreferenceFilterResult,
    )
"""

from risk_first_advisory.universe_layer.csv_provider import (
    CSVInstrumentUniverseProvider,
)
from risk_first_advisory.universe_layer.instruments import (
    AssetClass,
    FinancialInstrument,
    InstrumentType,
    InstrumentUniverse,
)
from risk_first_advisory.universe_layer.preference_filter import (
    InstrumentExclusion,
    PreferenceFilterEngine,
    PreferenceFilterResult,
)

__all__ = [
    "AssetClass",
    "CSVInstrumentUniverseProvider",
    "FinancialInstrument",
    "InstrumentExclusion",
    "InstrumentType",
    "InstrumentUniverse",
    "PreferenceFilterEngine",
    "PreferenceFilterResult",
]
