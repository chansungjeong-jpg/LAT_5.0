from __future__ import annotations

import pandas as pd
import pytest

from lat5.data import daily_ema_context
from lat5.hourly_abc_support import find_hourly_ma60_pullback, strong_hourly_breakout_at
from lat5.location_decision import LocationScoreConfig, build_context


def _empty(columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(columns=columns)
    frame.index = pd.DatetimeIndex([], name="datetime")
    return frame


def test_build_context_with_no_data_returns_safe_defaults():
    daily = _empty(["open", "high", "low", "close", "volume", "amount"])
    hourly = _empty(["open", "high", "low", "close", "volume", "ema60", "ema120"])
    minutes = _empty(["open", "high", "low", "close", "volume", "ema20_5m"])
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=hourly,
        minutes=minutes,
        as_of=pd.Timestamp("2026-08-10"),
        cfg=LocationScoreConfig(),
    )
    assert ctx == {"watchlist_ok": True, "sector_score": None, "pullback_state": "none"}


def _rising_daily(periods: int = 26) -> pd.DataFrame:
    index = pd.date_range("2026-07-01", periods=periods, freq="D")
    closes = [90.0 + i for i in range(periods)]
    return pd.DataFrame(
        {
            "open": [c - 1.0 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 2.0 for c in closes],
            "close": closes,
            "volume": [1000] * periods,
            "amount": [c * 1000 for c in closes],
        },
        index=index,
    )


def test_build_context_tolerates_default_indexed_empty_frames():
    """Real KiwoomDataStore.load_daily/load_minutes return a plain empty
    DataFrame (default RangeIndex, no datetime dtype) for a brand-new ticker
    with zero rows -- not a DatetimeIndex. build_context must not crash."""
    daily = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])
    hourly = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "ema60", "ema120"])
    minutes = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "ema20_5m"])
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=hourly,
        minutes=minutes,
        as_of=pd.Timestamp("2026-08-10"),
        cfg=LocationScoreConfig(),
    )
    assert ctx == {"watchlist_ok": True, "sector_score": None, "pullback_state": "none"}


def test_daily_trend_ok_true_and_distance_positive_in_uptrend():
    daily = _rising_daily()
    as_of = daily.index[-1]
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=_empty(["open", "high", "low", "close", "volume", "ema60", "ema120"]),
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["daily_trend_ok"] is True
    assert ctx["daily_ema10_distance_pct"] > 0


def test_daily_trend_ok_false_and_distance_negative_in_downtrend():
    daily = _rising_daily()
    daily = daily.iloc[::-1].set_axis(daily.index)  # reverse closes, same calendar
    as_of = daily.index[-1]
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=_empty(["open", "high", "low", "close", "volume", "ema60", "ema120"]),
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["daily_trend_ok"] is False
    assert ctx["daily_ema10_distance_pct"] < 0


def test_daily_bull_count_absent_below_ten_prior_rows():
    daily = _rising_daily(periods=10)  # 9 prior + as_of
    as_of = daily.index[-1]
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=_empty(["open", "high", "low", "close", "volume", "ema60", "ema120"]),
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert "daily_bull_count_5" not in ctx
    assert "daily_bull_count_10" not in ctx


def test_daily_bull_count_reports_actual_counts_not_just_pass_fail():
    daily = _rising_daily(periods=26)  # every prior day is bullish (close > open)
    as_of = daily.index[-1]
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=_empty(["open", "high", "low", "close", "volume", "ema60", "ema120"]),
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["daily_bull_count_5"] == 5
    assert ctx["daily_bull_count_10"] == 10


def test_daily_bull_count_reflects_a_mixed_recent_run():
    daily = _rising_daily(periods=26)
    # flip the 3 most recent prior days (positions -2,-3,-4 before as_of) to bearish
    open_col = daily.columns.get_loc("open")
    close_col = daily.columns.get_loc("close")
    for pos in (-2, -3, -4):
        daily.iloc[pos, open_col], daily.iloc[pos, close_col] = (
            daily.iloc[pos, close_col],
            daily.iloc[pos, open_col],
        )
    as_of = daily.index[-1]
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=_empty(["open", "high", "low", "close", "volume", "ema60", "ema120"]),
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["daily_bull_count_5"] == 2
    assert ctx["daily_bull_count_10"] == 7


def test_m60_trend_ok_only_uses_bars_completed_before_session_open():
    as_of = pd.Timestamp("2026-08-05")
    index = pd.DatetimeIndex(
        [pd.Timestamp("2026-08-05 08:00"), pd.Timestamp("2026-08-05 09:00")]
    )
    hourly = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [110.0, 50.0],  # completed bar strong, in-session bar weak
            "volume": [100, 100],
            "ema60": [100.0, 100.0],
            "ema120": [90.0, 90.0],
        },
        index=index,
    )
    ctx = build_context(
        daily=_empty(["open", "high", "low", "close", "volume", "amount"]),
        daily_ema=daily_ema_context(_empty(["open", "high", "low", "close", "volume", "amount"])),
        hourly=hourly,
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["m60_trend_ok"] is True


def _breakout_hourly(periods: int = 30, start: str = "2026-08-01 09:00") -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="h")
    open_ = [100.0] * periods
    high = [102.0] * periods
    low = [98.0] * periods
    close = [99.0] * periods
    volume = [100.0] * periods
    ema60 = [100.0] * periods
    ema120 = [95.0] * periods
    atr20 = [10.0] * periods
    # breakout bar at pos 21 (matches test_hourly_abc_support fixture)
    high[21], close[21], volume[21], ema60[21] = 111.0, 110.0, 200.0, 101.0
    return pd.DataFrame(
        {
            "open": open_, "high": high, "low": low, "close": close,
            "volume": volume, "ema60": ema60, "ema120": ema120, "atr20": atr20,
        },
        index=index,
    )


def test_no_recent_breakout_gives_pullback_state_none():
    hourly = _breakout_hourly()
    hourly = hourly.assign(high=98.0, close=99.0, volume=100.0)  # wipe out the breakout
    as_of = hourly.index[-1].normalize() + pd.Timedelta(days=1)
    ctx = build_context(
        daily=_empty(["open", "high", "low", "close", "volume", "amount"]),
        daily_ema=daily_ema_context(_empty(["open", "high", "low", "close", "volume", "amount"])),
        hourly=hourly,
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["pullback_state"] == "none"
    assert "anchor_volume_ok" not in ctx


def test_breakout_with_valid_pullback_sets_near_ema20_and_volume_flags():
    hourly = _breakout_hourly()
    breakout_pos = 21
    assert strong_hourly_breakout_at(hourly, breakout_pos) is not None
    # pullback bar at pos 23: low near ema60(101), close above ema60, volume < breakout volume
    hourly.iloc[23, hourly.columns.get_loc("low")] = 100.9
    hourly.iloc[23, hourly.columns.get_loc("close")] = 101.5
    hourly.iloc[23, hourly.columns.get_loc("volume")] = 150.0
    hourly.iloc[23, hourly.columns.get_loc("ema60")] = 101.0
    pullback = find_hourly_ma60_pullback(hourly, breakout_pos)
    assert pullback is not None and pullback.pullback_pos == 23

    as_of = hourly.index[-1].normalize() + pd.Timedelta(days=1)
    daily = _rising_daily()
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=hourly,
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["pullback_state"] == "near_ema20"
    assert ctx["anchor_volume_ok"] is True
    assert ctx["pullback_volume_dry"] is True
    assert ctx["bullish_candle_strength_ok"] is True
    assert ctx["breakout_volume_ok"] is False  # no 5m trigger data supplied
    assert ctx["supply_zone_method"] == "swing_high_proxy_v1"
    assert ctx["support_price"] == pytest.approx(100.9)
    assert ctx["resistance_price"] > ctx["price"]
    assert "rr" in ctx


def test_same_day_pullback_is_invisible_without_explicit_cutoff():
    """Documents the day-boundary default: a breakout+pullback that both
    resolve on as_of's own calendar day is invisible to the daily pre-market
    view (session_start = as_of 09:00 excludes all of as_of's own bars)."""
    hourly = _breakout_hourly(start="2026-08-04 00:00")
    breakout_pos = 21
    hourly.iloc[23, hourly.columns.get_loc("low")] = 100.9
    hourly.iloc[23, hourly.columns.get_loc("close")] = 101.5
    hourly.iloc[23, hourly.columns.get_loc("volume")] = 150.0
    hourly.iloc[23, hourly.columns.get_loc("ema60")] = 101.0
    as_of = hourly.index[23].normalize()  # same calendar day as the pullback bar (23:00)
    ctx = build_context(
        daily=_empty(["open", "high", "low", "close", "volume", "amount"]),
        daily_ema=daily_ema_context(_empty(["open", "high", "low", "close", "volume", "amount"])),
        hourly=hourly,
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["pullback_state"] == "none"


def test_same_day_pullback_is_visible_with_explicit_cutoff():
    hourly = _breakout_hourly(start="2026-08-04 00:00")
    breakout_pos = 21
    hourly.iloc[23, hourly.columns.get_loc("low")] = 100.9
    hourly.iloc[23, hourly.columns.get_loc("close")] = 101.5
    hourly.iloc[23, hourly.columns.get_loc("volume")] = 150.0
    hourly.iloc[23, hourly.columns.get_loc("ema60")] = 101.0
    as_of = hourly.index[23].normalize()
    cutoff = hourly.index[23] + pd.Timedelta(hours=1)  # right after the pullback bar closes
    ctx = build_context(
        daily=_empty(["open", "high", "low", "close", "volume", "amount"]),
        daily_ema=daily_ema_context(_empty(["open", "high", "low", "close", "volume", "amount"])),
        hourly=hourly,
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
        cutoff=cutoff,
    )
    assert ctx["pullback_state"] == "near_ema20"
    assert ctx["anchor_volume_ok"] is True


def test_breakout_still_in_progress_before_pullback_window_expires():
    hourly = _breakout_hourly(periods=24)  # only 2 bars after breakout(pos21): 22,23
    as_of = hourly.index[-1].normalize() + pd.Timedelta(days=1)
    ctx = build_context(
        daily=_empty(["open", "high", "low", "close", "volume", "amount"]),
        daily_ema=daily_ema_context(_empty(["open", "high", "low", "close", "volume", "amount"])),
        hourly=hourly,
        minutes=_empty(["open", "high", "low", "close", "volume", "ema20_5m"]),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["pullback_state"] == "in_progress"


def test_breakout_volume_ok_true_when_five_minute_reversal_trigger_found():
    hourly = _breakout_hourly()
    breakout_pos = 21
    hourly.iloc[23, hourly.columns.get_loc("low")] = 100.9
    hourly.iloc[23, hourly.columns.get_loc("close")] = 101.5
    hourly.iloc[23, hourly.columns.get_loc("volume")] = 150.0
    hourly.iloc[23, hourly.columns.get_loc("ema60")] = 101.0
    pullback = find_hourly_ma60_pullback(hourly, breakout_pos)
    confirm_time = hourly.index[pullback.pullback_pos] + pd.Timedelta(hours=1)

    minute_index = pd.date_range(confirm_time, periods=22, freq="5min")
    minutes = pd.DataFrame(
        {
            "open": [101.0] * 20 + [101.0, 102.5],
            "high": [101.2] * 20 + [102.6, 102.7],
            "low": [100.8] * 20 + [100.9, 102.4],
            "close": [101.0] * 20 + [102.5, 102.6],
            "volume": [50.0] * 20 + [500.0, 60.0],
            "ema20_5m": [101.0] * 22,
        },
        index=minute_index,
    )

    as_of = (confirm_time + pd.Timedelta(days=1)).normalize() + pd.Timedelta(hours=9)
    daily = _rising_daily()
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=hourly,
        minutes=minutes,
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["breakout_volume_ok"] is True


def test_m5_ema20_distance_pct_is_signed_not_absolute():
    as_of = pd.Timestamp("2026-08-05 09:00")
    minutes = pd.DataFrame(
        {
            "open": [100.0],
            "high": [100.0],
            "low": [100.0],
            "close": [95.0],
            "volume": [10.0],
            "ema20_5m": [100.0],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2026-08-04 15:25")]),
    )
    ctx = build_context(
        daily=_empty(["open", "high", "low", "close", "volume", "amount"]),
        daily_ema=daily_ema_context(_empty(["open", "high", "low", "close", "volume", "amount"])),
        hourly=_empty(["open", "high", "low", "close", "volume", "ema60", "ema120"]),
        minutes=minutes,
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert ctx["m5_ema20_distance_pct"] == pytest.approx(-0.05)
