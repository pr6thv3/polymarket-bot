"""Read-only, reproducible cross-venue research primitives.

This package is intentionally isolated from the bot runtime.  It must never
import execution clients, strategy classes, portfolios, or order management.
"""

from research.mapping import ContractMapping, MappingCatalog
from research.quotes import FeeRule, OutcomeQuote, PairedSnapshot, VenueSnapshot
from research.transport import ReadOnlyTransport, UnsafeResearchRequest

__all__ = [
    "ContractMapping",
    "FeeRule",
    "MappingCatalog",
    "OutcomeQuote",
    "PairedSnapshot",
    "ReadOnlyTransport",
    "UnsafeResearchRequest",
    "VenueSnapshot",
]
