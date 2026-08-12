import json
import sqlite3

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
    captured_contexts = []

    def _ready_location(ctx, cfg):
        captured_contexts.append(ctx)
        return {
            "state": "BUY_READY",
            "location_score": 90,
            "vetoes": [],
            "unknown_fields": [],
            "daily_ma_reaction": {
                "reaction": ctx["daily_ma_reaction_state"],
                "score": ctx["daily_ma_reaction_score"],
            },
            "rr_breakdown": {
                "current_price": 100.0,
                "stop_price": 95.0,
                "target_price": 110.0,
                "rr": 2.0,
            },
        }

    monkeypatch.setattr("lat5.backtest.evaluate_watchlist_position", _ready_location)

    output_db = tmp_path / "paper.db"
    trades, summary, diagnostics = run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        output_db,
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
        location_cfg=LocationScoreConfig(),
    )

    assert summary["trades"] == 1
    assert diagnostics["location_filtered_count"] == 0
    assert diagnostics["location_gate_enabled"] is True
    assert len(captured_contexts) == 1
    assert captured_contexts[0]["daily_ma_reaction_state"] == "UNKNOWN"
    assert captured_contexts[0]["daily_ma_reaction_score"] == 0
    assert diagnostics["location_decisions"] == [
        {
            "symbol": "005930",
            "name": "Samsung",
            "evaluated_at": str(pd.Timestamp(hourly.index[192]) + pd.Timedelta(hours=1)),
            "final_state": "BUY_READY",
            "location_score": 90,
            "vetoes": [],
            "unknown_fields": [],
            "daily_ma_reaction": {"reaction": "UNKNOWN", "score": 0},
            "rr_breakdown": {
                "current_price": 100.0,
                "stop_price": 95.0,
                "target_price": 110.0,
                "rr": 2.0,
            },
        }
    ]
    with sqlite3.connect(output_db) as connection:
        inputs_json = connection.execute(
            "SELECT inputs_json FROM decisions WHERE decision = 'BUY'"
        ).fetchone()[0]
    decision_inputs = json.loads(inputs_json)
    assert decision_inputs["daily_ma_reaction"] == {
        "reaction": "UNKNOWN",
        "score": 0,
    }
    assert decision_inputs["rr_breakdown"]["current_price"] == 100.0


def test_five_minute_reversal_reject_keeps_location_reaction_and_rr_evidence(
    monkeypatch, tmp_path
):
    hourly, minutes = _hourly_and_minutes()

    class Store:
        def load_minutes(self, ticker):
            return minutes

        def load_daily(self, ticker):
            return _empty_daily()

    _apply_common_monkeypatches(monkeypatch, hourly)
    monkeypatch.setattr(
        "lat5.backtest.find_five_minute_reversal_entry",
        lambda bars, start_time, pullback_low: None,
    )
    daily_reaction = {"reaction": "SMA5_RECOVERY", "score": 6}
    rr_breakdown = {
        "current_price": 100.0,
        "stop_price": 95.0,
        "target_price": 110.0,
        "rr": 2.0,
    }
    monkeypatch.setattr(
        "lat5.backtest.evaluate_watchlist_position",
        lambda ctx, cfg: {
            "state": "BUY_READY",
            "location_score": 86,
            "vetoes": [],
            "unknown_fields": [],
            "daily_ma_reaction": daily_reaction,
            "rr_breakdown": rr_breakdown,
        },
    )

    output_db = tmp_path / "paper.db"
    run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        output_db,
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
        location_cfg=LocationScoreConfig(),
    )

    with sqlite3.connect(output_db) as connection:
        inputs_json = connection.execute(
            "SELECT inputs_json FROM decisions "
            "WHERE reason = 'FIVE_MINUTE_REVERSAL_MISSING_OR_INVALIDATED'"
        ).fetchone()[0]
    decision_inputs = json.loads(inputs_json)
    assert decision_inputs["daily_ma_reaction"] == daily_reaction
    assert decision_inputs["rr_breakdown"] == rr_breakdown


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


def test_runner_fails_closed_when_daily_reaction_data_is_unknown(monkeypatch, tmp_path):
    hourly, minutes = _hourly_and_minutes()

    class Store:
        def load_minutes(self, ticker):
            return minutes

        def load_daily(self, ticker):
            return _empty_daily()

    _apply_common_monkeypatches(monkeypatch, hourly)

    trades, summary, diagnostics = run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        tmp_path / "paper.db",
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
        location_cfg=LocationScoreConfig(),
    )

    assert trades.empty
    assert summary["trades"] == 0
    assert diagnostics["location_filtered_count"] == 1
    assert diagnostics["reason_counts"]["LOCATION_FILTERED"] == 1
