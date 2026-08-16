from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from lat5.patterns import confirmed_pivots


@dataclass(frozen=True)
class TrendlineMABreakout:
    breakout_pos: int
    low_points: tuple[int, int]
    trendline_previous: float
    trendline_current: float
    volume_ratio: float
    ema_crossed: tuple[str, ...]
    stop_reference: float


def _line(first_pos: int, first_value: float, second_pos: int, second_value: float, target: int) -> float:
    return first_value + (second_value - first_value) * (target - first_pos) / (second_pos - first_pos)


def find_trendline_ma_breakout(
    frame: pd.DataFrame,
    *,
    left: int = 1,
    right: int = 1,
    min_gap_bars: int = 3,
    volume_multiple: float = 1.5,
) -> TrendlineMABreakout | None:
    if len(frame) < 22 or min_gap_bars < 1 or volume_multiple <= 0:
        return None
    required = {"high", "low", "close", "volume", "ema60", "ema120"}
    if not required.issubset(frame.columns):
        return None
    pos = len(frame) - 1
    previous, current = frame.iloc[pos - 1], frame.iloc[pos]
    if any(pd.isna(current[name]) for name in ("close", "ema60", "ema120")):
        return None
    if any(pd.isna(previous[name]) for name in ("close", "ema60", "ema120")):
        return None
    pivots = confirmed_pivots(frame.iloc[:pos], left=left, right=right)
    lows = list(pivots.lows)
    if len(lows) < 2:
        return None
    first_pos, second_pos = lows[-2:]
    if second_pos - first_pos < min_gap_bars:
        return None
    first_low = float(frame.iloc[first_pos]["low"])
    second_low = float(frame.iloc[second_pos]["low"])
    if second_low <= first_low:
        return None
    line_previous = _line(first_pos, first_low, second_pos, second_low, pos - 1)
    line_current = _line(first_pos, first_low, second_pos, second_low, pos)
    if float(previous["close"]) > line_previous or float(current["close"]) <= line_current:
        return None
    crossed = tuple(
        name for name in ("ema60", "ema120")
        if float(previous["close"]) <= float(previous[name])
        and float(current["close"]) > float(current[name])
    )
    if float(current["close"]) <= float(current["ema60"]) or float(current["close"]) <= float(current["ema120"]):
        return None
    prior_volume = frame.iloc[pos - 20 : pos]["volume"].astype(float)
    mean_volume = float(prior_volume.mean())
    if mean_volume <= 0:
        return None
    volume_ratio = float(current["volume"]) / mean_volume
    if volume_ratio < volume_multiple:
        return None
    return TrendlineMABreakout(
        breakout_pos=pos,
        low_points=(first_pos, second_pos),
        trendline_previous=line_previous,
        trendline_current=line_current,
        volume_ratio=volume_ratio,
        ema_crossed=crossed,
        stop_reference=min(second_low, float(current["low"])),
    )
