import pandas as pd

from lat5.hourly_breakout import (
    hourly_or_breakout_at,
    simulate_hourly_breakout_trade,
)
from lat5.backtest import BacktestConfig
from lat5.backtest import run_hourly_breakout_baseline
from lat5.data import WatchItem
from lat5.hourly_breakout import HourlyBreakoutSignal


def _hourly_frame(current_close=106.0, current_volume=150.0):
    index = pd.date_range("2026-08-01 09:00", periods=22, freq="h")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 22,
            "high": [107.0] * 22,
            "low": [94.0] * 22,
            "close": [100.0] * 20 + [99.0, current_close],
            "volume": [100.0] * 21 + [current_volume],
            "ema60": [100.0] * 21 + [101.0],
            "ema120": [95.0] * 22,
        },
        index=index,
    )
    return frame


def test_hourly_or_breakout_accepts_one_line_cross_with_both_lines_below_close():
    signal = hourly_or_breakout_at(_hourly_frame(), 21, volume_multiple=1.5)

    assert signal is not None
    assert signal.crossed == ("ema60",)
    assert signal.stop_reference == 94.0
    assert signal.volume_ratio == 1.5


def test_hourly_or_breakout_requires_close_above_both_lines():
    frame = _hourly_frame(current_close=100.5)

    assert hourly_or_breakout_at(frame, 21, volume_multiple=1.5) is None


def test_hourly_or_breakout_requires_1_5x_prior_20_bar_volume():
    assert hourly_or_breakout_at(
        _hourly_frame(current_volume=149.0), 21, volume_multiple=1.5
    ) is None


def test_hourly_breakout_trade_enters_next_bar_and_targets_two_r():
    bars = pd.DataFrame(
        {
            "open": [102.0, 106.0],
            "high": [105.0, 117.0],
            "low": [100.0, 105.0],
            "close": [104.0, 116.0],
        },
        index=pd.date_range("2026-08-07 10:00", periods=2, freq="5min"),
    )

    trade = simulate_hourly_breakout_trade(
        bars,
        entry_pos=0,
        stop=95.0,
        equity=100_000.0,
        config=BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
    )

    assert trade is not None
    assert trade["entry_price"] == 102.0
    assert trade["stop_price"] == 95.0
    assert trade["target_price"] == 116.0
    assert trade["exit_price"] == 116.0
    assert trade["exit_reason"] == "TARGET"


def test_hourly_breakout_baseline_wires_completed_hour_to_next_five_minute_bar(
    monkeypatch, tmp_path
):
    hourly_index = pd.date_range("2026-08-02 08:00", periods=122, freq="h")
    hourly = pd.DataFrame(
        {
            "open": [100.0] * 122,
            "high": [107.0] * 122,
            "low": [96.0] * 121 + [95.0],
            "close": [100.0] * 122,
            "volume": [100.0] * 121 + [200.0],
            "amount": [10_000.0] * 122,
        },
        index=hourly_index,
    )
    hourly.index = hourly.index[:-1].append(pd.DatetimeIndex(["2026-08-07 09:00"]))
    minutes = pd.DataFrame(
        {
            "open": [102.0, 106.0],
            "high": [105.0, 117.0],
            "low": [100.0, 105.0],
            "close": [104.0, 116.0],
            "volume": [100, 100],
            "amount": [10_400, 11_600],
        },
        index=pd.date_range("2026-08-07 10:00", periods=2, freq="5min"),
    )

    class Store:
        def load_minutes(self, ticker):
            return minutes

    monkeypatch.setattr("lat5.backtest.aggregate_60m", lambda bars: hourly)
    monkeypatch.setattr(
        "lat5.backtest.hourly_or_breakout_at",
        lambda frame, pos, volume_multiple: (
            HourlyBreakoutSignal(pos, ("ema60",), 95.0, 2.0)
            if pos == len(frame) - 1
            else None
        ),
    )

    trades, summary, diagnostics = run_hourly_breakout_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        tmp_path / "paper.db",
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
    )

    assert summary["trades"] == 1
    assert trades.iloc[0]["entry_time"] == pd.Timestamp("2026-08-07 10:00")
    assert diagnostics["breakout_count"] == 1
