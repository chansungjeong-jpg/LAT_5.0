from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Mapping

import pandas as pd

from lat5.us_featured import USFeaturedInput
from lat5.us_mapping import mappings_for


def featured_inputs_from_daily(
    history: Mapping[str, pd.DataFrame], *, as_of: date
) -> tuple[USFeaturedInput, ...]:
    """Create featured-stock inputs from completed daily bars only."""
    result: list[USFeaturedInput] = []
    for symbol, frame in history.items():
        if mappings_for(symbol) is None:
            continue
        if not {"Close", "Volume"} <= set(frame.columns):
            continue
        daily = frame.loc[pd.to_datetime(frame.index).date <= as_of, ["Close", "Volume"]].dropna()
        if len(daily) < 3:
            continue
        previous_close = float(daily.iloc[-2]["Close"])
        close = float(daily.iloc[-1]["Close"])
        baseline_volume = float(daily.iloc[-3:-1]["Volume"].mean())
        volume = float(daily.iloc[-1]["Volume"])
        if previous_close <= 0 or baseline_volume <= 0:
            continue
        change_pct = (close / previous_close) - 1.0
        volume_ratio = volume / baseline_volume
        trading_value = close * volume
        if not all(isfinite(value) for value in (change_pct, volume_ratio, trading_value)):
            continue
        result.append(USFeaturedInput(symbol, change_pct, volume_ratio, trading_value))
    return tuple(result)
