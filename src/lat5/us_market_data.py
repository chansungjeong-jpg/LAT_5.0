from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Iterable

import pandas as pd

from lat5.us_market_flow import USMarketObservation
from lat5.us_market_flow import aggregate_company_flows, evaluate_market_gate


class YFinanceDailyProvider:
    """Network boundary for delayed daily US market data.

    The downloader is injectable so parsing and freshness remain testable
    without network access. Production code can pass ``yfinance.download``.
    """

    def __init__(self, downloader: Callable):
        self.downloader = downloader

    def fetch(
        self,
        symbols: Iterable[str],
        *,
        as_of: date,
        lookback_days: int = 14,
    ) -> list[USMarketObservation]:
        requested = tuple(dict.fromkeys(symbols))
        if not requested:
            return []
        tables = self.downloader(
            requested,
            as_of - timedelta(days=lookback_days),
            as_of + timedelta(days=1),
        )
        observations: list[USMarketObservation] = []
        for symbol in requested:
            frame = tables.get(symbol)
            if frame is None or not isinstance(frame, pd.DataFrame):
                raise ValueError(f"missing history: {symbol}")
            if "Close" not in frame.columns:
                raise ValueError(f"Close column missing: {symbol}")
            clean = frame[["Close"]].dropna()
            if len(clean) < 2:
                raise ValueError(f"insufficient Close history: {symbol}")
            previous = float(clean.iloc[-2]["Close"])
            close = float(clean.iloc[-1]["Close"])
            latest_date = pd.Timestamp(clean.index[-1]).date()
            observations.append(
                USMarketObservation(symbol, latest_date, previous, close, as_of)
            )
        return observations


def collect_us_context(provider, store, run_id: int, *, as_of: date, symbols: Iterable[str]):
    observations = provider.fetch(symbols, as_of=as_of)
    market_gate = evaluate_market_gate(observations, as_of=as_of)
    company_flows = aggregate_company_flows(observations)
    store.save_us_observations(run_id, observations)
    store.save_us_market_gate(run_id, as_of, market_gate)
    store.save_us_company_flows(run_id, as_of, company_flows.values())

    class USContextResult:
        def __init__(self, gate, flows):
            self.market_gate = gate
            self.company_flows = flows

    return USContextResult(market_gate, company_flows)
