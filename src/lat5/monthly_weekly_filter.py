from __future__ import annotations

import pandas as pd

from lat5.data import aggregate_weekly


def aggregate_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return daily.copy()
    return (
        daily.sort_index()
        .resample("ME", label="right", closed="right")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["close"])
    )


def completed_periods(
    daily: pd.DataFrame, as_of: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return periods_as_of(daily, as_of, include_in_progress=False)


def periods_as_of(
    daily: pd.DataFrame, as_of: pd.Timestamp, *, include_in_progress: bool
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = daily.loc[daily.index <= as_of].sort_index()
    weekly = aggregate_weekly(daily)
    monthly = aggregate_monthly(daily)
    if not include_in_progress:
        weekly = weekly.loc[weekly.index <= as_of]
        month_end = as_of.to_period("M").start_time - pd.Timedelta(days=1)
        monthly = monthly.loc[monthly.index <= month_end]
    return weekly, monthly


def crossed_recovery(periods: pd.DataFrame, window: int) -> bool:
    if periods.empty or len(periods) < window + 1:
        return False
    close = periods["close"].astype(float)
    ma = close.rolling(window, min_periods=window).mean()
    previous_close, current_close = close.iloc[-2], close.iloc[-1]
    previous_ma, current_ma = ma.iloc[-2], ma.iloc[-1]
    if pd.isna(previous_ma) or pd.isna(current_ma):
        return False
    return bool(previous_close < previous_ma and current_close >= current_ma)


def recent_recovery(periods: pd.DataFrame, window: int, *, lookback: int = 3) -> bool:
    if periods.empty or len(periods) < window + 1 or lookback < 1:
        return False
    close = periods["close"].astype(float)
    ma = close.rolling(window, min_periods=window).mean()
    start = max(1, len(periods) - lookback - 1)
    for pos in range(start, len(periods)):
        if pd.isna(ma.iloc[pos - 1]) or pd.isna(ma.iloc[pos]):
            continue
        if close.iloc[pos - 1] < ma.iloc[pos - 1] and close.iloc[pos] >= ma.iloc[pos]:
            return bool(close.iloc[-1] >= ma.iloc[-1])
    return False


def recovery_details(periods: pd.DataFrame, window: int) -> dict[str, object] | None:
    if periods.empty or len(periods) < window + 1:
        return None
    close = periods["close"].astype(float)
    ma = close.rolling(window, min_periods=window).mean()
    candidates = []
    for pos in range(1, len(periods)):
        if pd.isna(ma.iloc[pos - 1]) or pd.isna(ma.iloc[pos]):
            continue
        if close.iloc[pos - 1] < ma.iloc[pos - 1] and close.iloc[pos] >= ma.iloc[pos]:
            candidates.append(pos)
    if not candidates or close.iloc[-1] < ma.iloc[-1]:
        return None
    pos = candidates[-1]
    return {
        "previous_period": str(periods.index[pos - 1].date()),
        "current_period": str(periods.index[pos].date()),
        "previous_close": float(close.iloc[pos - 1]),
        "previous_ma": float(ma.iloc[pos - 1]),
        "current_close": float(close.iloc[pos]),
        "current_ma": float(ma.iloc[pos]),
    }
