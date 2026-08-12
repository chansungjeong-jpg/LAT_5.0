from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Iterable

from lat5.us_mapping import mappings_for


@dataclass(frozen=True)
class USMarketObservation:
    symbol: str
    as_of: date
    previous_close: float
    close: float
    collected_on: date

    @property
    def change_pct(self) -> float:
        if self.previous_close == 0:
            raise ValueError(f"previous close is zero: {self.symbol}")
        return (self.close / self.previous_close) - 1.0


@dataclass(frozen=True)
class MarketGateRules:
    max_age_days: int = 2
    min_positive_indices: int = 3
    risk_off_us10y_change_pct: float = 0.015
    risk_off_vix_change_pct: float = 0.10


@dataclass(frozen=True)
class MarketGateDecision:
    state: str
    flow: str
    us10y_symbol: str
    positive_indices: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CompanyFlowDecision:
    flow: str
    direction: str
    mean_change_pct: float
    symbols: tuple[str, ...]


_MARKET_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA", "VIX", "US10Y")
_INDEX_SYMBOLS = ("SPY", "QQQ", "IWM", "DIA")


def _index(observations: Iterable[USMarketObservation]) -> dict[str, USMarketObservation]:
    result: dict[str, USMarketObservation] = {}
    for observation in observations:
        if observation.symbol in _MARKET_SYMBOLS:
            result[observation.symbol] = observation
    return result


def evaluate_market_gate(
    observations: Iterable[USMarketObservation],
    *,
    as_of: date,
    rules: MarketGateRules = MarketGateRules(),
) -> MarketGateDecision:
    values = _index(observations)
    missing = [symbol for symbol in _MARKET_SYMBOLS if symbol not in values]
    stale = [
        symbol for symbol, observation in values.items()
        if (as_of - observation.as_of).days > rules.max_age_days
        or (as_of - observation.collected_on).days > rules.max_age_days
    ]
    if missing or stale:
        return MarketGateDecision(
            "UNKNOWN", "US_MARKET_FLOW", "US10Y", 0,
            ("STALE_OR_MISSING_US_CONTEXT",),
        )

    changes = {symbol: values[symbol].change_pct for symbol in _MARKET_SYMBOLS}
    if not all(isfinite(value) for value in changes.values()):
        return MarketGateDecision(
            "UNKNOWN", "US_MARKET_FLOW", "US10Y", 0,
            ("INVALID_US_CONTEXT",),
        )

    positive_indices = sum(changes[symbol] > 0 for symbol in _INDEX_SYMBOLS)
    risk_off = (
        changes["US10Y"] >= rules.risk_off_us10y_change_pct
        and changes["VIX"] >= rules.risk_off_vix_change_pct
    )
    if risk_off:
        state = "RISK_OFF"
        reasons = ("US10Y_AND_VIX_RISK_OFF",)
    elif positive_indices >= rules.min_positive_indices:
        state = "BUY"
        reasons = ()
    else:
        state = "SELECTIVE_BUY"
        reasons = ("INDEX_BREADTH_SELECTIVE",)

    return MarketGateDecision(state, "US_MARKET_FLOW", "US10Y", positive_indices, reasons)


def aggregate_company_flows(
    observations: Iterable[USMarketObservation],
) -> dict[str, CompanyFlowDecision]:
    grouped: dict[str, list[tuple[str, float]]] = {}
    for observation in observations:
        mapping = mappings_for(observation.symbol)
        if mapping is None or mapping.flow == "US_MARKET_FLOW":
            continue
        grouped.setdefault(mapping.flow, []).append(
            (observation.symbol, observation.change_pct)
        )

    result: dict[str, CompanyFlowDecision] = {}
    for flow, rows in grouped.items():
        mean_change = sum(change for _, change in rows) / len(rows)
        direction = "POSITIVE" if mean_change > 0 else "NEGATIVE" if mean_change < 0 else "NEUTRAL"
        result[flow] = CompanyFlowDecision(
            flow, direction, mean_change, tuple(symbol for symbol, _ in rows)
        )
    return result
