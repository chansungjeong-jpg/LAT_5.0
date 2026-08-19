from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from math import inf
from pathlib import Path
from typing import Iterable

import pandas as pd

from lat5.data import WatchItem, aggregate_60m, daily_ema_context
from lat5.location_decision import LocationScoreConfig, build_context, evaluate_watchlist_position
from lat5.paper import PaperLedger, paper_entry_fill, paper_exit_fill, size_position
from lat5.patterns import ABCSetup, build_rising_channel, find_abc, is_anchor
from lat5.scoring import daily_trend
from lat5.hourly_breakout import hourly_or_breakout_at, simulate_hourly_breakout_trade
from lat5.hourly_abc_support import (
    find_five_minute_reversal_entry,
    find_five_minute_c_high_entry,
    find_hourly_abc_support,
    find_hourly_ma60_pullback,
    simulate_pullback_reversal_trade,
    strong_hourly_breakout_at,
)


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000_000.0
    risk_fraction: float = 0.005
    max_exposure_fraction: float = 0.20
    commission_bps: float = 1.5
    sell_tax_bps: float = 20.0
    slippage_bps: float = 5.0
    min_rr: float = 1.5


def _location_ledger_evidence(location: dict[str, object] | None) -> dict[str, object]:
    if location is None:
        return {}
    daily_ma_reaction = location.get("daily_ma_reaction")
    rr_breakdown = location.get("rr_breakdown")
    return {
        "location_state": location["state"],
        "location_entry_eligible": location.get("entry_eligible") is True,
        "location_score": location["location_score"],
        "location_vetoes": location.get("vetoes", []),
        "location_unknown_fields": location.get("unknown_fields", []),
        "daily_ma_reaction": daily_ma_reaction,
        "rr_breakdown": rr_breakdown,
        "location_daily_ma_reaction": daily_ma_reaction,
        "location_rr_breakdown": rr_breakdown,
    }


def infer_tick_size(bars: pd.DataFrame) -> float | None:
    values: list[float] = []
    for column in ("open", "high", "low", "close"):
        values.extend(float(value) for value in bars[column].dropna())
    unique = sorted(set(values))
    differences = [right - left for left, right in zip(unique, unique[1:]) if right > left]
    return min(differences) if differences else None


def simulate_fixed_trade(
    bars: pd.DataFrame,
    setup: ABCSetup,
    tick_size: float,
    channel_upper: float,
    equity: float,
    config: BacktestConfig,
    entry_start_pos: int,
    entry_end_pos: int,
) -> dict[str, object] | None:
    if bars.empty or entry_start_pos < 0 or entry_start_pos >= len(bars):
        return None
    limit = setup.entry + 2 * tick_size
    fill_price: float | None = None
    fill_pos: int | None = None
    for pos in range(entry_start_pos, min(entry_end_pos, len(bars) - 1) + 1):
        row = bars.iloc[pos]
        fill_price = paper_entry_fill(
            setup.entry,
            limit,
            float(row["open"]),
            float(row["high"]),
            config.slippage_bps,
        )
        if fill_price is not None:
            fill_pos = pos
            break
    if fill_price is None or fill_pos is None:
        return None

    risk = fill_price - setup.stop
    if risk <= 0:
        return None
    target = min(channel_upper, fill_price + 2.0 * risk)
    rr = (target - fill_price) / risk
    if rr < config.min_rr:
        return None
    quantity = size_position(
        equity,
        fill_price,
        setup.stop,
        config.risk_fraction,
        config.max_exposure_fraction,
    )
    if quantity <= 0:
        return None

    exit_price: float | None = None
    exit_reason = "EOD"
    exit_pos = len(bars) - 1
    for pos in range(fill_pos, len(bars)):
        row = bars.iloc[pos]
        exit_fill = paper_exit_fill(
            setup.stop,
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
        exit_price = float(bars.iloc[-1]["close"]) * (1.0 - config.slippage_bps / 10_000.0)

    entry_notional = fill_price * quantity
    exit_notional = exit_price * quantity
    fees = (entry_notional + exit_notional) * config.commission_bps / 10_000.0
    tax = exit_notional * config.sell_tax_bps / 10_000.0
    gross_pnl = (exit_price - fill_price) * quantity
    return {
        "entry_time": bars.index[fill_pos],
        "exit_time": bars.index[exit_pos],
        "entry_price": fill_price,
        "exit_price": exit_price,
        "stop_price": setup.stop,
        "target_price": target,
        "quantity": quantity,
        "rr_at_fill": rr,
        "exit_reason": exit_reason,
        "fees": fees,
        "tax": tax,
        "gross_pnl": gross_pnl,
        "net_pnl": gross_pnl - fees - tax,
    }


def run_technical_baseline(
    store,
    watch_items: Iterable[WatchItem],
    output_db: str | Path,
    config: BacktestConfig,
    start: str | None = None,
    end: str | None = None,
    max_symbols: int | None = None,
) -> tuple[pd.DataFrame, dict[str, float | int], dict[str, object]]:
    unique_items: list[WatchItem] = []
    seen_tickers: set[str] = set()
    for item in watch_items:
        if item.ticker not in seen_tickers:
            unique_items.append(item)
            seen_tickers.add(item.ticker)
    if max_symbols is not None:
        unique_items = unique_items[:max_symbols]

    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    trades: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    minute_covered = 0
    daily_covered = 0
    anchor_count = 0
    abc_count = 0

    with PaperLedger(output_db) as ledger:
        for item in unique_items:
            daily = store.load_daily(item.ticker)
            minutes = store.load_minutes(item.ticker)
            if not daily.empty:
                daily_covered += 1
            if minutes.empty:
                reason_counts["MINUTE_DATA_MISSING"] += 1
                continue
            minute_covered += 1
            if daily.empty or len(daily) < 20:
                reason_counts["DAILY_DATA_MISSING"] += 1
                continue

            minutes = minutes.sort_index().copy()
            if "amount" not in minutes:
                minutes["amount"] = minutes["close"].astype(float) * minutes["volume"].astype(float)
            tick_size = infer_tick_size(minutes)
            if tick_size is None:
                reason_counts["TICK_SIZE_UNKNOWN"] += 1
                continue

            daily_context = daily_ema_context(daily)
            hourly = aggregate_60m(minutes)
            if hourly.empty:
                reason_counts["HOUR_DATA_MISSING"] += 1
                continue
            hourly["ema60"] = hourly["close"].astype(float).ewm(
                span=60, adjust=False, min_periods=60
            ).mean()
            hourly["ema120"] = hourly["close"].astype(float).ewm(
                span=120, adjust=False, min_periods=120
            ).mean()

            for day_value, day_bars in minutes.groupby(minutes.index.normalize()):
                day_ts = pd.Timestamp(day_value)
                if start_ts is not None and day_ts < start_ts:
                    continue
                if end_ts is not None and day_ts > end_ts:
                    continue
                day_bars = day_bars.sort_index()
                if len(day_bars) < 28 or day_ts not in daily_context.index:
                    continue
                ema_row = daily_context.loc[day_ts]
                if pd.isna(ema_row["ema10"]) or pd.isna(ema_row["ema20"]):
                    continue

                for anchor_pos in range(20, len(day_bars) - 7):
                    if not is_anchor(day_bars, anchor_pos):
                        continue
                    anchor_count += 1
                    setup = find_abc(day_bars, anchor_pos, tick_size)
                    if setup is None:
                        reason = "ABC_INVALID"
                        ledger.record_decision(
                            str(day_bars.index[anchor_pos]), item.ticker, item.sector,
                            "REJECT", reason, "lat5-technical-fixed", "0.1.0",
                            {"anchor_pos": anchor_pos},
                        )
                        reason_counts[reason] += 1
                        continue
                    abc_count += 1
                    confirm_pos = setup.c_pos + 1
                    entry_start = setup.c_pos + 2
                    entry_end = min(setup.expires_pos, len(day_bars) - 1)
                    if entry_start > entry_end or confirm_pos >= len(day_bars):
                        reason_counts["ABC_EXPIRED"] += 1
                        continue

                    signal_time = day_bars.index[confirm_pos]
                    signal_price = float(day_bars.iloc[confirm_pos]["close"])
                    state = daily_trend(
                        signal_price, float(ema_row["ema10"]), float(ema_row["ema20"])
                    )
                    completed_hourly = hourly.loc[hourly.index + pd.Timedelta(hours=1) <= signal_time]
                    decision = "WATCH"
                    reason = "HOUR_CONTEXT_UNKNOWN"
                    channel = None

                    if state == "REJECT":
                        decision, reason = "REJECT", "DAILY_TREND_REJECT"
                    elif len(completed_hourly) >= 120:
                        hour_row = completed_hourly.iloc[-1]
                        if pd.isna(hour_row["ema60"]) or pd.isna(hour_row["ema120"]):
                            reason = "HOUR_EMA_UNKNOWN"
                        elif not (
                            float(hour_row["close"]) >= float(hour_row["ema60"])
                            and float(hour_row["ema60"]) >= float(hour_row["ema120"])
                        ):
                            decision, reason = "REJECT", "HOUR_TREND_REJECT"
                        else:
                            channel = build_rising_channel(completed_hourly)
                            if channel is None:
                                reason = "CHANNEL_UNKNOWN"
                            else:
                                position = (signal_price - channel.lower) / (channel.upper - channel.lower)
                                if position < 0:
                                    decision, reason = "REJECT", "CHANNEL_BREAKDOWN"
                                elif position >= 0.90:
                                    reason = "CHANNEL_TOO_HIGH"
                                else:
                                    trade = simulate_fixed_trade(
                                        day_bars,
                                        setup,
                                        tick_size,
                                        channel.upper,
                                        config.initial_capital,
                                        config,
                                        entry_start,
                                        entry_end,
                                    )
                                    if trade is not None:
                                        decision, reason = "BUY", "ABC_BREAKOUT"
                                        trade.update(
                                            ticker=item.ticker,
                                            name=item.name,
                                            sector=item.sector,
                                            strategy_id="lat5-technical-fixed",
                                            algorithm_version="0.1.0",
                                        )
                                        trades.append(trade)
                                    else:
                                        reason = "NO_FILL_OR_RR_LOW"

                    inputs = {
                        "daily_state": state,
                        "entry": setup.entry,
                        "stop": setup.stop,
                        "tick_size": tick_size,
                        "channel_lower": channel.lower if channel else None,
                        "channel_upper": channel.upper if channel else None,
                    }
                    decision_id = ledger.record_decision(
                        str(signal_time), item.ticker, item.sector, decision, reason,
                        "lat5-technical-fixed", "0.1.0", inputs,
                    )
                    reason_counts[reason] += 1

                    if decision == "BUY":
                        trade = trades[-1]
                        order_id = ledger.create_order(
                            decision_id,
                            setup.entry,
                            setup.entry + 2 * tick_size,
                            setup.stop,
                            float(trade["target_price"]),
                            int(trade["quantity"]),
                            str(signal_time),
                            str(day_bars.index[entry_end]),
                        )
                        quantity = int(trade["quantity"])
                        entry_fee = float(trade["entry_price"]) * quantity * config.commission_bps / 10_000.0
                        exit_fee = float(trade["exit_price"]) * quantity * config.commission_bps / 10_000.0
                        ledger.record_fill(
                            order_id, str(trade["entry_time"]), float(trade["entry_price"]),
                            quantity, "ENTRY", entry_fee, 0.0,
                            float(trade["entry_price"]) - setup.entry,
                        )
                        ledger.record_fill(
                            order_id, str(trade["exit_time"]), float(trade["exit_price"]),
                            quantity, str(trade["exit_reason"]), exit_fee,
                            float(trade["tax"]), 0.0,
                        )
                        break

    trades_frame = pd.DataFrame(trades)
    if not trades_frame.empty:
        trades_frame = trades_frame.sort_values("entry_time").reset_index(drop=True)
    summary = summarize_trades(trades_frame, config.initial_capital)
    diagnostics: dict[str, object] = {
        "universe_symbols": len(unique_items),
        "daily_covered_symbols": daily_covered,
        "minute_covered_symbols": minute_covered,
        "anchor_count": anchor_count,
        "abc_count": abc_count,
        "reason_counts": dict(reason_counts),
        "missing_execution_strength": True,
        "full_strategy_validated": False,
    }
    return trades_frame, summary, diagnostics


def run_hourly_breakout_baseline(
    store,
    watch_items: Iterable[WatchItem],
    output_db: str | Path,
    config: BacktestConfig,
    start: str | None = None,
    end: str | None = None,
    max_symbols: int | None = None,
    volume_multiple: float = 1.5,
) -> tuple[pd.DataFrame, dict[str, float | int], dict[str, object]]:
    unique_items: list[WatchItem] = []
    seen_tickers: set[str] = set()
    for item in watch_items:
        if item.ticker not in seen_tickers:
            unique_items.append(item)
            seen_tickers.add(item.ticker)
    if max_symbols is not None:
        unique_items = unique_items[:max_symbols]

    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    strategy_id = "lat5-hourly-ma-or-volume"
    algorithm_version = "0.2.0"
    trades: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    minute_covered = 0
    hourly_covered = 0
    breakout_count = 0

    with PaperLedger(output_db) as ledger:
        for item in unique_items:
            minutes = store.load_minutes(item.ticker)
            if minutes.empty:
                reason_counts["MINUTE_DATA_MISSING"] += 1
                continue
            minute_covered += 1
            minutes = minutes.sort_index().copy()
            if "amount" not in minutes:
                minutes["amount"] = (
                    minutes["close"].astype(float) * minutes["volume"].astype(float)
                )
            tick_size = infer_tick_size(minutes)
            if tick_size is None:
                reason_counts["TICK_SIZE_UNKNOWN"] += 1
                continue
            hourly = aggregate_60m(minutes).sort_index()
            if len(hourly) < 120:
                reason_counts["HOUR_DATA_INSUFFICIENT"] += 1
                continue
            hourly_covered += 1
            hourly["ema60"] = hourly["close"].astype(float).ewm(
                span=60, adjust=False, min_periods=60
            ).mean()
            hourly["ema120"] = hourly["close"].astype(float).ewm(
                span=120, adjust=False, min_periods=120
            ).mean()
            traded_days: set[pd.Timestamp] = set()

            for pos in range(120, len(hourly)):
                signal = hourly_or_breakout_at(
                    hourly, pos, volume_multiple=volume_multiple
                )
                if signal is None:
                    continue
                signal_time = pd.Timestamp(hourly.index[pos]) + pd.Timedelta(hours=1)
                signal_day = signal_time.normalize()
                if start_ts is not None and signal_day < start_ts:
                    continue
                if end_ts is not None and signal_day > end_ts:
                    continue
                if signal_day in traded_days:
                    reason_counts["DAILY_TRADE_ALREADY_DONE"] += 1
                    continue
                breakout_count += 1
                entry_bars = minutes.loc[
                    (minutes.index >= signal_time)
                    & (minutes.index.normalize() == signal_day)
                ]
                stop = signal.stop_reference - tick_size
                trade = None
                reason = "NEXT_5M_MISSING"
                if not entry_bars.empty:
                    trade = simulate_hourly_breakout_trade(
                        entry_bars,
                        entry_pos=0,
                        stop=stop,
                        equity=config.initial_capital,
                        config=config,
                    )
                    reason = "HOURLY_MA_OR_VOLUME" if trade is not None else "INVALID_STOP_OR_SIZE"

                decision = "BUY" if trade is not None else "REJECT"
                inputs = {
                    "crossed": list(signal.crossed),
                    "hour_close": float(hourly.iloc[pos]["close"]),
                    "ema60": float(hourly.iloc[pos]["ema60"]),
                    "ema120": float(hourly.iloc[pos]["ema120"]),
                    "volume_ratio": signal.volume_ratio,
                    "volume_multiple": volume_multiple,
                    "stop": stop,
                    "target_r": 2.0,
                }
                decision_id = ledger.record_decision(
                    str(signal_time),
                    item.ticker,
                    item.sector,
                    decision,
                    reason,
                    strategy_id,
                    algorithm_version,
                    inputs,
                )
                reason_counts[reason] += 1
                if trade is None:
                    continue

                trade.update(
                    ticker=item.ticker,
                    name=item.name,
                    sector=item.sector,
                    strategy_id=strategy_id,
                    algorithm_version=algorithm_version,
                )
                trades.append(trade)
                traded_days.add(signal_day)
                quantity = int(trade["quantity"])
                order_id = ledger.create_order(
                    decision_id,
                    float(trade["entry_price"]),
                    float(trade["entry_price"]),
                    float(trade["stop_price"]),
                    float(trade["target_price"]),
                    quantity,
                    str(signal_time),
                    str(entry_bars.index[0]),
                )
                entry_fee = (
                    float(trade["entry_price"])
                    * quantity
                    * config.commission_bps
                    / 10_000.0
                )
                exit_fee = (
                    float(trade["exit_price"])
                    * quantity
                    * config.commission_bps
                    / 10_000.0
                )
                ledger.record_fill(
                    order_id,
                    str(trade["entry_time"]),
                    float(trade["entry_price"]),
                    quantity,
                    "ENTRY",
                    entry_fee,
                    0.0,
                    float(trade["entry_price"])
                    - float(entry_bars.iloc[0]["open"]),
                )
                ledger.record_fill(
                    order_id,
                    str(trade["exit_time"]),
                    float(trade["exit_price"]),
                    quantity,
                    str(trade["exit_reason"]),
                    exit_fee,
                    float(trade["tax"]),
                    0.0,
                )

    trades_frame = pd.DataFrame(trades)
    if not trades_frame.empty:
        trades_frame = trades_frame.sort_values("entry_time").reset_index(drop=True)
    summary = summarize_trades(trades_frame, config.initial_capital)
    diagnostics: dict[str, object] = {
        "strategy": strategy_id,
        "universe_symbols": len(unique_items),
        "minute_covered_symbols": minute_covered,
        "hourly_covered_symbols": hourly_covered,
        "breakout_count": breakout_count,
        "reason_counts": dict(reason_counts),
        "volume_multiple": volume_multiple,
        "target_r": 2.0,
        "requested_strategy_validated": True,
        "full_lat_strategy_validated": False,
    }
    return trades_frame, summary, diagnostics


def run_hourly_abc_support_baseline(
    store,
    watch_items: Iterable[WatchItem],
    output_db: str | Path,
    config: BacktestConfig,
    start: str | None = None,
    end: str | None = None,
    max_symbols: int | None = None,
) -> tuple[pd.DataFrame, dict[str, float | int], dict[str, object]]:
    unique_items: list[WatchItem] = []
    seen_tickers: set[str] = set()
    for item in watch_items:
        if item.ticker not in seen_tickers:
            unique_items.append(item)
            seen_tickers.add(item.ticker)
    if max_symbols is not None:
        unique_items = unique_items[:max_symbols]

    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    strategy_id = "lat5-hourly-abc-ma60-support"
    algorithm_version = "0.3.0"
    trades: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    minute_covered = 0
    hourly_covered = 0
    strong_breakout_count = 0
    abc_support_count = 0

    with PaperLedger(output_db) as ledger:
        for item in unique_items:
            minutes = store.load_minutes(item.ticker)
            if minutes.empty:
                reason_counts["MINUTE_DATA_MISSING"] += 1
                continue
            minute_covered += 1
            minutes = minutes.sort_index().copy()
            if "amount" not in minutes:
                minutes["amount"] = (
                    minutes["close"].astype(float) * minutes["volume"].astype(float)
                )
            tick_size = infer_tick_size(minutes)
            if tick_size is None:
                reason_counts["TICK_SIZE_UNKNOWN"] += 1
                continue
            hourly = aggregate_60m(minutes).sort_index()
            if len(hourly) < 120:
                reason_counts["HOUR_DATA_INSUFFICIENT"] += 1
                continue
            hourly_covered += 1
            hourly["ema60"] = hourly["close"].astype(float).ewm(
                span=60, adjust=False, min_periods=60
            ).mean()
            hourly["ema120"] = hourly["close"].astype(float).ewm(
                span=120, adjust=False, min_periods=120
            ).mean()
            previous_close = hourly["close"].astype(float).shift(1)
            true_range = pd.concat(
                [
                    hourly["high"].astype(float) - hourly["low"].astype(float),
                    (hourly["high"].astype(float) - previous_close).abs(),
                    (hourly["low"].astype(float) - previous_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            hourly["atr20"] = true_range.rolling(20, min_periods=20).mean()

            strong_positions = [
                pos
                for pos in range(120, len(hourly))
                if strong_hourly_breakout_at(hourly, pos) is not None
            ]
            strong_breakout_count += len(strong_positions)
            traded_days: set[pd.Timestamp] = set()

            for index, breakout_pos in enumerate(strong_positions):
                setup = find_hourly_abc_support(hourly, breakout_pos)
                breakout_time = pd.Timestamp(hourly.index[breakout_pos]) + pd.Timedelta(hours=1)
                if setup is None:
                    reason_counts["HOURLY_ABC_OR_MA60_SUPPORT_MISSING"] += 1
                    ledger.record_decision(
                        str(breakout_time), item.ticker, item.sector, "REJECT",
                        "HOURLY_ABC_OR_MA60_SUPPORT_MISSING", strategy_id,
                        algorithm_version, {"breakout_pos": breakout_pos},
                    )
                    continue

                next_breakout_pos = (
                    strong_positions[index + 1]
                    if index + 1 < len(strong_positions)
                    else None
                )
                if next_breakout_pos is not None and next_breakout_pos <= setup.confirm_pos:
                    reason_counts["NEW_BREAKOUT_INVALIDATED_ABC"] += 1
                    continue
                abc_support_count += 1
                confirm_time = pd.Timestamp(hourly.index[setup.confirm_pos]) + pd.Timedelta(hours=1)
                expiry_time = (
                    pd.Timestamp(hourly.index[next_breakout_pos]) + pd.Timedelta(hours=1)
                    if next_breakout_pos is not None
                    else None
                )
                entry_window = minutes.loc[minutes.index >= confirm_time]
                if expiry_time is not None:
                    entry_window = entry_window.loc[entry_window.index < expiry_time]
                entry_pair = find_five_minute_c_high_entry(
                    entry_window,
                    start_time=confirm_time,
                    c_high=setup.c_high,
                    c_low=setup.c_low,
                )
                if entry_pair is None:
                    reason = "C_HIGH_NOT_BROKEN_OR_C_LOW_LOST"
                    reason_counts[reason] += 1
                    ledger.record_decision(
                        str(confirm_time), item.ticker, item.sector, "REJECT", reason,
                        strategy_id, algorithm_version,
                        {"c_high": setup.c_high, "c_low": setup.c_low},
                    )
                    continue

                trigger_pos, entry_pos = entry_pair
                entry_time = pd.Timestamp(entry_window.index[entry_pos])
                entry_day = entry_time.normalize()
                if start_ts is not None and entry_day < start_ts:
                    continue
                if end_ts is not None and entry_day > end_ts:
                    continue
                if entry_day in traded_days:
                    reason_counts["DAILY_TRADE_ALREADY_DONE"] += 1
                    continue
                day_bars = minutes.loc[
                    (minutes.index >= entry_time)
                    & (minutes.index.normalize() == entry_day)
                ]
                stop = setup.c_low - tick_size
                trade = simulate_hourly_breakout_trade(
                    day_bars,
                    entry_pos=0,
                    stop=stop,
                    equity=config.initial_capital,
                    config=config,
                )
                reason = "HOURLY_ABC_MA60_C_HIGH" if trade is not None else "INVALID_STOP_OR_SIZE"
                decision = "BUY" if trade is not None else "REJECT"
                inputs = {
                    "breakout_pos": breakout_pos,
                    "a_pos": setup.a_pos,
                    "b_pos": setup.b_pos,
                    "c_pos": setup.c_pos,
                    "c_high": setup.c_high,
                    "c_low": setup.c_low,
                    "ma60": setup.ma60,
                    "five_minute_trigger_time": str(entry_window.index[trigger_pos]),
                    "stop": stop,
                    "target_r": 2.0,
                }
                decision_id = ledger.record_decision(
                    str(entry_time), item.ticker, item.sector, decision, reason,
                    strategy_id, algorithm_version, inputs,
                )
                reason_counts[reason] += 1
                if trade is None:
                    continue

                trade.update(
                    ticker=item.ticker,
                    name=item.name,
                    sector=item.sector,
                    strategy_id=strategy_id,
                    algorithm_version=algorithm_version,
                )
                trades.append(trade)
                traded_days.add(entry_day)
                quantity = int(trade["quantity"])
                order_id = ledger.create_order(
                    decision_id,
                    float(trade["entry_price"]),
                    float(trade["entry_price"]),
                    float(trade["stop_price"]),
                    float(trade["target_price"]),
                    quantity,
                    str(entry_time),
                    str(entry_time),
                )
                entry_fee = (
                    float(trade["entry_price"]) * quantity
                    * config.commission_bps / 10_000.0
                )
                exit_fee = (
                    float(trade["exit_price"]) * quantity
                    * config.commission_bps / 10_000.0
                )
                ledger.record_fill(
                    order_id, str(trade["entry_time"]), float(trade["entry_price"]),
                    quantity, "ENTRY", entry_fee, 0.0,
                    float(trade["entry_price"]) - float(day_bars.iloc[0]["open"]),
                )
                ledger.record_fill(
                    order_id, str(trade["exit_time"]), float(trade["exit_price"]),
                    quantity, str(trade["exit_reason"]), exit_fee,
                    float(trade["tax"]), 0.0,
                )

    trades_frame = pd.DataFrame(trades)
    if not trades_frame.empty:
        trades_frame = trades_frame.sort_values("entry_time").reset_index(drop=True)
    summary = summarize_trades(trades_frame, config.initial_capital)
    diagnostics: dict[str, object] = {
        "strategy": strategy_id,
        "universe_symbols": len(unique_items),
        "minute_covered_symbols": minute_covered,
        "hourly_covered_symbols": hourly_covered,
        "strong_breakout_count": strong_breakout_count,
        "abc_support_count": abc_support_count,
        "reason_counts": dict(reason_counts),
        "target_r": 2.0,
        "requested_strategy_validated": True,
        "full_lat_strategy_validated": False,
    }
    return trades_frame, summary, diagnostics


def run_hourly_pullback_reversal_baseline(
    store,
    watch_items: Iterable[WatchItem],
    output_db: str | Path,
    config: BacktestConfig,
    start: str | None = None,
    end: str | None = None,
    max_symbols: int | None = None,
    location_cfg: LocationScoreConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, float | int], dict[str, object]]:
    unique_items: list[WatchItem] = []
    seen_tickers: set[str] = set()
    for item in watch_items:
        if item.ticker not in seen_tickers:
            unique_items.append(item)
            seen_tickers.add(item.ticker)
    if max_symbols is not None:
        unique_items = unique_items[:max_symbols]

    start_ts = pd.Timestamp(start) if start else None
    end_ts = pd.Timestamp(end) if end else None
    strategy_id = "lat5-hourly-pullback-reversal"
    algorithm_version = "0.4.0"
    trades: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    minute_covered = 0
    hourly_covered = 0
    strong_breakout_count = 0
    pullback_count = 0
    reversal_trigger_count = 0
    location_filtered_count = 0
    location_decisions: list[dict[str, object]] = []

    with PaperLedger(output_db) as ledger:
        for item in unique_items:
            minutes = store.load_minutes(item.ticker)
            if minutes.empty:
                reason_counts["MINUTE_DATA_MISSING"] += 1
                continue
            minute_covered += 1
            minutes = minutes.sort_index().copy()
            daily_ema = None
            if location_cfg is not None:
                daily = store.load_daily(item.ticker)
                daily_ema = daily_ema_context(daily) if not daily.empty else daily
            if "amount" not in minutes:
                minutes["amount"] = (
                    minutes["close"].astype(float) * minutes["volume"].astype(float)
                )
            minutes["ema20_5m"] = minutes["close"].astype(float).ewm(
                span=20, adjust=False, min_periods=20
            ).mean()
            tick_size = infer_tick_size(minutes)
            if tick_size is None:
                reason_counts["TICK_SIZE_UNKNOWN"] += 1
                continue
            hourly = aggregate_60m(minutes).sort_index()
            if len(hourly) < 120:
                reason_counts["HOUR_DATA_INSUFFICIENT"] += 1
                continue
            hourly_covered += 1
            hourly["ema60"] = hourly["close"].astype(float).ewm(
                span=60, adjust=False, min_periods=60
            ).mean()
            hourly["ema120"] = hourly["close"].astype(float).ewm(
                span=120, adjust=False, min_periods=120
            ).mean()
            previous_close = hourly["close"].astype(float).shift(1)
            true_range = pd.concat(
                [
                    hourly["high"].astype(float) - hourly["low"].astype(float),
                    (hourly["high"].astype(float) - previous_close).abs(),
                    (hourly["low"].astype(float) - previous_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            hourly["atr20"] = true_range.rolling(20, min_periods=20).mean()

            all_strong_positions = [
                pos
                for pos in range(120, len(hourly))
                if strong_hourly_breakout_at(hourly, pos) is not None
            ]
            strong_positions = []
            for pos in all_strong_positions:
                signal_day = (
                    pd.Timestamp(hourly.index[pos]) + pd.Timedelta(hours=1)
                ).normalize()
                if start_ts is not None and signal_day < start_ts:
                    continue
                if end_ts is not None and signal_day > end_ts:
                    continue
                strong_positions.append(pos)
            strong_breakout_count += len(strong_positions)
            traded_days: set[pd.Timestamp] = set()

            for index, breakout_pos in enumerate(strong_positions):
                setup = find_hourly_ma60_pullback(hourly, breakout_pos)
                breakout_time = pd.Timestamp(hourly.index[breakout_pos]) + pd.Timedelta(hours=1)
                if setup is None:
                    reason = "MA60_PULLBACK_2_TO_6_MISSING"
                    reason_counts[reason] += 1
                    ledger.record_decision(
                        str(breakout_time), item.ticker, item.sector, "REJECT", reason,
                        strategy_id, algorithm_version, {"breakout_pos": breakout_pos},
                    )
                    continue

                next_breakout_pos = (
                    strong_positions[index + 1]
                    if index + 1 < len(strong_positions)
                    else None
                )
                if next_breakout_pos is not None and next_breakout_pos <= setup.pullback_pos:
                    reason_counts["NEW_BREAKOUT_INVALIDATED_PULLBACK"] += 1
                    continue
                pullback_count += 1
                confirm_time = pd.Timestamp(hourly.index[setup.pullback_pos]) + pd.Timedelta(hours=1)

                location: dict[str, object] | None = None
                if location_cfg is not None:
                    ctx = build_context(
                        daily=daily,
                        daily_ema=daily_ema,
                        hourly=hourly,
                        minutes=minutes,
                        as_of=confirm_time.normalize(),
                        cfg=location_cfg,
                        cutoff=confirm_time,
                    )
                    location = evaluate_watchlist_position(ctx, location_cfg)
                    location_decisions.append(
                        {
                            "symbol": item.ticker,
                            "name": item.name,
                            "evaluated_at": str(confirm_time),
                            "final_state": location["state"],
                            "entry_eligible": location.get("entry_eligible") is True,
                            "location_score": location["location_score"],
                            "score_components": dict(location.get("score_components", {})),
                            "vetoes": list(location.get("vetoes", [])),
                            "unknown_fields": list(location.get("unknown_fields", [])),
                            "m60_rsi14": location.get("m60_rsi14"),
                            "daily_ma_reaction": location.get("daily_ma_reaction"),
                            "rr_breakdown": location.get("rr_breakdown"),
                            "breakout_resistance_price": location.get("breakout_resistance_price"),
                            "breakout_entry_price": location.get("breakout_entry_price"),
                            "breakout_stop_price": location.get("breakout_stop_price"),
                            "breakout_target_price": location.get("breakout_target_price"),
                            "breakout_rr": location.get("breakout_rr"),
                        }
                    )
                    if location.get("entry_eligible") is not True:
                        reason = "LOCATION_FILTERED"
                        reason_counts[reason] += 1
                        location_filtered_count += 1
                        ledger.record_decision(
                            str(confirm_time), item.ticker, item.sector, "REJECT", reason,
                            strategy_id, algorithm_version,
                            _location_ledger_evidence(location),
                        )
                        continue

                session_end = confirm_time.normalize() + pd.Timedelta(days=1)
                entry_bars = minutes.loc[minutes.index < session_end]
                if next_breakout_pos is not None:
                    expiry_time = pd.Timestamp(hourly.index[next_breakout_pos]) + pd.Timedelta(hours=1)
                    entry_bars = entry_bars.loc[entry_bars.index < expiry_time]
                entry_pair = find_five_minute_reversal_entry(
                    entry_bars,
                    start_time=confirm_time,
                    pullback_low=setup.pullback_low,
                )
                if entry_pair is None:
                    reason = "FIVE_MINUTE_REVERSAL_MISSING_OR_INVALIDATED"
                    reason_counts[reason] += 1
                    inputs = {
                        "pullback_low": setup.pullback_low,
                        "ma60": setup.ma60,
                    }
                    inputs.update(_location_ledger_evidence(location))
                    ledger.record_decision(
                        str(confirm_time), item.ticker, item.sector, "REJECT", reason,
                        strategy_id, algorithm_version,
                        inputs,
                    )
                    continue

                trigger_pos, entry_pos = entry_pair
                reversal_trigger_count += 1
                entry_time = pd.Timestamp(entry_bars.index[entry_pos])
                entry_day = entry_time.normalize()
                if start_ts is not None and entry_day < start_ts:
                    continue
                if end_ts is not None and entry_day > end_ts:
                    continue
                if entry_day in traded_days:
                    reason_counts["DAILY_TRADE_ALREADY_DONE"] += 1
                    continue

                trade_bars = minutes.loc[
                    (minutes.index >= entry_time)
                    & (minutes.index.normalize() == entry_day)
                ]
                stop = setup.pullback_low - tick_size
                trade = simulate_pullback_reversal_trade(
                    trade_bars,
                    entry_pos=0,
                    stop=stop,
                    equity=config.initial_capital,
                    config=config,
                )
                reason = "HOURLY_MA60_PULLBACK_5M_REVERSAL" if trade is not None else "INVALID_STOP_OR_SIZE"
                decision = "BUY" if trade is not None else "REJECT"
                inputs = {
                    "breakout_pos": breakout_pos,
                    "pullback_pos": setup.pullback_pos,
                    "pullback_high": setup.pullback_high,
                    "pullback_low": setup.pullback_low,
                    "ma60": setup.ma60,
                    "five_minute_trigger_time": str(entry_bars.index[trigger_pos]),
                    "stop": stop,
                    "partial_target_r": 1.0,
                    "final_target_r": 2.0,
                    "entry_cutoff": "14:30",
                }
                if location is not None:
                    inputs.update(_location_ledger_evidence(location))
                decision_id = ledger.record_decision(
                    str(entry_time), item.ticker, item.sector, decision, reason,
                    strategy_id, algorithm_version, inputs,
                )
                reason_counts[reason] += 1
                if trade is None:
                    continue

                trade.update(
                    ticker=item.ticker,
                    name=item.name,
                    sector=item.sector,
                    strategy_id=strategy_id,
                    algorithm_version=algorithm_version,
                )
                trades.append(trade)
                traded_days.add(entry_day)
                quantity = int(trade["quantity"])
                order_id = ledger.create_order(
                    decision_id,
                    float(trade["entry_price"]),
                    float(trade["entry_price"]),
                    float(trade["stop_price"]),
                    float(trade["target_price"]),
                    quantity,
                    str(entry_time),
                    str(entry_time),
                )
                entry_fee = (
                    float(trade["entry_price"]) * quantity
                    * config.commission_bps / 10_000.0
                )
                ledger.record_fill(
                    order_id, str(trade["entry_time"]), float(trade["entry_price"]),
                    quantity, "ENTRY", entry_fee, 0.0,
                    float(trade["entry_price"]) - float(trade_bars.iloc[0]["open"]),
                )
                for event in trade["exit_fills"]:
                    price = float(event["price"])
                    event_quantity = int(event["quantity"])
                    exit_fee = price * event_quantity * config.commission_bps / 10_000.0
                    tax = price * event_quantity * config.sell_tax_bps / 10_000.0
                    ledger.record_fill(
                        order_id, str(event["time"]), price, event_quantity,
                        str(event["reason"]), exit_fee, tax, 0.0,
                    )

    trades_frame = pd.DataFrame(trades)
    if not trades_frame.empty:
        trades_frame = trades_frame.sort_values("entry_time").reset_index(drop=True)
    summary = summarize_trades(trades_frame, config.initial_capital)
    diagnostics: dict[str, object] = {
        "strategy": strategy_id,
        "algorithm_version": algorithm_version,
        "universe_symbols": len(unique_items),
        "minute_covered_symbols": minute_covered,
        "hourly_covered_symbols": hourly_covered,
        "strong_breakout_count": strong_breakout_count,
        "pullback_count": pullback_count,
        "reversal_trigger_count": reversal_trigger_count,
        "location_gate_enabled": location_cfg is not None,
        "location_filtered_count": location_filtered_count,
        "location_decisions": location_decisions,
        "reason_counts": dict(reason_counts),
        "partial_target_r": 1.0,
        "final_target_r": 2.0,
        "requested_strategy_validated": True,
        "full_lat_strategy_validated": False,
    }
    return trades_frame, summary, diagnostics


def summarize_trades(trades: pd.DataFrame, initial_capital: float) -> dict[str, float | int]:
    if trades.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "net_pnl": 0.0,
            "return_pct": 0.0,
            "max_drawdown": 0.0,
        }
    pnl = trades["net_pnl"].astype(float)
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else inf
    equity_change = pd.concat([pd.Series([0.0]), pnl.cumsum()], ignore_index=True)
    drawdown = equity_change.cummax() - equity_change
    net_pnl = float(pnl.sum())
    return {
        "trades": int(len(pnl)),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": profit_factor,
        "expectancy": float(pnl.mean()),
        "net_pnl": net_pnl,
        "return_pct": net_pnl / initial_capital * 100.0,
        "max_drawdown": float(drawdown.max()),
    }
