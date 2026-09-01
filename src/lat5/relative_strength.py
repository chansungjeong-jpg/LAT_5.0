from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from lat5.data import drop_incomplete_trailing_session


def n_day_return(daily: pd.DataFrame, *, days: int) -> float | None:
    """Percent return of the latest completed close vs. the close `days`
    trading sessions earlier. None when there isn't enough history.

    Drops a trailing not-yet-traded placeholder session first (see
    `drop_incomplete_trailing_session`) -- otherwise "today" silently
    becomes yesterday's close carried forward with zero volume, which
    doesn't crash but quietly shifts the whole return window back a day.
    """
    daily = drop_incomplete_trailing_session(daily)
    close = daily["close"].astype(float)
    if len(close) < days + 1:
        return None
    return float(close.iloc[-1] / close.iloc[-1 - days] - 1.0)


def market_average_return(
    daily_frames: dict[str, pd.DataFrame], *, days: int
) -> float | None:
    """Equal-weighted average N-day return across every ticker with enough
    history -- a Watchlist-basket proxy for a market/sector index. Not the
    literal KOSPI/KOSDAQ index (no confirmed index-chart TR yet); swap in a
    real index series here once one is available.
    """
    returns = [
        value
        for daily in daily_frames.values()
        if (value := n_day_return(daily, days=days)) is not None
    ]
    if not returns:
        return None
    return sum(returns) / len(returns)


@dataclass(frozen=True)
class RelativeStrength:
    stock_return: float
    market_return: float
    rs: float


def relative_strength(
    daily: pd.DataFrame, market_return: float | None, *, days: int
) -> RelativeStrength | None:
    """RS = stock's N-day return minus the market-proxy's N-day return.
    Positive means the stock outperformed the proxy over the window --
    "stronger than the market" in the sense actually computable today.
    """
    if market_return is None:
        return None
    stock_return = n_day_return(daily, days=days)
    if stock_return is None:
        return None
    return RelativeStrength(
        stock_return=stock_return,
        market_return=market_return,
        rs=stock_return - market_return,
    )
