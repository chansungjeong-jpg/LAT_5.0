import pandas as pd

from lat5.backtest import BacktestConfig, run_hourly_pullback_reversal_baseline
from lat5.data import WatchItem
from lat5.hourly_abc_support import HourlyMA60Pullback
from lat5.location_decision import LocationScoreConfig


def _hourly_and_minutes():
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
    return hourly, minutes


def _empty_daily():
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])


def _apply_common_monkeypatches(monkeypatch, hourly):
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


def test_runner_skips_candidate_when_location_state_not_ready(monkeypatch, tmp_path):
    hourly, minutes = _hourly_and_minutes()

    class Store:
        def load_minutes(self, ticker):
            return minutes

        def load_daily(self, ticker):
            return _empty_daily()

    _apply_common_monkeypatches(monkeypatch, hourly)
    monkeypatch.setattr(
        "lat5.backtest.evaluate_watchlist_position",
        lambda ctx, cfg: {"state": "WATCH", "location_score": 50, "vetoes": []},
    )

    trades, summary, diagnostics = run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        tmp_path / "paper.db",
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
        location_cfg=LocationScoreConfig(),
    )

    assert summary["trades"] == 0
    assert diagnostics["location_filtered_count"] == 1
    assert diagnostics["reason_counts"]["LOCATION_FILTERED"] == 1


def test_runner_allows_candidate_when_location_state_ready(monkeypatch, tmp_path):
    hourly, minutes = _hourly_and_minutes()

    class Store:
        def load_minutes(self, ticker):
            return minutes

        def load_daily(self, ticker):
            return _empty_daily()

    _apply_common_monkeypatches(monkeypatch, hourly)
    monkeypatch.setattr(
        "lat5.backtest.evaluate_watchlist_position",
        lambda ctx, cfg: {"state": "BUY_READY", "location_score": 90, "vetoes": []},
    )

    trades, summary, diagnostics = run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        tmp_path / "paper.db",
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
        location_cfg=LocationScoreConfig(),
    )

    assert summary["trades"] == 1
    assert diagnostics["location_filtered_count"] == 0
    assert diagnostics["location_gate_enabled"] is True


def test_runner_default_behavior_unchanged_when_location_cfg_omitted(monkeypatch, tmp_path):
    hourly, minutes = _hourly_and_minutes()

    class Store:
        def load_minutes(self, ticker):
            return minutes

        def load_daily(self, ticker):
            raise AssertionError("load_daily must not be called when location_cfg is None")

    _apply_common_monkeypatches(monkeypatch, hourly)

    trades, summary, diagnostics = run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        tmp_path / "paper.db",
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
    )

    assert summary["trades"] == 1
    assert diagnostics["location_gate_enabled"] is False
