import json
import sqlite3

import pandas as pd
import pytest

from lat5.backtest import BacktestConfig, run_hourly_pullback_reversal_baseline
from lat5.data import WatchItem
from lat5.hourly_abc_support import HourlyMA60Pullback
from lat5.location_decision import LocationScoreConfig, evaluate_watchlist_position


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


def _entry_gate_context():
    return {
        "watchlist_ok": True,
        "sector_score": 75,
        "daily_trend_ok": True,
        "weekly_trend_ok": True,
        "m60_trend_ok": True,
        "m60_slope_pct": 0.01,
        "daily_bull_count_5": 5,
        "daily_bull_count_10": 10,
        "anchor_volume_ok": True,
        "pullback_volume_dry": True,
        "breakout_volume_ok": True,
        "bullish_candle_strength_ok": True,
        "pullback_state": "near_ema20",
        "m5_ema20_distance_pct": 0.01,
        "daily_ema10_distance_pct": 0.05,
        "rr": 2.5,
        "overhead_supply_close": False,
        "daily_volume_ratio": 2.5,
        "daily_ma_reaction_score": 0,
        "daily_ma_reaction_state": "NONE",
        "daily_ma_reaction": {
            "reaction": "NONE",
            "score": 0,
            "unknown_fields": [],
        },
    }


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
            "entry_eligible": True,
            "location_score": 90,
            "score_components": {},
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
            "entry_eligible": True,
            "location_score": 90,
            "score_components": {},
            "vetoes": [],
            "unknown_fields": [],
            "m60_rsi14": None,
            "daily_ma_reaction": {"reaction": "UNKNOWN", "score": 0},
            "rr_breakdown": {
                "current_price": 100.0,
                "stop_price": 95.0,
                "target_price": 110.0,
                "rr": 2.0,
            },
            "breakout_resistance_price": None,
            "breakout_entry_price": None,
            "breakout_stop_price": None,
            "breakout_target_price": None,
            "breakout_rr": None,
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
            "entry_eligible": True,
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


@pytest.mark.parametrize(
    ("case", "field", "value", "expected_veto", "expected_unknown"),
    [
        ("watch_high", None, None, None, None),
        ("no_pullback", "pullback_state", "none", "NO_PULLBACK", None),
        ("overheated", "m5_ema20_distance_pct", 0.10, "OVERHEATED", None),
        (
            "weekly_missing",
            "weekly_trend_ok",
            None,
            "ENTRY_PREREQUISITE_UNKNOWN",
            "weekly_trend_ok",
        ),
        (
            "m60_trend_missing",
            "m60_trend_ok",
            None,
            "ENTRY_PREREQUISITE_UNKNOWN",
            "m60_trend_ok",
        ),
        (
            "m60_slope_missing",
            "m60_slope_pct",
            None,
            "ENTRY_PREREQUISITE_UNKNOWN",
            "m60_slope_pct",
        ),
        (
            "daily_missing",
            "daily_trend_ok",
            None,
            "ENTRY_PREREQUISITE_UNKNOWN",
            "daily_trend_ok",
        ),
    ],
)
def test_runner_blocks_ineligible_watch_high_from_trade_and_buy_ledger(
    monkeypatch,
    tmp_path,
    case,
    field,
    value,
    expected_veto,
    expected_unknown,
):
    hourly, minutes = _hourly_and_minutes()

    class Store:
        def load_minutes(self, ticker):
            return minutes

        def load_daily(self, ticker):
            return _empty_daily()

    location_ctx = _entry_gate_context()
    if case == "watch_high":
        location_ctx["breakout_volume_ok"] = False
        location_ctx["daily_volume_ratio"] = 1.7
    elif case in {"no_pullback", "overheated"}:
        location_ctx["breakout_volume_ok"] = False
        location_ctx["daily_volume_ratio"] = 1.7
        location_ctx[field] = value
    else:
        location_ctx["daily_ma_reaction_score"] = 20
        location_ctx["daily_ma_reaction_state"] = "SMA60_UPWARD_CROSS_STRONG_BULL"
        location_ctx["daily_ma_reaction"] = {
            "reaction": "SMA60_UPWARD_CROSS_STRONG_BULL",
            "score": 20,
            "unknown_fields": [],
        }
        location_ctx.pop(field)

    location_result = evaluate_watchlist_position(
        location_ctx, LocationScoreConfig()
    )
    assert location_result["location_score"] >= 70
    assert location_result["state"] == "WATCH_HIGH"
    assert location_result["entry_eligible"] is False

    _apply_common_monkeypatches(monkeypatch, hourly)
    monkeypatch.setattr(
        "lat5.backtest.evaluate_watchlist_position",
        lambda ctx, cfg: location_result,
    )

    output_db = tmp_path / f"{case}.db"
    trades, summary, diagnostics = run_hourly_pullback_reversal_baseline(
        Store(),
        [WatchItem("005930", "Samsung", "Semiconductor")],
        output_db,
        BacktestConfig(commission_bps=0, sell_tax_bps=0, slippage_bps=0),
        start="2026-08-07",
        end="2026-08-07",
        location_cfg=LocationScoreConfig(),
    )

    assert trades.empty
    assert summary["trades"] == 0
    assert diagnostics["location_filtered_count"] == 1
    assert diagnostics["location_decisions"][0]["entry_eligible"] is False
    if expected_veto is not None:
        assert expected_veto in diagnostics["location_decisions"][0]["vetoes"]
    if expected_unknown is not None:
        assert expected_unknown in diagnostics["location_decisions"][0]["unknown_fields"]

    with sqlite3.connect(output_db) as connection:
        buy_count = connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE decision = 'BUY'"
        ).fetchone()[0]
        reject_inputs = connection.execute(
            "SELECT inputs_json FROM decisions "
            "WHERE decision = 'REJECT' AND reason = 'LOCATION_FILTERED'"
        ).fetchone()[0]

    assert buy_count == 0
    evidence = json.loads(reject_inputs)
    assert evidence["location_entry_eligible"] is False
    if expected_veto is not None:
        assert expected_veto in evidence["location_vetoes"]
    if expected_unknown is not None:
        assert expected_unknown in evidence["location_unknown_fields"]
