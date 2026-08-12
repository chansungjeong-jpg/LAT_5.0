import pandas as pd

from lat5.hourly_abc_support import (
    HourlyABCSupport,
    HourlyMA60Pullback,
    find_five_minute_reversal_entry,
    find_hourly_ma60_pullback,
    simulate_pullback_reversal_trade,
    find_five_minute_c_high_entry,
    find_hourly_abc_support,
    strong_hourly_breakout_at,
)
from lat5.backtest import (
    BacktestConfig,
    run_hourly_abc_support_baseline,
    run_hourly_pullback_reversal_baseline,
)
from lat5.data import WatchItem


def test_strong_hourly_breakout_requires_distance_body_close_and_volume():
    index = pd.date_range("2026-08-01 09:00", periods=22, freq="h")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 21 + [100.0],
            "high": [102.0] * 21 + [111.0],
            "low": [98.0] * 21 + [99.0],
            "close": [99.0] * 21 + [110.0],
            "volume": [100.0] * 21 + [200.0],
            "ema60": [100.0] * 21 + [101.0],
            "ema120": [95.0] * 22,
            "atr20": [10.0] * 22,
        },
        index=index,
    )

    signal = strong_hourly_breakout_at(frame, 21)

    assert signal is not None
    assert signal.crossed == ("ema60",)


def test_strong_hourly_breakout_rejects_weak_volume():
    index = pd.date_range("2026-08-01 09:00", periods=22, freq="h")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 22,
            "high": [102.0] * 21 + [111.0],
            "low": [98.0] * 21 + [99.0],
            "close": [99.0] * 21 + [110.0],
            "volume": [100.0] * 21 + [199.0],
            "ema60": [100.0] * 21 + [101.0],
            "ema120": [95.0] * 22,
            "atr20": [10.0] * 22,
        },
        index=index,
    )
    assert strong_hourly_breakout_at(frame, 21) is None


def _abc_frame(c_low=102.0, c_close=103.0):
    index = pd.date_range("2026-08-07 09:00", periods=8, freq="h")
    return pd.DataFrame(
        {
            "open": [108, 107, 103, 106, 111, 108, 104, 106],
            "high": [112, 109, 105, 111, 115, 110, 108, 109],
            "low": [106, 104, 100, 104, 108, 105, c_low, 104],
            "close": [110, 105, 103, 109, 112, 107, c_close, 108],
            "volume": [200, 100, 100, 100, 100, 100, 100, 100],
            "ema60": [101, 101, 101, 101, 101, 101, 102, 102],
            "ema120": [96] * 8,
        },
        index=index,
    )


def test_hourly_abc_requires_higher_c_low_and_ma60_support():
    setup = find_hourly_abc_support(_abc_frame(), breakout_pos=0)

    assert setup is not None
    assert (setup.a_pos, setup.b_pos, setup.c_pos, setup.confirm_pos) == (2, 4, 6, 7)
    assert setup.c_high == 108.0
    assert setup.c_low == 102.0


def test_hourly_abc_rejects_c_below_a_or_away_from_ma60():
    assert find_hourly_abc_support(_abc_frame(c_low=99.0), breakout_pos=0) is None
    assert find_hourly_abc_support(_abc_frame(c_low=105.0, c_close=106.0), breakout_pos=0) is None


def test_hourly_pullback_accepts_second_through_sixth_bar_ma60_support_with_lower_volume():
    frame = _abc_frame().copy()
    frame.loc[:, "ema60"] = 102.0
    frame.loc[:, "volume"] = [200, 180, 150, 140, 130, 120, 110, 100]
    frame.iloc[2, frame.columns.get_loc("low")] = 101.5
    frame.iloc[2, frame.columns.get_loc("close")] = 103.0

    setup = find_hourly_ma60_pullback(frame, breakout_pos=0)

    assert setup is not None
    assert setup.pullback_pos == 2
    assert setup.pullback_low == 101.5


def test_five_minute_entry_waits_for_close_above_c_high_then_uses_next_open():
    bars = pd.DataFrame(
        {
            "open": [106, 107, 109],
            "high": [108, 110, 112],
            "low": [105, 106, 108],
            "close": [107, 109, 111],
        },
        index=pd.date_range("2026-08-07 14:00", periods=3, freq="5min"),
    )

    trigger_pos, entry_pos = find_five_minute_c_high_entry(
        bars, start_time=pd.Timestamp("2026-08-07 14:00"), c_high=108.0, c_low=102.0
    )

    assert trigger_pos == 1
    assert entry_pos == 2


def test_five_minute_entry_expires_when_c_low_breaks_first():
    bars = pd.DataFrame(
        {
            "open": [106, 103, 109],
            "high": [107, 104, 112],
            "low": [103, 100, 108],
            "close": [104, 101, 111],
        },
        index=pd.date_range("2026-08-07 14:00", periods=3, freq="5min"),
    )

    assert find_five_minute_c_high_entry(
        bars, start_time=bars.index[0], c_high=108.0, c_low=102.0
    ) is None


def test_five_minute_reversal_requires_three_bar_high_bullish_close_and_volume():
    index = pd.date_range("2026-08-07 12:30", periods=24, freq="5min")
    bars = pd.DataFrame(
        {
            "open": [100.0] * 21 + [100.0, 103.0, 106.0],
            "high": [102.0] * 21 + [104.0, 106.0, 108.0],
            "low": [99.0] * 24,
            "close": [101.0] * 21 + [103.0, 105.0, 107.0],
            "volume": [100.0] * 22 + [150.0, 100.0],
        },
        index=index,
    )

    trigger_pos, entry_pos = find_five_minute_reversal_entry(
        bars,
        start_time=index[20],
        pullback_low=98.0,
    )

    assert trigger_pos == 22
    assert entry_pos == 23


def test_pullback_trade_sells_half_at_one_r_then_remainder_at_two_r():
    bars = pd.DataFrame(
        {
            "open": [100.0, 104.0, 108.0],
            "high": [104.0, 106.0, 111.0],
            "low": [99.0, 103.0, 107.0],
            "close": [103.0, 105.0, 110.0],
            "ema20_5m": [98.0, 99.0, 100.0],
        },
        index=pd.date_range("2026-08-07 13:00", periods=3, freq="5min"),
    )

    trade = simulate_pullback_reversal_trade(
        bars,
        entry_pos=0,
        stop=95.0,
        equity=1_000_000.0,
        config=BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
    )

    assert trade is not None
    assert trade["partial_exit_price"] == 105.0
    assert trade["remaining_exit_price"] == 110.0
    assert trade["exit_reason"] == "PARTIAL_1R+TARGET_2R"


def test_pullback_trade_moves_remaining_stop_to_breakeven_after_one_r():
    bars = pd.DataFrame(
        {
            "open": [100.0, 104.0],
            "high": [106.0, 104.0],
            "low": [99.0, 99.0],
            "close": [105.0, 100.0],
            "ema20_5m": [98.0, 98.0],
        },
        index=pd.date_range("2026-08-07 13:00", periods=2, freq="5min"),
    )

    trade = simulate_pullback_reversal_trade(
        bars, entry_pos=0, stop=95.0, equity=1_000_000.0,
        config=BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
    )

    assert trade is not None
    assert trade["remaining_exit_price"] == 100.0
    assert trade["exit_reason"] == "PARTIAL_1R+BREAKEVEN"


def test_pullback_trade_exits_remaining_position_on_five_minute_ema20_close_break():
    bars = pd.DataFrame(
        {
            "open": [100.0, 104.0],
            "high": [106.0, 105.0],
            "low": [99.0, 101.0],
            "close": [105.0, 102.0],
            "ema20_5m": [98.0, 103.0],
        },
        index=pd.date_range("2026-08-07 13:00", periods=2, freq="5min"),
    )

    trade = simulate_pullback_reversal_trade(
        bars, entry_pos=0, stop=95.0, equity=1_000_000.0,
        config=BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
    )

    assert trade is not None
    assert trade["remaining_exit_price"] == 102.0
    assert trade["exit_reason"] == "PARTIAL_1R+EMA20_EXIT"


def test_pullback_trade_time_exits_when_half_r_is_not_reached_within_sixty_minutes():
    bars = pd.DataFrame(
        {
            "open": [100.0] * 12,
            "high": [102.0] * 12,
            "low": [99.0] * 12,
            "close": [101.0] * 12,
            "ema20_5m": [98.0] * 12,
        },
        index=pd.date_range("2026-08-07 13:00", periods=12, freq="5min"),
    )

    trade = simulate_pullback_reversal_trade(
        bars, entry_pos=0, stop=95.0, equity=1_000_000.0,
        config=BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
    )

    assert trade is not None
    assert trade["exit_time"] == bars.index[11]
    assert trade["exit_reason"] == "TIME_60M"


def test_hourly_abc_support_baseline_enters_after_confirmed_c_high_break(
    monkeypatch, tmp_path
):
    hourly_index = pd.date_range("2026-08-01 00:00", periods=130, freq="h")
    hourly = pd.DataFrame(
        {
            "open": [100.0] * 130,
            "high": [110.0] * 130,
            "low": [95.0] * 130,
            "close": [105.0] * 130,
            "volume": [100.0] * 130,
            "amount": [10_000.0] * 130,
        },
        index=hourly_index,
    )
    confirm_time = hourly.index[125] + pd.Timedelta(hours=1)
    minutes = pd.DataFrame(
        {
            "open": [106.0, 108.0, 110.0, 120.0],
            "high": [108.0, 110.0, 115.0, 143.0],
            "low": [104.0, 106.0, 108.0, 119.0],
            "close": [107.0, 109.0, 112.0, 142.0],
            "volume": [100, 100, 100, 100],
            "amount": [10_700, 10_900, 11_200, 14_200],
        },
        index=pd.date_range(confirm_time, periods=4, freq="5min"),
    )

    class Store:
        def load_minutes(self, ticker):
            return minutes

    monkeypatch.setattr("lat5.backtest.aggregate_60m", lambda bars: hourly)
    monkeypatch.setattr(
        "lat5.backtest.strong_hourly_breakout_at",
        lambda frame, pos: object() if pos == 120 else None,
    )
    monkeypatch.setattr(
        "lat5.backtest.find_hourly_abc_support",
        lambda frame, breakout_pos: HourlyABCSupport(
            breakout_pos, 121, 123, 124, 125, 108.0, 95.0, 96.0
        ),
    )

    trades, summary, diagnostics = run_hourly_abc_support_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        tmp_path / "paper.db",
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
    )

    assert summary["trades"] == 1
    assert trades.iloc[0]["entry_time"] == minutes.index[2]
    assert diagnostics["abc_support_count"] == 1


def test_hourly_pullback_reversal_runner_wires_pullback_to_five_minute_entry(
    monkeypatch, tmp_path
):
    hourly_index = pd.date_range(end="2026-08-07 11:00", periods=200, freq="h")
    hourly = pd.DataFrame(
        {
            "open": [100.0] * 200,
            "high": [110.0] * 200,
            "low": [95.0] * 200,
            "close": [105.0] * 200,
            "volume": [100.0] * 200,
            "amount": [10_000.0] * 200,
        },
        index=hourly_index,
    )
    minutes = pd.DataFrame(
        {
            "open": [100.0 + pos for pos in range(24)],
            "high": [102.0 + pos for pos in range(24)],
            "low": [99.0 + pos for pos in range(24)],
            "close": [101.0 + pos for pos in range(24)],
            "volume": [100.0] * 24,
            "amount": [10_000.0] * 24,
        },
        index=pd.date_range("2026-08-07 12:00", periods=24, freq="5min"),
    )

    class Store:
        def load_minutes(self, ticker):
            return minutes

    monkeypatch.setattr("lat5.backtest.aggregate_60m", lambda bars: hourly)
    monkeypatch.setattr(
        "lat5.backtest.strong_hourly_breakout_at",
        lambda frame, pos: object() if pos in (120, 190) else None,
    )
    monkeypatch.setattr(
        "lat5.backtest.find_hourly_ma60_pullback",
        lambda frame, breakout_pos: HourlyMA60Pullback(
            breakout_pos, breakout_pos + 2, 110.0, 95.0, 96.0
        ),
    )
    monkeypatch.setattr(
        "lat5.backtest.find_five_minute_reversal_entry",
        lambda bars, start_time, pullback_low: (20, 21),
    )

    trades, summary, diagnostics = run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        tmp_path / "paper.db",
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
    )

    assert summary["trades"] == 1
    assert trades.iloc[0]["entry_time"] == minutes.index[21]
    assert diagnostics["strong_breakout_count"] == 1
    assert diagnostics["pullback_count"] == 1
