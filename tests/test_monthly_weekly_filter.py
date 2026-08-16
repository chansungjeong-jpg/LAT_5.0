import pandas as pd

from lat5.monthly_weekly_filter import crossed_recovery, periods_as_of, recent_recovery


def test_crossed_recovery_requires_previous_close_below_and_current_close_above():
    frame = pd.DataFrame(
        {"close": [90, 95, 110, 120, 130]},
        index=pd.date_range("2026-01-31", periods=5, freq="ME"),
    )
    assert crossed_recovery(frame, 3) is False

    frame.loc[frame.index[-2], "close"] = 80
    assert crossed_recovery(frame, 3) is True


def test_incomplete_current_month_is_not_used_by_completed_period_filter():
    frame = pd.DataFrame(
        {"close": [90] * 10 + [200]},
        index=pd.date_range("2025-10-31", periods=11, freq="ME"),
    )
    completed = frame.loc[frame.index <= pd.Timestamp("2026-07-31")]
    assert completed.index[-1] == pd.Timestamp("2026-07-31")


def test_periods_as_of_includes_current_in_progress_month_for_provisional_status():
    index = list(pd.date_range("2025-10-31", periods=10, freq="ME")) + [pd.Timestamp("2026-08-15")]
    frame = pd.DataFrame(
        {"open": 100, "high": 110, "low": 90, "close": [90] * 10 + [200], "volume": 100},
        index=index,
    )
    weekly, monthly = periods_as_of(frame, pd.Timestamp("2026-08-15"), include_in_progress=True)
    assert monthly.index[-1] == pd.Timestamp("2026-08-31")


def test_recent_recovery_remains_true_when_cross_happened_one_period_ago():
    frame = pd.DataFrame(
        {"close": [100, 100, 100, 80, 120, 125]},
        index=pd.date_range("2025-12-05", periods=6, freq="W-FRI"),
    )
    assert recent_recovery(frame, 3, lookback=2) is True
