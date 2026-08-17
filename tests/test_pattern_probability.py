import numpy as np
import pandas as pd
import pytest

from lat5.pattern_probability import (
    compute_forward_returns,
    evaluate_ticker,
    find_breakout_events,
    split_oos,
    t_stat,
)


def _daily(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes, "volume": volumes}, index=index)


def test_find_breakout_events_requires_seven_percent_and_double_volume():
    closes = [100.0] * 20 + [107.5] + [108.0] * 10
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * 10
    daily = _daily(closes, volumes)

    events = find_breakout_events(daily)

    assert list(events["pos"]) == [20]


def test_find_breakout_events_rejects_big_move_without_volume():
    closes = [100.0] * 20 + [107.5] + [108.0] * 10
    volumes = [1000.0] * 31  # no 2x spike on the breakout day
    daily = _daily(closes, volumes)

    events = find_breakout_events(daily)

    assert events.empty


def test_compute_forward_returns_marks_missing_future_data_as_nan_not_dropped():
    closes = [100.0] * 20 + [107.5] + [108.0] * 7
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * 7
    daily = _daily(closes, volumes)
    events = find_breakout_events(daily)

    returns = compute_forward_returns(daily, events, entry_offset=3, hold_days=(5, 10))

    assert len(returns) == 1
    assert pd.isna(returns["ret_5"].iloc[0])
    assert pd.isna(returns["ret_10"].iloc[0])


def test_compute_forward_returns_computes_correct_ratio():
    closes = (
        [100.0] * 20
        + [110.0]
        + [110.0] * 2
        + [121.0]
        + [110.0] * 4
        + [132.0]
        + [110.0] * 20
    )
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * (len(closes) - 21)
    daily = _daily(closes, volumes)
    events = find_breakout_events(daily)

    returns = compute_forward_returns(daily, events, entry_offset=3, hold_days=(5, 10))

    assert returns["ret_5"].iloc[0] == pytest.approx(132.0 / 121.0 - 1.0)


def test_split_oos_divides_by_event_count_not_calendar_time():
    events = pd.DataFrame({"breakout_date": pd.date_range("2020-01-01", periods=10, freq="D")})
    train, test = split_oos(events, cutoff_frac=0.7)
    assert len(train) == 7
    assert len(test) == 3
    assert train["breakout_date"].max() < test["breakout_date"].min()


def test_t_stat_of_all_zero_returns_is_zero():
    assert t_stat(pd.Series([0.0, 0.0, 0.0])) == 0.0


def test_t_stat_matches_hand_computed_value():
    returns = pd.Series([0.02, 0.04, 0.06, 0.08, 0.10])
    assert t_stat(returns) == pytest.approx(4.2426, abs=0.001)


def test_evaluate_ticker_insufficient_sample_below_min_n():
    closes = [100.0] * 20 + [107.5] + [108.0] * 10
    volumes = [1000.0] * 20 + [2500.0] + [1000.0] * 10
    daily = _daily(closes, volumes)

    verdict = evaluate_ticker(daily, min_n=30, t_threshold=1.99)

    assert verdict.verdict == "INSUFFICIENT_SAMPLE"


def test_evaluate_ticker_pass_requires_both_windows_significant_in_both_splits():
    rng = np.random.default_rng(seed=7)
    n_days = 400
    closes = [100.0]
    volumes = []
    for _ in range(n_days):
        volumes.append(1000.0)
        closes.append(closes[-1] * (1.0 + rng.normal(0.0005, 0.01)))
    closes = closes[1:]
    for k in range(60):
        i = 25 + k * 6
        if i + 15 >= len(closes):
            break
        closes[i] = closes[i - 1] * 1.09
        volumes[i] = 3000.0
        for j in range(1, 14):
            closes[i + j] = closes[i + j - 1] * 1.01
    daily = _daily(closes, volumes)

    verdict = evaluate_ticker(daily, min_n=15, t_threshold=1.5)

    assert verdict.verdict in ("PASS", "PARTIAL")
    assert verdict.hold_5.n_train >= 15
