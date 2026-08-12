from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class USReferenceMapping:
    symbol: str
    name: str
    flow: str
    kr_tickers: tuple[str, ...]


US10Y_MARKET_INDICATOR = USReferenceMapping(
    symbol="US10Y",
    name="US 10-Year Treasury Yield",
    flow="US_MARKET_FLOW",
    kr_tickers=(),
)


_MAPPINGS: tuple[USReferenceMapping, ...] = (
    USReferenceMapping("MU", "Micron Technology", "US_AI_FLOW", ("000660",)),
    USReferenceMapping("STX", "Seagate Technology", "US_AI_FLOW", ("005930",)),
    USReferenceMapping("NVDA", "NVIDIA", "US_AI_FLOW", ("000660", "005930", "042700")),
    USReferenceMapping("MSFT", "Microsoft", "US_AI_FLOW", ("035420", "035720", "018260")),
    USReferenceMapping("AMZN", "Amazon", "US_AI_FLOW", ("035420", "035720", "018260")),
    USReferenceMapping("RUN", "Sunrun", "US_SOLAR_FLOW", ("009830",)),
    USReferenceMapping("FSLR", "First Solar", "US_SOLAR_FLOW", ("009830",)),
    USReferenceMapping("VRT", "Vertiv", "US_POWER_EQUIPMENT_FLOW", ("010120", "267260", "298040")),
    USReferenceMapping("ETN", "Eaton", "US_POWER_EQUIPMENT_FLOW", ("010120", "267260")),
    USReferenceMapping("GEV", "GE Vernova", "US_POWER_EQUIPMENT_FLOW", ("012450", "267260", "298040")),
    USReferenceMapping("LMT", "Lockheed Martin", "US_DEFENSE_FLOW", ("012450", "079550", "047810")),
    USReferenceMapping("RTX", "RTX", "US_DEFENSE_FLOW", ("012450", "079550", "047810")),
    USReferenceMapping("LLY", "Eli Lilly", "US_BIOTECH_FLOW", ("207940", "068270", "326030")),
    USReferenceMapping("VRTX", "Vertex Pharmaceuticals", "US_BIOTECH_FLOW", ("207940", "068270", "326030")),
    USReferenceMapping("TSLA", "Tesla", "US_BATTERY_FLOW", ("373220", "006400", "096770")),
    USReferenceMapping("ALB", "Albemarle", "US_BATTERY_FLOW", ("373220", "006400", "096770")),
    USReferenceMapping("FLNC", "Fluence Energy", "US_BATTERY_FLOW", ("373220", "006400", "010120")),
)


def mapping_registry() -> tuple[USReferenceMapping, ...]:
    return _MAPPINGS


def mappings_for(symbol: str) -> USReferenceMapping | None:
    normalized = symbol.strip().upper()
    return next((item for item in _MAPPINGS if item.symbol == normalized), None)
