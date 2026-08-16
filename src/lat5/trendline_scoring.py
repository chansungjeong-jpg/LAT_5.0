from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from lat5.trendline_breakout import TrendlineMABreakout


@dataclass(frozen=True)
class TrendlineScore:
    total_score: int
    components: dict[str, int]
    hard_blocks: tuple[str, ...]
    evidence: dict[str, float | int | str]


def _bounded(value: float, low: float, high: float, points: int) -> int:
    if value <= low:
        return 0
    if value >= high:
        return points
    return int(round((value - low) / (high - low) * points))


def score_trendline_candidate(
    frame: pd.DataFrame,
    signal: TrendlineMABreakout,
    *,
    weekly_above: bool,
    monthly_above: bool,
) -> TrendlineScore:
    pos = signal.breakout_pos
    row = frame.iloc[pos]
    close = float(row["close"])
    atr = float(row.get("atr14", 0) or 0)
    if atr <= 0:
        atr = max(float(row["high"]) - float(row["low"]), close * 0.01)
    low_first = float(frame.iloc[signal.low_points[0]]["low"])
    low_second = float(frame.iloc[signal.low_points[1]]["low"])
    higher_low_pct = (low_second / low_first - 1.0) * 100.0
    breakout_margin_atr = (close - signal.trendline_current) / atr
    trendline_points = _bounded(higher_low_pct, 0.0, 8.0, 10) + _bounded(
        breakout_margin_atr, 0.0, 2.0, 10
    )

    ema60 = float(row["ema60"])
    ema120 = float(row["ema120"])
    ema_gap_pct = (ema60 / ema120 - 1.0) * 100.0 if ema120 else 0.0
    ema_points = (10 if signal.ema_crossed else 5) + _bounded(ema_gap_pct, 0.0, 5.0, 10)
    volume_points = 10 + _bounded(signal.volume_ratio, 1.5, 3.0, 10)

    distance_pct = (close / ema60 - 1.0) * 100.0 if ema60 else 999.0
    distance_points = max(0, 15 - int(max(distance_pct - 1.0, 0.0) * 5))
    supply_high = float(frame.iloc[max(0, pos - 40) : pos]["high"].max())
    supply_room_pct = (supply_high / close - 1.0) * 100.0 if close else 0.0
    supply_points = _bounded(supply_room_pct, 2.0, 8.0, 15)
    htf_points = (5 if weekly_above else 0) + (5 if monthly_above else 0)

    blocks: list[str] = []
    if distance_pct > 5.0:
        blocks.append("OVEREXTENDED_FROM_EMA60")
    if supply_room_pct < 2.0:
        blocks.append("SUPPLY_TOO_CLOSE")
    components = {
        "trendline": min(20, trendline_points),
        "moving_average": min(20, ema_points),
        "volume": min(20, volume_points),
        "distance": min(15, distance_points),
        "supply_room": min(15, supply_points),
        "higher_timeframe": min(10, htf_points),
    }
    return TrendlineScore(
        total_score=sum(components.values()),
        components=components,
        hard_blocks=tuple(blocks),
        evidence={
            "close": close,
            "ema60": ema60,
            "ema120": ema120,
            "ema_gap_pct": ema_gap_pct,
            "distance_from_ema60_pct": distance_pct,
            "volume_ratio": signal.volume_ratio,
            "supply_room_pct": supply_room_pct,
            "breakout_margin_atr": breakout_margin_atr,
        },
    )
