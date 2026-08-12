from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class MarketLeaderInput:
    ticker: str
    name: str
    market: str
    sector: str
    trading_value: float
    rise_rate: float


@dataclass(frozen=True)
class MarketLeader:
    ticker: str
    name: str
    market: str
    sector: str
    trading_value: float
    rise_rate: float
    trading_value_rank: int
    rise_rate_rank: int
    leader_score: float


def _rank_desc(values: list[MarketLeaderInput], attribute: str) -> dict[str, int]:
    ordered = sorted(
        values,
        key=lambda item: (-float(getattr(item, attribute)), item.ticker),
    )
    return {item.ticker: position for position, item in enumerate(ordered, start=1)}


def _percentile_score(rank: int, count: int) -> float:
    if count <= 1:
        return 100.0
    return 100.0 * (count - rank) / (count - 1)


def rank_market_leaders(
    rows: Iterable[MarketLeaderInput],
) -> list[MarketLeader]:
    """Rank positive-rising symbols separately within KOSPI and KOSDAQ.

    Leader Score is 60% trading-value rank and 40% rise-rate rank. The input
    is deliberately pure: market-wide collection and Watchlist persistence
    belong to the application/storage layers.
    """
    grouped: dict[str, list[MarketLeaderInput]] = {}
    for item in rows:
        if item.market not in {"KOSPI", "KOSDAQ"}:
            continue
        if not all(
            isfinite(float(value))
            for value in (item.trading_value, item.rise_rate)
        ):
            continue
        if float(item.trading_value) <= 0 or float(item.rise_rate) <= 0:
            continue
        grouped.setdefault(item.market, []).append(item)

    ranked: list[MarketLeader] = []
    for market in sorted(grouped):
        market_rows = grouped[market]
        trading_ranks = _rank_desc(market_rows, "trading_value")
        rise_ranks = _rank_desc(market_rows, "rise_rate")
        count = len(market_rows)
        for item in market_rows:
            trading_rank = trading_ranks[item.ticker]
            rise_rank = rise_ranks[item.ticker]
            score = (
                _percentile_score(trading_rank, count) * 0.60
                + _percentile_score(rise_rank, count) * 0.40
            )
            ranked.append(
                MarketLeader(
                    ticker=item.ticker,
                    name=item.name,
                    market=item.market,
                    sector=item.sector,
                    trading_value=float(item.trading_value),
                    rise_rate=float(item.rise_rate),
                    trading_value_rank=trading_rank,
                    rise_rate_rank=rise_rank,
                    leader_score=score,
                )
            )

    return sorted(
        ranked,
        key=lambda item: (-item.leader_score, item.market, item.ticker),
    )
