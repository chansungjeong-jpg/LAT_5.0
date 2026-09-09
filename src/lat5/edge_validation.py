"""Research-only edge validation for the recovery filter -> RS -> location
score chain (see docs/edge_validation_design.md and c-handoff.md).

This module never writes to `data/lat5_market.db` and never touches the
production artifacts under `artifacts/latest_scoring/`. It re-derives
point-in-time feature snapshots from raw OHLCV and evaluates them against
strictly-later outcome bars, keeping the two concerns in separate data
structures (`FeatureSnapshot` vs `Outcome`) so a bug in one cannot leak
future information into the other.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace

import pandas as pd

from lat5.data import KiwoomDataStore, WatchItem, aggregate_60m, daily_ema_context
from lat5.location_decision import (
    LocationScoreConfig,
    build_context,
    evaluate_watchlist_position,
)
from lat5.monthly_weekly_filter import periods_as_of, recent_recovery, recovery_details
from lat5.relative_strength import market_average_return, n_day_return, relative_strength

RS_DAYS_DEFAULT = 20
SESSION_MIN_COVERAGE_DEFAULT = 0.5
COMMISSION_BPS_DEFAULT = 1.5
SELL_TAX_BPS_DEFAULT = 20.0
SLIPPAGE_BPS_DEFAULT = 5.0


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UniverseItem:
    ticker: str
    name: str
    sectors: tuple[str, ...]


def dedup_universe(items: list[WatchItem]) -> list[UniverseItem]:
    """Collapse the sector-duplicated watchlist rows to one row per ticker.

    Membership counts, equal-weight averages, and sample sizes must use the
    unique ticker set (154), not the 168 sector-joined rows -- a ticker
    listed under two sectors would otherwise be double-counted.
    """
    order: list[str] = []
    sectors_by_ticker: dict[str, list[str]] = {}
    name_by_ticker: dict[str, str] = {}
    for item in items:
        if item.ticker not in sectors_by_ticker:
            order.append(item.ticker)
            sectors_by_ticker[item.ticker] = []
            name_by_ticker[item.ticker] = item.name
        if item.sector not in sectors_by_ticker[item.ticker]:
            sectors_by_ticker[item.ticker].append(item.sector)
    return [
        UniverseItem(ticker, name_by_ticker[ticker], tuple(sectors_by_ticker[ticker]))
        for ticker in order
    ]


# ---------------------------------------------------------------------------
# Trading calendar
# ---------------------------------------------------------------------------


def build_session_calendar(
    daily_frames: dict[str, pd.DataFrame], *, min_coverage: float = SESSION_MIN_COVERAGE_DEFAULT
) -> list[pd.Timestamp]:
    """Dates recognised as a real market session.

    No independent index/holiday calendar is available in this repo (see
    design doc section 5), so a date counts as a session when at least
    `min_coverage` of the given tickers have a daily row on it -- a
    data-driven proxy that is robust to any single ticker's gaps.
    """
    counts: Counter[pd.Timestamp] = Counter()
    for frame in daily_frames.values():
        for ts in frame.index:
            counts[pd.Timestamp(ts).normalize()] += 1
    total = len(daily_frames)
    if total == 0:
        return []
    threshold = max(1, math.ceil(total * min_coverage))
    return sorted(ts for ts, count in counts.items() if count >= threshold)


# ---------------------------------------------------------------------------
# Point-in-time truncation
# ---------------------------------------------------------------------------


def truncate_daily(daily: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.DataFrame:
    """Rows with date <= as_of_date (inclusive of the evaluation day itself)."""
    if daily.empty:
        return daily
    as_of_date = pd.Timestamp(as_of_date).normalize()
    return daily.loc[daily.index.normalize() <= as_of_date]


def truncate_minutes(minutes: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if minutes.empty:
        return minutes
    return minutes.loc[minutes.index <= pd.Timestamp(cutoff)]


# ---------------------------------------------------------------------------
# Recovery snapshot (final_spec ch.0 -- reused as-is from monthly_weekly_filter)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecoveryResult:
    passed: bool
    provisional: bool | None
    weekly_detail: dict | None
    monthly_detail: dict | None
    reason: str | None


def evaluate_recovery(daily_trunc: pd.DataFrame, as_of: pd.Timestamp) -> RecoveryResult:
    as_of = pd.Timestamp(as_of)
    weekly, monthly = periods_as_of(daily_trunc, as_of, include_in_progress=True)
    if weekly.empty or monthly.empty:
        return RecoveryResult(False, None, None, None, "INSUFFICIENT_HISTORY")
    passed = recent_recovery(weekly, 5) and recent_recovery(monthly, 10)
    if not passed:
        return RecoveryResult(False, None, None, None, "NOT_RECOVERED")
    provisional = bool(
        monthly.index[-1].to_period("M") == as_of.to_period("M") or weekly.index[-1] > as_of
    )
    return RecoveryResult(
        True,
        provisional,
        recovery_details(weekly, 5),
        recovery_details(monthly, 10),
        None,
    )


# ---------------------------------------------------------------------------
# Relative strength snapshot (reuses relative_strength.py, but on truncated
# frames -- the scan script's bug was never truncating in the first place)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelativeStrengthSnapshot:
    market_return: float | None
    universe_n: int
    by_ticker: dict[str, float | None]  # RS value or None if not computable
    stock_return_by_ticker: dict[str, float | None]


def evaluate_relative_strength(
    daily_trunc_by_ticker: dict[str, pd.DataFrame], *, days: int = RS_DAYS_DEFAULT
) -> RelativeStrengthSnapshot:
    market_return = market_average_return(daily_trunc_by_ticker, days=days)
    by_ticker: dict[str, float | None] = {}
    stock_return_by_ticker: dict[str, float | None] = {}
    universe_n = 0
    for ticker, daily in daily_trunc_by_ticker.items():
        stock_return = n_day_return(daily, days=days)
        stock_return_by_ticker[ticker] = stock_return
        if stock_return is not None:
            universe_n += 1
        result = relative_strength(daily, market_return, days=days)
        by_ticker[ticker] = result.rs if result is not None else None
    return RelativeStrengthSnapshot(market_return, universe_n, by_ticker, stock_return_by_ticker)


# ---------------------------------------------------------------------------
# Location score snapshot (reuses location_decision.py -- the actual
# dashboard path, not the unused location_score.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocationResult:
    score: int | None
    state: str | None
    vetoes: tuple[str, ...]
    rr: float | None
    rr_known: bool
    unknown_fields: tuple[str, ...]
    reason: str | None


_MISSING_LOCATION = LocationResult(None, None, (), None, False, (), None)


def evaluate_location(
    daily_trunc: pd.DataFrame,
    minutes_trunc: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    cutoff: pd.Timestamp,
    cfg: LocationScoreConfig,
) -> LocationResult:
    if minutes_trunc.empty:
        return replace(_MISSING_LOCATION, reason="MINUTE_DATA_MISSING")
    minutes_trunc = minutes_trunc.sort_index().copy()
    if "amount" not in minutes_trunc:
        minutes_trunc["amount"] = (
            minutes_trunc["close"].astype(float) * minutes_trunc["volume"].astype(float)
        )
    minutes_trunc["ema20_5m"] = (
        minutes_trunc["close"].astype(float).ewm(span=20, adjust=False, min_periods=20).mean()
    )
    hourly = aggregate_60m(minutes_trunc).sort_index()
    if len(hourly) < 120:
        return replace(_MISSING_LOCATION, reason="HOURLY_DATA_INSUFFICIENT")
    hourly["ema60"] = hourly["close"].astype(float).ewm(span=60, adjust=False, min_periods=60).mean()
    hourly["ema120"] = (
        hourly["close"].astype(float).ewm(span=120, adjust=False, min_periods=120).mean()
    )
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
    daily_ema = daily_ema_context(daily_trunc) if not daily_trunc.empty else daily_trunc

    ctx = build_context(
        daily=daily_trunc,
        daily_ema=daily_ema,
        hourly=hourly,
        minutes=minutes_trunc,
        as_of=pd.Timestamp(as_of),
        cfg=cfg,
        cutoff=pd.Timestamp(cutoff),
    )
    decision = evaluate_watchlist_position(ctx, cfg)
    unknown_fields = tuple(decision.get("unknown_fields", []))
    return LocationResult(
        score=int(decision["location_score"]),
        state=str(decision["state"]),
        vetoes=tuple(decision.get("vetoes", [])),
        rr=decision.get("rr"),
        rr_known="rr" not in unknown_fields,
        unknown_fields=unknown_fields,
        reason=None,
    )


# ---------------------------------------------------------------------------
# Flow signal (H-002, see .claude/skills/edge-loop/research_log/hypotheses.md)
#
# foreign_net_cum and strength_mean are kept as two SEPARATE signals, never
# combined into one score -- CloseBet's provisional_score already documents
# why blending untested features is risky (the combination itself becomes an
# extra unvalidated hypothesis). edge_validation_stats.build_comparisons
# ranks each independently.
# ---------------------------------------------------------------------------

FOREIGN_FLOW_LOOKBACK_DAYS_DEFAULT = 5


@dataclass(frozen=True)
class FlowResult:
    foreign_net_cum: float | None  # sum of foreign_net_thousand over the lookback window
    foreign_net_lookback_days: int
    strength_mean: float | None  # mean execution strength across the eval day's own minutes
    reason: str | None


_MISSING_FLOW = FlowResult(None, FOREIGN_FLOW_LOOKBACK_DAYS_DEFAULT, None, "FLOW_DATA_MISSING")


def evaluate_flow_signal(
    foreign_flow_trunc: pd.DataFrame,
    strength_trunc: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    lookback_days: int = FOREIGN_FLOW_LOOKBACK_DAYS_DEFAULT,
) -> FlowResult:
    """`foreign_flow_trunc`/`strength_trunc` must already be truncated by the
    caller (date <= as_of / datetime <= cutoff) -- this function does not
    truncate, matching evaluate_recovery/evaluate_location's contract.
    """
    as_of = pd.Timestamp(as_of).normalize()

    foreign_net_cum: float | None = None
    if not foreign_flow_trunc.empty and "foreign_net" in foreign_flow_trunc.columns:
        window = foreign_flow_trunc.sort_index().tail(lookback_days)
        if len(window) == lookback_days:
            foreign_net_cum = float(window["foreign_net"].astype(float).sum())

    strength_mean: float | None = None
    if not strength_trunc.empty and "strength" in strength_trunc.columns:
        today = strength_trunc.loc[strength_trunc.index.normalize() == as_of]
        if not today.empty:
            strength_mean = float(today["strength"].astype(float).mean())

    reason = None if (foreign_net_cum is not None or strength_mean is not None) else "FLOW_DATA_MISSING"
    return FlowResult(foreign_net_cum, lookback_days, strength_mean, reason)


# ---------------------------------------------------------------------------
# Entry / outcome resolution (post-hoc; deliberately kept out of the
# feature-snapshot code path above)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryResult:
    status: str  # "FILLED" | "UNFILLED"
    entry_date: pd.Timestamp | None
    entry_price: float | None
    entry_pos: int | None
    reason: str | None


def resolve_entry(
    daily_full: pd.DataFrame, eval_day: pd.Timestamp, calendar: list[pd.Timestamp]
) -> EntryResult:
    eval_day = pd.Timestamp(eval_day).normalize()
    future_sessions = [d for d in calendar if d > eval_day]
    if not future_sessions:
        return EntryResult("UNFILLED", None, None, None, "NO_NEXT_SESSION_IN_CALENDAR")
    next_session = future_sessions[0]
    if daily_full.empty:
        return EntryResult("UNFILLED", None, None, None, "NO_TICKER_ROW_ON_NEXT_SESSION")
    normalized_index = daily_full.index.normalize()
    matches = normalized_index == next_session
    if not matches.any():
        return EntryResult("UNFILLED", None, None, None, "NO_TICKER_ROW_ON_NEXT_SESSION")
    pos = int(matches.argmax())
    open_price = float(daily_full.iloc[pos]["open"])
    if not (open_price > 0):
        return EntryResult("UNFILLED", None, None, None, "INVALID_OPEN_PRICE")
    return EntryResult("FILLED", daily_full.index[pos], open_price, pos, None)


@dataclass(frozen=True)
class OutcomeResult:
    status: str  # "MATURE" | "IMMATURE" | "DATA_GAP"
    exit_date: pd.Timestamp | None
    exit_price: float | None
    gross_return: float | None
    net_return: float | None
    mfe: float | None
    mae: float | None
    sessions_available: int
    sessions_required: int


def resolve_outcome(
    daily_full: pd.DataFrame,
    entry_pos: int,
    entry_price: float,
    entry_date: pd.Timestamp,
    hold_days: int,
    calendar: list[pd.Timestamp],
    *,
    commission_bps: float = COMMISSION_BPS_DEFAULT,
    sell_tax_bps: float = SELL_TAX_BPS_DEFAULT,
    slippage_bps: float = SLIPPAGE_BPS_DEFAULT,
) -> OutcomeResult:
    total_rows = len(daily_full)
    exit_pos = entry_pos + hold_days - 1
    sessions_available = total_rows - entry_pos
    if exit_pos < total_rows:
        window = daily_full.iloc[entry_pos : exit_pos + 1]
        exit_price = float(window["close"].iloc[-1])
        exit_date = window.index[-1]
        mfe = float(window["high"].astype(float).max() / entry_price - 1.0)
        mae = float(window["low"].astype(float).min() / entry_price - 1.0)
        gross_return = exit_price / entry_price - 1.0
        cost_fraction = (2 * commission_bps + sell_tax_bps + 2 * slippage_bps) / 10_000.0
        net_return = gross_return - cost_fraction
        return OutcomeResult(
            "MATURE", exit_date, exit_price, gross_return, net_return, mfe, mae,
            sessions_available, hold_days,
        )

    entry_date = pd.Timestamp(entry_date).normalize()
    sessions_since_entry = [d for d in calendar if d >= entry_date]
    status = "DATA_GAP" if len(sessions_since_entry) >= hold_days else "IMMATURE"
    return OutcomeResult(
        status, None, None, None, None, None, None, sessions_available, hold_days
    )


# ---------------------------------------------------------------------------
# Alternate fill rule: signal-day close entry -> H-day open exit.
#
# Priority-1 finding from the overnight/intraday leg decomposition (see
# reports/edge_validation -- 154-ticker x 12yr split of close-to-open vs.
# open-to-close legs): every year 2015-2026 the overnight leg is positive
# and most years the intraday leg is negative. The production fill rule
# (next-session open entry -> H-day close exit) captures exactly zero
# overnight legs from the signal day and captures every intraday leg
# including the exit day's -- the worst possible alignment given that split.
#
# resolve_entry_close/resolve_outcome_close_to_open re-price the *same*
# H-session window (same entry_pos/exit_pos arithmetic, same calendar) by
# swapping in the signal day's own close as entry and the exit day's open
# instead of its close. Algebraically this replaces the exit day's intraday
# leg with the signal day's overnight leg and touches nothing in between --
# so any difference from resolve_entry/resolve_outcome isolates exactly
# that one swap, not a different sample or a different feature.
# ---------------------------------------------------------------------------


def resolve_entry_close(
    daily_full: pd.DataFrame, eval_day: pd.Timestamp
) -> EntryResult:
    eval_day = pd.Timestamp(eval_day).normalize()
    if daily_full.empty:
        return EntryResult("UNFILLED", None, None, None, "NO_TICKER_ROW_ON_EVAL_DAY")
    normalized_index = daily_full.index.normalize()
    matches = normalized_index == eval_day
    if not matches.any():
        return EntryResult("UNFILLED", None, None, None, "NO_TICKER_ROW_ON_EVAL_DAY")
    pos = int(matches.argmax())
    close_price = float(daily_full.iloc[pos]["close"])
    if not (close_price > 0):
        return EntryResult("UNFILLED", None, None, None, "INVALID_CLOSE_PRICE")
    return EntryResult("FILLED", daily_full.index[pos], close_price, pos, None)


def resolve_outcome_close_to_open(
    daily_full: pd.DataFrame,
    entry_pos: int,
    entry_price: float,
    entry_date: pd.Timestamp,
    hold_days: int,
    calendar: list[pd.Timestamp],
    *,
    commission_bps: float = COMMISSION_BPS_DEFAULT,
    sell_tax_bps: float = SELL_TAX_BPS_DEFAULT,
    slippage_bps: float = SLIPPAGE_BPS_DEFAULT,
) -> OutcomeResult:
    total_rows = len(daily_full)
    exit_pos = entry_pos + hold_days  # one row further than resolve_outcome:
    # entry_pos here is the signal day itself (day 0), not day 1.
    sessions_available = total_rows - entry_pos - 1
    if exit_pos < total_rows:
        window = daily_full.iloc[entry_pos : exit_pos + 1]
        exit_price = float(daily_full.iloc[exit_pos]["open"])
        exit_date = daily_full.index[exit_pos]
        mfe = float(window["high"].astype(float).max() / entry_price - 1.0)
        mae = float(window["low"].astype(float).min() / entry_price - 1.0)
        gross_return = exit_price / entry_price - 1.0
        cost_fraction = (2 * commission_bps + sell_tax_bps + 2 * slippage_bps) / 10_000.0
        net_return = gross_return - cost_fraction
        return OutcomeResult(
            "MATURE", exit_date, exit_price, gross_return, net_return, mfe, mae,
            sessions_available, hold_days,
        )

    entry_date = pd.Timestamp(entry_date).normalize()
    sessions_after_entry = [d for d in calendar if d > entry_date]
    status = "DATA_GAP" if len(sessions_after_entry) >= hold_days else "IMMATURE"
    return OutcomeResult(
        status, None, None, None, None, None, None, sessions_available, hold_days
    )


# ---------------------------------------------------------------------------
# Per-eval-day orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TickerDayRecord:
    eval_day: pd.Timestamp
    ticker: str
    name: str
    sectors: tuple[str, ...]
    recovery: RecoveryResult
    rs: float | None
    stock_return: float | None
    location: LocationResult
    entry: EntryResult
    outcomes: dict[int, OutcomeResult]
    entry_close: EntryResult
    outcomes_close_to_open: dict[int, OutcomeResult]
    flow: FlowResult


@dataclass(frozen=True)
class RunConfig:
    db_path: str
    watchlist_path: str
    start: str
    end: str
    holds: tuple[int, ...] = (10, 5, 20)
    rs_days: int = RS_DAYS_DEFAULT
    session_min_coverage: float = SESSION_MIN_COVERAGE_DEFAULT
    location_cfg: LocationScoreConfig = field(default_factory=LocationScoreConfig)
    commission_bps: float = COMMISSION_BPS_DEFAULT
    sell_tax_bps: float = SELL_TAX_BPS_DEFAULT
    slippage_bps: float = SLIPPAGE_BPS_DEFAULT
    flow_lookback_days: int = FOREIGN_FLOW_LOOKBACK_DAYS_DEFAULT


def load_universe_data(
    store: KiwoomDataStore, universe: list[UniverseItem]
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    daily_full: dict[str, pd.DataFrame] = {}
    minutes_full: dict[str, pd.DataFrame] = {}
    foreign_flow_full: dict[str, pd.DataFrame] = {}
    strength_full: dict[str, pd.DataFrame] = {}
    for item in universe:
        daily_full[item.ticker] = store.load_daily(item.ticker)
        minutes_full[item.ticker] = store.load_minutes(item.ticker)
        foreign_flow_full[item.ticker] = store.load_foreign_flow(item.ticker)
        strength_full[item.ticker] = store.load_execution_strength(item.ticker)
    return daily_full, minutes_full, foreign_flow_full, strength_full


def run_eval_day(
    eval_day: pd.Timestamp,
    universe: list[UniverseItem],
    daily_full: dict[str, pd.DataFrame],
    minutes_full: dict[str, pd.DataFrame],
    calendar: list[pd.Timestamp],
    cfg: RunConfig,
    foreign_flow_full: dict[str, pd.DataFrame] | None = None,
    strength_full: dict[str, pd.DataFrame] | None = None,
) -> list[TickerDayRecord]:
    eval_day = pd.Timestamp(eval_day).normalize()
    daily_trunc = {
        item.ticker: truncate_daily(daily_full[item.ticker], eval_day) for item in universe
    }
    rs_snapshot = evaluate_relative_strength(daily_trunc, days=cfg.rs_days)

    cutoff = eval_day + pd.Timedelta(hours=16)
    records: list[TickerDayRecord] = []
    for item in universe:
        recovery = evaluate_recovery(daily_trunc[item.ticker], eval_day)
        location = _MISSING_LOCATION
        flow = _MISSING_FLOW
        if recovery.passed:
            minutes_trunc = truncate_minutes(minutes_full[item.ticker], cutoff)
            location = evaluate_location(
                daily_trunc[item.ticker],
                minutes_trunc,
                as_of=eval_day,
                cutoff=cutoff,
                cfg=cfg.location_cfg,
            )
            if foreign_flow_full is not None and strength_full is not None:
                flow = evaluate_flow_signal(
                    truncate_daily(foreign_flow_full[item.ticker], eval_day),
                    truncate_minutes(strength_full[item.ticker], cutoff),
                    as_of=eval_day,
                    lookback_days=cfg.flow_lookback_days,
                )

        entry = resolve_entry(daily_full[item.ticker], eval_day, calendar)
        outcomes: dict[int, OutcomeResult] = {}
        if entry.status == "FILLED":
            for hold_days in cfg.holds:
                outcomes[hold_days] = resolve_outcome(
                    daily_full[item.ticker],
                    entry.entry_pos,
                    entry.entry_price,
                    entry.entry_date,
                    hold_days,
                    calendar,
                    commission_bps=cfg.commission_bps,
                    sell_tax_bps=cfg.sell_tax_bps,
                    slippage_bps=cfg.slippage_bps,
                )

        entry_close = resolve_entry_close(daily_full[item.ticker], eval_day)
        outcomes_close_to_open: dict[int, OutcomeResult] = {}
        if entry_close.status == "FILLED":
            for hold_days in cfg.holds:
                outcomes_close_to_open[hold_days] = resolve_outcome_close_to_open(
                    daily_full[item.ticker],
                    entry_close.entry_pos,
                    entry_close.entry_price,
                    entry_close.entry_date,
                    hold_days,
                    calendar,
                    commission_bps=cfg.commission_bps,
                    sell_tax_bps=cfg.sell_tax_bps,
                    slippage_bps=cfg.slippage_bps,
                )

        records.append(
            TickerDayRecord(
                eval_day=eval_day,
                ticker=item.ticker,
                name=item.name,
                sectors=item.sectors,
                recovery=recovery,
                rs=rs_snapshot.by_ticker.get(item.ticker),
                stock_return=rs_snapshot.stock_return_by_ticker.get(item.ticker),
                location=location,
                entry=entry,
                outcomes=outcomes,
                entry_close=entry_close,
                outcomes_close_to_open=outcomes_close_to_open,
                flow=flow,
            )
        )
    return records


def run(cfg: RunConfig) -> dict[str, object]:
    from lat5.data import parse_watchlist

    watch_items = parse_watchlist(cfg.watchlist_path)
    universe = dedup_universe(watch_items)

    with KiwoomDataStore(cfg.db_path) as store:
        daily_full, minutes_full, foreign_flow_full, strength_full = load_universe_data(
            store, universe
        )

    calendar = build_session_calendar(daily_full, min_coverage=cfg.session_min_coverage)
    start = pd.Timestamp(cfg.start).normalize()
    end = pd.Timestamp(cfg.end).normalize()
    eval_days = [d for d in calendar if start <= d <= end]

    all_records: list[TickerDayRecord] = []
    for eval_day in eval_days:
        all_records.extend(
            run_eval_day(
                eval_day, universe, daily_full, minutes_full, calendar, cfg,
                foreign_flow_full=foreign_flow_full, strength_full=strength_full,
            )
        )

    return {
        "universe": universe,
        "calendar": calendar,
        "eval_days": eval_days,
        "records": all_records,
        "daily_full": daily_full,
        "minutes_full": minutes_full,
    }
