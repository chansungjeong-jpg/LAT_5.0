import pandas as pd
import pytest

from lat5.data import WatchItem
from lat5.edge_validation import (
    RS_DAYS_DEFAULT,
    build_session_calendar,
    dedup_universe,
    evaluate_flow_signal,
    evaluate_location,
    evaluate_recovery,
    evaluate_rsi_recovery_signal,
    resolve_entry,
    resolve_entry_close,
    resolve_outcome,
    resolve_outcome_close_to_open,
    truncate_daily,
    truncate_minutes,
)
from lat5.location_decision import LocationScoreConfig


def _ohlcv(closes: list[float], *, freq: str = "B", start: str = "2024-01-02") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(closes), freq=freq)
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        index=index,
    )


# ---------------------------------------------------------------------------
# dedup_universe
# ---------------------------------------------------------------------------


def test_dedup_universe_collapses_sector_duplicates():
    items = [
        WatchItem("005930", "삼성전자", "반도체"),
        WatchItem("005930", "삼성전자", "대형주"),
        WatchItem("000660", "SK하이닉스", "반도체"),
    ]

    universe = dedup_universe(items)

    assert [u.ticker for u in universe] == ["005930", "000660"]
    assert universe[0].sectors == ("반도체", "대형주")


def test_dedup_universe_does_not_duplicate_repeated_sector():
    items = [WatchItem("005930", "삼성전자", "반도체"), WatchItem("005930", "삼성전자", "반도체")]

    universe = dedup_universe(items)

    assert universe[0].sectors == ("반도체",)


# ---------------------------------------------------------------------------
# session calendar
# ---------------------------------------------------------------------------


def test_build_session_calendar_requires_majority_coverage():
    common_days = pd.date_range("2026-08-10", periods=5, freq="B")
    frames = {
        "A": pd.DataFrame({"close": [1] * 5}, index=common_days),
        "B": pd.DataFrame({"close": [1] * 5}, index=common_days),
        # C only has one day -- should not manufacture a session by itself
        "C": pd.DataFrame({"close": [1]}, index=[common_days[2]]),
    }

    calendar = build_session_calendar(frames, min_coverage=0.5)

    assert calendar == list(common_days)


def test_build_session_calendar_excludes_minority_days():
    days = pd.date_range("2026-08-10", periods=3, freq="B")
    frames = {
        "A": pd.DataFrame({"close": [1, 1, 1]}, index=days),
        "B": pd.DataFrame({"close": [1]}, index=[days[0]]),  # only trades day 0
        "C": pd.DataFrame({"close": [1]}, index=[days[0]]),
    }

    calendar = build_session_calendar(frames, min_coverage=0.5)

    assert calendar == [days[0]]


# ---------------------------------------------------------------------------
# truncate_daily
# ---------------------------------------------------------------------------


def test_truncate_daily_includes_as_of_date_itself():
    daily = _ohlcv([100, 101, 102, 103, 104])
    as_of = daily.index[2]

    truncated = truncate_daily(daily, as_of)

    assert truncated.index[-1] == as_of
    assert len(truncated) == 3


# ---------------------------------------------------------------------------
# no-lookahead: recovery
# ---------------------------------------------------------------------------


def test_evaluate_recovery_is_invariant_to_future_bars_appended_after_as_of():
    """Regression for c-handoff.md problem 1: computing a historical day's
    recovery state must never change depending on what happens afterward."""
    closes = [100.0] * 300 + [70.0] * 20 + [130.0] * 20
    daily_full = _ohlcv(closes)
    as_of = daily_full.index[339]  # inside the recovered tail

    baseline = evaluate_recovery(truncate_daily(daily_full, as_of), as_of)

    mutated_tail = _ohlcv(closes[: 340] + [1.0] * 10)  # wildly different future
    mutated = evaluate_recovery(truncate_daily(mutated_tail, as_of), as_of)

    assert baseline == mutated


def test_evaluate_recovery_insufficient_history_reason():
    empty = pd.DataFrame(
        columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([])
    )

    result = evaluate_recovery(empty, pd.Timestamp("2026-08-13"))

    assert result.passed is False
    assert result.reason == "INSUFFICIENT_HISTORY"


def test_evaluate_recovery_not_recovered_when_rolling_window_too_short():
    daily = _ohlcv([100.0] * 5)

    result = evaluate_recovery(daily, daily.index[-1])

    assert result.passed is False
    assert result.reason == "NOT_RECOVERED"


# ---------------------------------------------------------------------------
# no-lookahead: location score
# ---------------------------------------------------------------------------


def _minute_bars(days: list[pd.Timestamp], price: float = 100.0) -> pd.DataFrame:
    frames = []
    for day in days:
        times = pd.date_range(
            day + pd.Timedelta(hours=9), day + pd.Timedelta(hours=15, minutes=25), freq="5min"
        )
        frames.append(
            pd.DataFrame(
                {
                    "open": [price] * len(times),
                    "high": [price * 1.001] * len(times),
                    "low": [price * 0.999] * len(times),
                    "close": [price] * len(times),
                    "volume": [100.0] * len(times),
                    "amount": [price * 100.0] * len(times),
                },
                index=times,
            )
        )
    return pd.concat(frames).sort_index()


def test_evaluate_location_is_invariant_to_future_minute_bars():
    business_days = list(pd.bdate_range("2026-06-01", periods=40))
    cutoff_day = business_days[30]
    cutoff = cutoff_day + pd.Timedelta(hours=16)

    daily_full = _ohlcv([100.0] * len(business_days), start="2026-06-01")
    daily_trunc = truncate_daily(daily_full, cutoff_day)
    cfg = LocationScoreConfig()

    minutes_before = _minute_bars(business_days[:31])  # through cutoff_day only
    baseline = evaluate_location(
        daily_trunc, minutes_before, as_of=cutoff_day, cutoff=cutoff, cfg=cfg
    )

    minutes_with_future = _minute_bars(business_days)  # includes days after cutoff
    minutes_with_future_trunc = minutes_with_future.loc[minutes_with_future.index <= cutoff]
    mutated = evaluate_location(
        daily_trunc, minutes_with_future_trunc, as_of=cutoff_day, cutoff=cutoff, cfg=cfg
    )

    assert baseline == mutated
    assert baseline.score is not None


def test_evaluate_location_reports_missing_minute_data():
    daily = _ohlcv([100.0] * 5)
    empty_minutes = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    result = evaluate_location(
        daily, empty_minutes, as_of=daily.index[-1], cutoff=daily.index[-1], cfg=LocationScoreConfig()
    )

    assert result.score is None
    assert result.reason == "MINUTE_DATA_MISSING"


# ---------------------------------------------------------------------------
# entry resolution
# ---------------------------------------------------------------------------


def test_resolve_entry_fills_at_next_session_open():
    daily_full = _ohlcv([100, 101, 102, 103])
    calendar = list(daily_full.index)
    eval_day = daily_full.index[1]

    entry = resolve_entry(daily_full, eval_day, calendar)

    assert entry.status == "FILLED"
    assert entry.entry_date == daily_full.index[2]
    assert entry.entry_price == pytest.approx(102.0)


def test_resolve_entry_unfilled_when_ticker_has_no_row_on_next_session():
    calendar_days = pd.date_range("2026-08-10", periods=5, freq="B")
    # ticker's own data is missing exactly the day after eval_day (halt)
    daily_full = pd.DataFrame(
        {"open": [100, 999, 103], "high": [100, 999, 103], "low": [100, 999, 103], "close": [100, 999, 103]},
        index=[calendar_days[0], calendar_days[2], calendar_days[3]],
    )
    eval_day = calendar_days[0]

    entry = resolve_entry(daily_full, eval_day, list(calendar_days))

    assert entry.status == "UNFILLED"
    assert entry.reason == "NO_TICKER_ROW_ON_NEXT_SESSION"


def test_resolve_entry_does_not_skip_ahead_to_a_later_session():
    """A halted ticker must not silently fill several days later."""
    calendar_days = pd.date_range("2026-08-10", periods=5, freq="B")
    daily_full = pd.DataFrame(
        {"open": [100, 103], "high": [100, 103], "low": [100, 103], "close": [100, 103]},
        index=[calendar_days[0], calendar_days[3]],
    )

    entry = resolve_entry(daily_full, calendar_days[0], list(calendar_days))

    assert entry.status == "UNFILLED"


def test_resolve_entry_unfilled_when_no_future_session_in_calendar():
    daily_full = _ohlcv([100, 101])
    calendar = list(daily_full.index)

    entry = resolve_entry(daily_full, calendar[-1], calendar)

    assert entry.status == "UNFILLED"
    assert entry.reason == "NO_NEXT_SESSION_IN_CALENDAR"


# ---------------------------------------------------------------------------
# outcome resolution
# ---------------------------------------------------------------------------


def test_resolve_outcome_mature_computes_gross_and_net_return():
    closes = [100.0] * 11
    closes[9] = 110.0  # 10th row counting entry day as day 1 -> exit_pos=9
    daily_full = _ohlcv(closes)
    calendar = list(daily_full.index)

    outcome = resolve_outcome(
        daily_full, entry_pos=0, entry_price=100.0, entry_date=daily_full.index[0],
        hold_days=10, calendar=calendar,
        commission_bps=1.5, sell_tax_bps=20.0, slippage_bps=5.0,
    )

    assert outcome.status == "MATURE"
    assert outcome.gross_return == pytest.approx(0.10)
    cost_fraction = (2 * 1.5 + 20.0 + 2 * 5.0) / 10_000.0
    assert outcome.net_return == pytest.approx(0.10 - cost_fraction)


def test_resolve_outcome_immature_when_calendar_has_not_caught_up():
    daily_full = _ohlcv([100.0] * 3)  # only 3 rows -- can't reach hold_days=10
    calendar = list(daily_full.index)  # calendar also only has 3 sessions total

    outcome = resolve_outcome(
        daily_full, entry_pos=0, entry_price=100.0, entry_date=daily_full.index[0],
        hold_days=10, calendar=calendar,
    )

    assert outcome.status == "IMMATURE"
    assert outcome.gross_return is None


def test_resolve_outcome_data_gap_when_calendar_passed_but_ticker_row_missing():
    daily_full = _ohlcv([100.0] * 3)  # ticker stopped reporting after 3 rows
    calendar = list(pd.date_range(daily_full.index[0], periods=15, freq="B"))  # market kept going

    outcome = resolve_outcome(
        daily_full, entry_pos=0, entry_price=100.0, entry_date=daily_full.index[0],
        hold_days=10, calendar=calendar,
    )

    assert outcome.status == "DATA_GAP"
    assert outcome.gross_return is None


# ---------------------------------------------------------------------------
# priority-1 A/B: close-to-open fill scheme
# ---------------------------------------------------------------------------


def _open_close_frame(opens: list[float], closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=len(opens), freq="B")
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 1 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 1 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1000.0] * len(opens),
        },
        index=index,
    )


def test_resolve_entry_close_fills_at_signal_days_own_close():
    daily_full = _open_close_frame([100, 102, 104], [101, 103, 105])
    eval_day = daily_full.index[0]

    entry = resolve_entry_close(daily_full, eval_day)

    assert entry.status == "FILLED"
    assert entry.entry_date == eval_day
    assert entry.entry_price == pytest.approx(101.0)
    assert entry.entry_pos == 0


def test_resolve_entry_close_unfilled_when_eval_day_row_missing():
    daily_full = _open_close_frame([100, 104], [101, 105])
    daily_full = daily_full.rename(index={daily_full.index[0]: pd.Timestamp("2099-01-01")})

    entry = resolve_entry_close(daily_full, pd.Timestamp("2026-01-02"))

    assert entry.status == "UNFILLED"
    assert entry.reason == "NO_TICKER_ROW_ON_EVAL_DAY"


def test_close_to_open_and_next_open_schemes_share_the_same_exit_row():
    """Both fill rules must reference the identical exit session -- the A/B
    isolates the overnight-vs-intraday leg swap, not a different window."""
    opens = [100, 102, 104, 106, 108]
    closes = [101, 103, 105, 107, 109]
    daily_full = _open_close_frame(opens, closes)
    calendar = list(daily_full.index)
    eval_day = daily_full.index[0]

    old_entry = resolve_entry(daily_full, eval_day, calendar)
    old_outcome = resolve_outcome(
        daily_full, old_entry.entry_pos, old_entry.entry_price, old_entry.entry_date,
        hold_days=3, calendar=calendar, commission_bps=0, sell_tax_bps=0, slippage_bps=0,
    )

    new_entry = resolve_entry_close(daily_full, eval_day)
    new_outcome = resolve_outcome_close_to_open(
        daily_full, new_entry.entry_pos, new_entry.entry_price, new_entry.entry_date,
        hold_days=3, calendar=calendar, commission_bps=0, sell_tax_bps=0, slippage_bps=0,
    )

    assert old_outcome.exit_date == new_outcome.exit_date == daily_full.index[3]
    assert old_outcome.exit_price == pytest.approx(closes[3])
    assert new_outcome.exit_price == pytest.approx(opens[3])
    assert old_outcome.gross_return == pytest.approx(closes[3] / opens[1] - 1.0)
    assert new_outcome.gross_return == pytest.approx(opens[3] / closes[0] - 1.0)


def test_resolve_outcome_close_to_open_immature_when_calendar_has_not_caught_up():
    daily_full = _open_close_frame([100.0] * 3, [101.0] * 3)
    calendar = list(daily_full.index)

    outcome = resolve_outcome_close_to_open(
        daily_full, entry_pos=0, entry_price=101.0, entry_date=daily_full.index[0],
        hold_days=10, calendar=calendar,
    )

    assert outcome.status == "IMMATURE"
    assert outcome.gross_return is None


# ---------------------------------------------------------------------------
# H-002: flow signal (foreign net cumulative + execution strength)
# ---------------------------------------------------------------------------


def _foreign_flow(values: list[float], *, start: str = "2026-08-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"foreign_net": values}, index=index)


def _strength_minutes(day_values: dict[str, list[float]]) -> pd.DataFrame:
    frames = []
    for day, values in day_values.items():
        times = pd.date_range(pd.Timestamp(day) + pd.Timedelta(hours=9), periods=len(values), freq="1min")
        frames.append(pd.DataFrame({"strength": values}, index=times))
    return pd.concat(frames).sort_index()


def test_evaluate_flow_signal_computes_cumulative_net_and_strength_mean():
    foreign_flow = _foreign_flow([100.0, -50.0, 200.0, 0.0, 300.0])  # sum=550, last 5
    strength = _strength_minutes({"2026-08-07": [40.0, 60.0, 50.0]})
    as_of = pd.Timestamp("2026-08-07")

    result = evaluate_flow_signal(foreign_flow, strength, as_of=as_of, lookback_days=5)

    assert result.foreign_net_cum == pytest.approx(550.0)
    assert result.strength_mean == pytest.approx(50.0)
    assert result.reason is None


def test_evaluate_flow_signal_none_when_lookback_window_incomplete():
    foreign_flow = _foreign_flow([100.0, -50.0, 200.0])  # only 3 rows, need 5
    strength = pd.DataFrame(columns=["strength"], index=pd.DatetimeIndex([]))

    result = evaluate_flow_signal(foreign_flow, strength, as_of=pd.Timestamp("2026-08-05"), lookback_days=5)

    assert result.foreign_net_cum is None
    assert result.strength_mean is None
    assert result.reason == "FLOW_DATA_MISSING"


def test_evaluate_flow_signal_reason_none_when_only_one_source_available():
    foreign_flow = _foreign_flow([100.0] * 5)
    strength = pd.DataFrame(columns=["strength"], index=pd.DatetimeIndex([]))

    result = evaluate_flow_signal(foreign_flow, strength, as_of=pd.Timestamp("2026-08-07"), lookback_days=5)

    assert result.foreign_net_cum == pytest.approx(500.0)
    assert result.strength_mean is None
    assert result.reason is None  # at least one source known -- not a full outage


def test_evaluate_flow_signal_strength_mean_only_uses_eval_days_own_minutes():
    foreign_flow = pd.DataFrame(columns=["foreign_net"], index=pd.DatetimeIndex([]))
    strength = _strength_minutes({"2026-08-06": [10.0, 10.0], "2026-08-07": [80.0, 90.0]})

    result = evaluate_flow_signal(foreign_flow, strength, as_of=pd.Timestamp("2026-08-07"))

    assert result.strength_mean == pytest.approx(85.0)


def test_evaluate_flow_signal_is_invariant_to_future_rows_via_caller_truncation():
    """Same contract as evaluate_recovery/evaluate_location: whatever the
    caller truncates to before calling must fully determine the result --
    rows appended after as_of/cutoff in the untruncated source must not
    change it."""
    as_of = pd.Timestamp("2026-08-10")
    cutoff = as_of + pd.Timedelta(hours=16)

    foreign_flow_full = _foreign_flow([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 999.0, 999.0])
    strength_full = _strength_minutes(
        {"2026-08-10": [30.0, 40.0], "2026-08-11": [999.0, 999.0]}
    )

    baseline = evaluate_flow_signal(
        truncate_daily(foreign_flow_full.iloc[:6], as_of),
        truncate_minutes(strength_full[strength_full.index.normalize() <= as_of], cutoff),
        as_of=as_of,
    )
    with_future = evaluate_flow_signal(
        truncate_daily(foreign_flow_full, as_of),
        truncate_minutes(strength_full, cutoff),
        as_of=as_of,
    )

    assert baseline == with_future
    assert with_future.foreign_net_cum == pytest.approx(2 + 3 + 4 + 5 + 6)
    assert with_future.strength_mean == pytest.approx(35.0)


def test_resolve_outcome_close_to_open_data_gap_when_ticker_stopped_reporting():
    daily_full = _open_close_frame([100.0] * 3, [101.0] * 3)
    calendar = list(pd.date_range(daily_full.index[0], periods=15, freq="B"))

    outcome = resolve_outcome_close_to_open(
        daily_full, entry_pos=0, entry_price=101.0, entry_date=daily_full.index[0],
        hold_days=10, calendar=calendar,
    )

    assert outcome.status == "DATA_GAP"
    assert outcome.gross_return is None


# ---------------------------------------------------------------------------
# RSI recovery signal (H-003, see .claude/skills/edge-loop/research_log/hypotheses.md)
# ---------------------------------------------------------------------------


def _daily_close_frame(closes: list[float], *, start: str = "2026-06-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=index)


def test_evaluate_rsi_recovery_signal_true_when_previous_oversold_and_current_recovers():
    # 16 strictly declining bars (previous-day RSI == 0.0, deeply oversold),
    # then a large up day for the as-of (current) bar.
    declining = [100.0 - i for i in range(16)]
    daily_trunc = _daily_close_frame(declining + [declining[-1] + 20.0])

    result = evaluate_rsi_recovery_signal(daily_trunc, as_of=daily_trunc.index[-1])

    assert result.rsi14_prev == pytest.approx(0.0)
    assert result.rsi14 == pytest.approx(60.6060606060606)
    assert result.signal is True
    assert result.reason is None


def test_evaluate_rsi_recovery_signal_false_when_no_crossing():
    # Flat closes -> RSI stays near the midline on both days, no threshold crossed.
    flat = [100.0] * 17
    daily_trunc = _daily_close_frame(flat)

    result = evaluate_rsi_recovery_signal(daily_trunc, as_of=daily_trunc.index[-1])

    assert result.signal is False
    assert result.reason is None


def test_evaluate_rsi_recovery_signal_none_when_insufficient_bars():
    # Wilder RSI(14) needs at least 15 bars for the previous-day value and
    # 16 for the current -- 10 bars is not enough for either.
    daily_trunc = _daily_close_frame([100.0 + i for i in range(10)])

    result = evaluate_rsi_recovery_signal(daily_trunc, as_of=daily_trunc.index[-1])

    assert result.signal is None
    assert result.rsi14 is None
    assert result.reason == "RSI_DATA_MISSING"


def test_evaluate_rsi_recovery_signal_is_invariant_to_future_rows_via_caller_truncation():
    """Same contract as evaluate_recovery/evaluate_flow_signal: whatever the
    caller truncates to before calling must fully determine the result --
    rows appended after as_of in the untruncated source must not change it."""
    declining = [100.0 - i for i in range(16)]
    full = declining + [declining[-1] + 20.0, 999.0, 999.0]
    daily_full = _daily_close_frame(full)
    as_of = daily_full.index[16]

    baseline = evaluate_rsi_recovery_signal(truncate_daily(daily_full.iloc[:17], as_of), as_of=as_of)
    with_future = evaluate_rsi_recovery_signal(truncate_daily(daily_full, as_of), as_of=as_of)

    assert baseline == with_future
    assert with_future.signal is True
