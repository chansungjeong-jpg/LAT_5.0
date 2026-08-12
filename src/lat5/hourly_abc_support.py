from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from lat5.paper import size_position
from lat5.patterns import confirmed_pivots

if TYPE_CHECKING:
    from lat5.backtest import BacktestConfig


@dataclass(frozen=True)
class StrongHourlyBreakout:
    pos: int
    crossed: tuple[str, ...]
    volume_ratio: float
    body_atr_ratio: float


@dataclass(frozen=True)
class HourlyABCSupport:
    breakout_pos: int
    a_pos: int
    b_pos: int
    c_pos: int
    confirm_pos: int
    c_high: float
    c_low: float
    ma60: float


@dataclass(frozen=True)
class HourlyMA60Pullback:
    breakout_pos: int
    pullback_pos: int
    pullback_high: float
    pullback_low: float
    ma60: float


def strong_hourly_breakout_at(
    frame: pd.DataFrame,
    pos: int,
    *,
    distance_pct: float = 0.005,
    body_atr_multiple: float = 0.8,
    volume_multiple: float = 2.0,
    upper_close_fraction: float = 0.25,
) -> StrongHourlyBreakout | None:
    if pos < 20 or pos >= len(frame):
        return None
    previous = frame.iloc[pos - 1]
    current = frame.iloc[pos]
    required = ("open", "high", "low", "close", "volume", "ema60", "ema120", "atr20")
    if any(pd.isna(current[key]) for key in required):
        return None
    if any(pd.isna(previous[key]) for key in ("close", "ema60", "ema120")):
        return None

    close = float(current["close"])
    open_price = float(current["open"])
    high = float(current["high"])
    low = float(current["low"])
    if close <= open_price or close <= float(current["ema60"]) or close <= float(current["ema120"]):
        return None
    crossed = tuple(
        line
        for line in ("ema60", "ema120")
        if float(previous["close"]) <= float(previous[line])
        and close >= float(current[line]) * (1.0 + distance_pct)
    )
    if not crossed:
        return None

    atr20 = float(current["atr20"])
    candle_range = high - low
    if atr20 <= 0 or candle_range <= 0:
        return None
    body_atr_ratio = (close - open_price) / atr20
    if body_atr_ratio < body_atr_multiple:
        return None
    if (high - close) / candle_range > upper_close_fraction:
        return None

    mean_volume = float(frame.iloc[pos - 20 : pos]["volume"].astype(float).mean())
    if mean_volume <= 0:
        return None
    volume_ratio = float(current["volume"]) / mean_volume
    if volume_ratio < volume_multiple:
        return None
    return StrongHourlyBreakout(pos, crossed, volume_ratio, body_atr_ratio)


def find_hourly_abc_support(
    frame: pd.DataFrame,
    breakout_pos: int,
    *,
    ma60_tolerance_pct: float = 0.005,
) -> HourlyABCSupport | None:
    if breakout_pos < 0 or breakout_pos >= len(frame) - 3:
        return None
    search = frame.iloc[breakout_pos + 1 :]
    pivots = confirmed_pivots(search, left=1, right=1)
    lows = [breakout_pos + 1 + pos for pos in pivots.lows]
    highs = [breakout_pos + 1 + pos for pos in pivots.highs]
    if not lows:
        return None
    a_pos = lows[0]
    b_candidates = [pos for pos in highs if pos > a_pos]
    if not b_candidates:
        return None
    b_pos = b_candidates[0]
    c_candidates = [pos for pos in lows if pos > b_pos]
    if not c_candidates:
        return None
    c_pos = c_candidates[0]
    confirm_pos = c_pos + 1
    if confirm_pos >= len(frame):
        return None

    a_low = float(frame.iloc[a_pos]["low"])
    c_row = frame.iloc[c_pos]
    c_low = float(c_row["low"])
    c_close = float(c_row["close"])
    ma60 = float(c_row["ema60"])
    if ma60 <= 0 or c_low <= a_low or c_close <= ma60:
        return None
    if abs(c_low - ma60) / ma60 > ma60_tolerance_pct:
        return None
    return HourlyABCSupport(
        breakout_pos=breakout_pos,
        a_pos=a_pos,
        b_pos=b_pos,
        c_pos=c_pos,
        confirm_pos=confirm_pos,
        c_high=float(c_row["high"]),
        c_low=c_low,
        ma60=ma60,
    )


def find_hourly_ma60_pullback(
    frame: pd.DataFrame,
    breakout_pos: int,
    *,
    min_bars: int = 2,
    max_bars: int = 6,
    ma60_tolerance_pct: float = 0.01,
) -> HourlyMA60Pullback | None:
    if breakout_pos < 0 or breakout_pos >= len(frame):
        return None
    breakout_volume = float(frame.iloc[breakout_pos]["volume"])
    stop = min(len(frame), breakout_pos + max_bars + 1)
    for pos in range(breakout_pos + min_bars, stop):
        row = frame.iloc[pos]
        if any(pd.isna(row[key]) for key in ("high", "low", "close", "volume", "ema60")):
            continue
        ma60 = float(row["ema60"])
        low = float(row["low"])
        if ma60 <= 0 or abs(low - ma60) / ma60 > ma60_tolerance_pct:
            continue
        if float(row["close"]) <= ma60 or float(row["volume"]) >= breakout_volume:
            continue
        return HourlyMA60Pullback(
            breakout_pos=breakout_pos,
            pullback_pos=pos,
            pullback_high=float(row["high"]),
            pullback_low=low,
            ma60=ma60,
        )
    return None


def find_five_minute_c_high_entry(
    bars: pd.DataFrame,
    *,
    start_time: pd.Timestamp,
    c_high: float,
    c_low: float,
) -> tuple[int, int] | None:
    for pos in range(len(bars) - 1):
        if bars.index[pos] < start_time:
            continue
        close = float(bars.iloc[pos]["close"])
        if close < c_low:
            return None
        if close > c_high:
            return pos, pos + 1
    return None


def find_five_minute_reversal_entry(
    bars: pd.DataFrame,
    *,
    start_time: pd.Timestamp,
    pullback_low: float,
    volume_multiple: float = 1.5,
    lookback_high_bars: int = 3,
    entry_cutoff: str = "14:30",
) -> tuple[int, int] | None:
    first_pos = max(20, lookback_high_bars)
    cutoff = pd.Timestamp(entry_cutoff).time()
    for pos in range(first_pos, len(bars) - 1):
        timestamp = pd.Timestamp(bars.index[pos])
        if timestamp < start_time:
            continue
        row = bars.iloc[pos]
        close = float(row["close"])
        if close < pullback_low:
            return None
        prior_high = float(
            bars.iloc[pos - lookback_high_bars : pos]["high"].astype(float).max()
        )
        prior_volume = float(bars.iloc[pos - 20 : pos]["volume"].astype(float).mean())
        if prior_volume <= 0:
            continue
        if close <= float(row["open"]) or close <= prior_high:
            continue
        if float(row["volume"]) < prior_volume * volume_multiple:
            continue
        entry_pos = pos + 1
        entry_time = pd.Timestamp(bars.index[entry_pos])
        if entry_time.normalize() != timestamp.normalize() or entry_time.time() > cutoff:
            return None
        return pos, entry_pos
    return None


def simulate_pullback_reversal_trade(
    bars: pd.DataFrame,
    *,
    entry_pos: int,
    stop: float,
    equity: float,
    config: "BacktestConfig",
) -> dict[str, object] | None:
    if bars.empty or entry_pos < 0 or entry_pos >= len(bars) or stop <= 0:
        return None
    entry_time = pd.Timestamp(bars.index[entry_pos])
    entry_price = float(bars.iloc[entry_pos]["open"]) * (
        1.0 + config.slippage_bps / 10_000.0
    )
    risk = entry_price - stop
    if risk <= 0:
        return None
    quantity = size_position(
        equity,
        entry_price,
        stop,
        config.risk_fraction,
        config.max_exposure_fraction,
    )
    if quantity <= 0:
        return None

    one_r = entry_price + risk
    two_r = entry_price + 2.0 * risk
    partial_quantity = quantity // 2
    remaining = quantity
    partial_exit_price: float | None = None
    remaining_exit_price: float | None = None
    remaining_reason = "EOD"
    exit_events: list[dict[str, object]] = []
    sell_factor = 1.0 - config.slippage_bps / 10_000.0

    for pos in range(entry_pos, len(bars)):
        row = bars.iloc[pos]
        bar_open = float(row["open"])
        bar_high = float(row["high"])
        bar_low = float(row["low"])
        bar_close = float(row["close"])
        timestamp = pd.Timestamp(bars.index[pos])
        active_stop = entry_price if partial_exit_price is not None else stop

        if bar_open <= active_stop or bar_low <= active_stop:
            price = (bar_open if bar_open <= active_stop else active_stop) * sell_factor
            remaining_exit_price = price
            remaining_reason = "BREAKEVEN" if partial_exit_price is not None else "STOP"
            exit_events.append(
                {"time": timestamp, "price": price, "quantity": remaining,
                 "reason": remaining_reason}
            )
            remaining = 0
            break

        if partial_exit_price is None and partial_quantity > 0 and bar_high >= one_r:
            partial_exit_price = (bar_open if bar_open >= one_r else one_r) * sell_factor
            exit_events.append(
                {"time": timestamp, "price": partial_exit_price,
                 "quantity": partial_quantity, "reason": "PARTIAL_1R"}
            )
            remaining -= partial_quantity

        if remaining > 0 and bar_high >= two_r:
            remaining_exit_price = (bar_open if bar_open >= two_r else two_r) * sell_factor
            remaining_reason = "TARGET_2R"
            exit_events.append(
                {"time": timestamp, "price": remaining_exit_price,
                 "quantity": remaining, "reason": remaining_reason}
            )
            remaining = 0
            break

        ema20 = row.get("ema20_5m")
        if remaining > 0 and ema20 is not None and not pd.isna(ema20) and bar_close < float(ema20):
            remaining_exit_price = bar_close * sell_factor
            remaining_reason = "EMA20_EXIT"
            exit_events.append(
                {"time": timestamp, "price": remaining_exit_price,
                 "quantity": remaining, "reason": remaining_reason}
            )
            remaining = 0
            break

        if remaining > 0 and pos - entry_pos >= 11:
            best_high = float(bars.iloc[entry_pos : pos + 1]["high"].astype(float).max())
            if best_high < entry_price + 0.5 * risk:
                remaining_exit_price = bar_close * sell_factor
                remaining_reason = "TIME_60M"
                exit_events.append(
                    {"time": timestamp, "price": remaining_exit_price,
                     "quantity": remaining, "reason": remaining_reason}
                )
                remaining = 0
                break

    if remaining > 0:
        timestamp = pd.Timestamp(bars.index[-1])
        remaining_exit_price = float(bars.iloc[-1]["close"]) * sell_factor
        exit_events.append(
            {"time": timestamp, "price": remaining_exit_price,
             "quantity": remaining, "reason": "EOD"}
        )
        remaining = 0

    exit_notional = sum(
        float(event["price"]) * int(event["quantity"]) for event in exit_events
    )
    gross_pnl = sum(
        (float(event["price"]) - entry_price) * int(event["quantity"])
        for event in exit_events
    )
    fees = (entry_price * quantity + exit_notional) * config.commission_bps / 10_000.0
    tax = exit_notional * config.sell_tax_bps / 10_000.0
    weighted_exit = exit_notional / quantity
    exit_reason = (
        f"PARTIAL_1R+{remaining_reason}" if partial_exit_price is not None else remaining_reason
    )
    return {
        "entry_time": entry_time,
        "exit_time": exit_events[-1]["time"],
        "entry_price": entry_price,
        "exit_price": weighted_exit,
        "partial_exit_price": partial_exit_price,
        "remaining_exit_price": remaining_exit_price,
        "stop_price": stop,
        "target_price": two_r,
        "quantity": quantity,
        "rr_at_fill": 2.0,
        "exit_reason": exit_reason,
        "exit_fills": exit_events,
        "fees": fees,
        "tax": tax,
        "gross_pnl": gross_pnl,
        "net_pnl": gross_pnl - fees - tax,
    }
