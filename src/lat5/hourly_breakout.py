from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from lat5.paper import paper_exit_fill, size_position

if TYPE_CHECKING:
    from lat5.backtest import BacktestConfig


@dataclass(frozen=True)
class HourlyBreakoutSignal:
    pos: int
    crossed: tuple[str, ...]
    stop_reference: float
    volume_ratio: float


def hourly_or_breakout_at(
    frame: pd.DataFrame,
    pos: int,
    *,
    volume_multiple: float = 1.5,
) -> HourlyBreakoutSignal | None:
    if pos < 20 or pos >= len(frame) or volume_multiple <= 0:
        return None
    previous = frame.iloc[pos - 1]
    current = frame.iloc[pos]
    required = ("close", "low", "volume", "ema60", "ema120")
    if any(pd.isna(current[key]) for key in required):
        return None
    if any(pd.isna(previous[key]) for key in ("close", "ema60", "ema120")):
        return None

    current_close = float(current["close"])
    if current_close <= float(current["ema60"]) or current_close <= float(current["ema120"]):
        return None
    crossed = tuple(
        line
        for line in ("ema60", "ema120")
        if float(previous["close"]) <= float(previous[line])
        and current_close > float(current[line])
    )
    if not crossed:
        return None

    prior_volume = frame.iloc[pos - 20 : pos]["volume"].astype(float)
    mean_volume = float(prior_volume.mean())
    if mean_volume <= 0:
        return None
    volume_ratio = float(current["volume"]) / mean_volume
    if volume_ratio < volume_multiple:
        return None
    return HourlyBreakoutSignal(
        pos=pos,
        crossed=crossed,
        stop_reference=float(current["low"]),
        volume_ratio=volume_ratio,
    )


def simulate_hourly_breakout_trade(
    bars: pd.DataFrame,
    *,
    entry_pos: int,
    stop: float,
    equity: float,
    config: "BacktestConfig",
) -> dict[str, object] | None:
    if bars.empty or entry_pos < 0 or entry_pos >= len(bars) or stop <= 0:
        return None
    entry_open = float(bars.iloc[entry_pos]["open"])
    entry_price = entry_open * (1.0 + config.slippage_bps / 10_000.0)
    risk = entry_price - stop
    if risk <= 0:
        return None
    target = entry_price + 2.0 * risk
    quantity = size_position(
        equity,
        entry_price,
        stop,
        config.risk_fraction,
        config.max_exposure_fraction,
    )
    if quantity <= 0:
        return None

    exit_price: float | None = None
    exit_reason = "EOD"
    exit_pos = len(bars) - 1
    for pos in range(entry_pos, len(bars)):
        row = bars.iloc[pos]
        exit_fill = paper_exit_fill(
            stop,
            target,
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            config.slippage_bps,
        )
        if exit_fill is not None:
            exit_price, exit_reason = exit_fill
            exit_pos = pos
            break
    if exit_price is None:
        exit_price = float(bars.iloc[-1]["close"]) * (
            1.0 - config.slippage_bps / 10_000.0
        )

    entry_notional = entry_price * quantity
    exit_notional = exit_price * quantity
    fees = (entry_notional + exit_notional) * config.commission_bps / 10_000.0
    tax = exit_notional * config.sell_tax_bps / 10_000.0
    gross_pnl = (exit_price - entry_price) * quantity
    return {
        "entry_time": bars.index[entry_pos],
        "exit_time": bars.index[exit_pos],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_price": stop,
        "target_price": target,
        "quantity": quantity,
        "rr_at_fill": 2.0,
        "exit_reason": exit_reason,
        "fees": fees,
        "tax": tax,
        "gross_pnl": gross_pnl,
        "net_pnl": gross_pnl - fees - tax,
    }
