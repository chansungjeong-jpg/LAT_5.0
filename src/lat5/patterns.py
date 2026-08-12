from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Pivots:
    highs: tuple[int, ...]
    lows: tuple[int, ...]


@dataclass(frozen=True)
class Channel:
    upper: float
    lower: float
    position: float
    high_points: tuple[int, int]
    low_points: tuple[int, int]


@dataclass(frozen=True)
class ABCSetup:
    anchor_pos: int
    a_pos: int
    p_pos: int
    b_pos: int
    c_pos: int
    entry: float
    stop: float
    expires_pos: int

    @property
    def risk_per_share(self) -> float:
        return self.entry - self.stop


def confirmed_pivots(frame: pd.DataFrame, left: int = 2, right: int = 2) -> Pivots:
    highs: list[int] = []
    lows: list[int] = []
    high_values = frame["high"].astype(float).to_numpy()
    low_values = frame["low"].astype(float).to_numpy()

    for pos in range(left, len(frame) - right):
        high_neighbors = [*high_values[pos - left : pos], *high_values[pos + 1 : pos + right + 1]]
        low_neighbors = [*low_values[pos - left : pos], *low_values[pos + 1 : pos + right + 1]]
        if all(high_values[pos] > value for value in high_neighbors):
            highs.append(pos)
        if all(low_values[pos] < value for value in low_neighbors):
            lows.append(pos)
    return Pivots(tuple(highs), tuple(lows))


def _project_line(first_pos: int, first_value: float, second_pos: int, second_value: float, target: int) -> float:
    slope = (second_value - first_value) / (second_pos - first_pos)
    return first_value + slope * (target - first_pos)


def build_rising_channel(frame: pd.DataFrame, lookback: int = 40) -> Channel | None:
    if len(frame) < 6:
        return None
    start = max(0, len(frame) - lookback)
    window = frame.iloc[start:]
    pivots = confirmed_pivots(window, left=2, right=2)
    if len(pivots.highs) < 2 or len(pivots.lows) < 2:
        return None

    high_local = pivots.highs[-2:]
    low_local = pivots.lows[-2:]
    high_values = tuple(float(window.iloc[pos]["high"]) for pos in high_local)
    low_values = tuple(float(window.iloc[pos]["low"]) for pos in low_local)
    if high_values[1] <= high_values[0] or low_values[1] <= low_values[0]:
        return None

    target_local = len(window) - 1
    upper = _project_line(high_local[0], high_values[0], high_local[1], high_values[1], target_local)
    lower = _project_line(low_local[0], low_values[0], low_local[1], low_values[1], target_local)
    if upper <= lower:
        return None

    price = float(window.iloc[-1]["close"])
    position = (price - lower) / (upper - lower)
    return Channel(
        upper=upper,
        lower=lower,
        position=position,
        high_points=(high_local[0] + start, high_local[1] + start),
        low_points=(low_local[0] + start, low_local[1] + start),
    )


def is_anchor(frame: pd.DataFrame, pos: int) -> bool:
    if pos < 20 or pos >= len(frame):
        return False
    row = frame.iloc[pos]
    prior_amount = frame.iloc[pos - 20 : pos]["amount"].astype(float)
    candle_range = float(row["high"] - row["low"])
    if candle_range <= 0 or float(row["open"]) <= 0:
        return False
    amount_ok = float(row["amount"]) >= float(prior_amount.mean()) * 2.0
    return_ok = float(row["close"] / row["open"] - 1.0) >= 0.015
    upper_close_ok = float(row["high"] - row["close"]) / candle_range <= 0.40
    return amount_ok and return_ok and upper_close_ok


def find_abc(
    frame: pd.DataFrame, anchor_pos: int, tick_size: float, max_bars: int = 36
) -> ABCSetup | None:
    if anchor_pos < 0 or anchor_pos >= len(frame) or tick_size <= 0:
        return None
    stop_pos = min(len(frame), anchor_pos + max_bars + 1)
    search = frame.iloc[anchor_pos:stop_pos]
    pivots = confirmed_pivots(search, left=1, right=1)
    highs = [anchor_pos + pos for pos in pivots.highs if pos > 0]
    lows = [anchor_pos + pos for pos in pivots.lows if pos > 0]
    if not highs:
        return None

    a_pos = highs[0]
    p_candidates = [pos for pos in lows if pos > a_pos]
    if not p_candidates:
        return None
    p_pos = p_candidates[0]
    b_candidates = [pos for pos in highs if pos > p_pos]
    if not b_candidates:
        return None
    b_pos = b_candidates[0]
    c_candidates = [pos for pos in lows if pos > b_pos]
    if not c_candidates:
        return None
    c_pos = c_candidates[0]

    anchor = frame.iloc[anchor_pos]
    a_high = float(frame.iloc[a_pos]["high"])
    p_low = float(frame.iloc[p_pos]["low"])
    b_high = float(frame.iloc[b_pos]["high"])
    c_low = float(frame.iloc[c_pos]["low"])
    advance = a_high - float(anchor["low"])
    first_pullback = a_high - p_low
    if advance <= 0 or first_pullback <= 0:
        return None
    if a_high <= float(anchor["high"]) or p_low < float(anchor["low"]):
        return None
    if first_pullback / advance > 0.60:
        return None
    if (b_high - p_low) / first_pullback < 0.50:
        return None
    if c_low <= p_low:
        return None

    entry = b_high + tick_size
    stop = c_low - tick_size
    if stop <= 0 or entry <= stop:
        return None
    return ABCSetup(
        anchor_pos=anchor_pos,
        a_pos=a_pos,
        p_pos=p_pos,
        b_pos=b_pos,
        c_pos=c_pos,
        entry=entry,
        stop=stop,
        expires_pos=min(c_pos + 3, anchor_pos + max_bars),
    )
