from __future__ import annotations

import pandas as pd
import pytest

from lat5.location_decision import (
    LocationScoreConfig,
    build_context,
    evaluate_watchlist_position,
)


def _full_pass_ctx() -> dict:
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


def _daily_frame(count: int = 70) -> pd.DataFrame:
    index = pd.date_range("2026-06-04", periods=count, freq="D")
    close = pd.Series(range(100, 100 + count), index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 1.0,
            "high": close + 1.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def _daily_reaction_case(case: str) -> tuple[pd.DataFrame, pd.Timestamp]:
    if case == "sma5_break":
        frame = _daily_frame()
        last = frame.index[-1]
        frame.loc[last, ["open", "high", "low", "close"]] = [
            164.5,
            165.2,
            164.0,
            165.0,
        ]
    elif case == "sma20_break":
        frame = _daily_frame(61)
        frame.loc[:, "close"] = 100.0
        frame.loc[:, "open"] = 99.0
        frame.loc[:, "high"] = 101.0
        frame.loc[:, "low"] = 98.0
        last = frame.index[-1]
        frame.loc[last, ["open", "high", "low", "close"]] = [
            98.5,
            99.2,
            98.0,
            99.0,
        ]
    elif case == "recovery":
        frame = _daily_frame()
        previous = frame.index[-2]
        last = frame.index[-1]
        frame.loc[previous, "close"] = 155.0
        frame.loc[last, ["open", "high", "low", "close"]] = [
            165.0,
            171.0,
            169.0,
            170.0,
        ]
    elif case == "unknown":
        frame = _daily_frame(10)
        last = frame.index[-1]
    else:
        raise AssertionError(f"unsupported case: {case}")
    return frame, last + pd.Timedelta(days=1)


def _full_pass_ctx_with_detected_reaction(case: str) -> dict:
    daily, as_of = _daily_reaction_case(case)
    detected = build_context(
        daily=daily,
        daily_ema=pd.DataFrame(),
        hourly=pd.DataFrame(),
        minutes=pd.DataFrame(),
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    ctx = _full_pass_ctx()
    ctx.update(
        {
            "daily_ma_reaction_score": detected["daily_ma_reaction_score"],
            "daily_ma_reaction_state": detected["daily_ma_reaction_state"],
            "daily_ma_reaction_reasons": detected["daily_ma_reaction_reasons"],
            "daily_ma_reaction": detected["daily_ma_reaction"],
        }
    )
    return ctx


def test_not_on_watchlist_forces_ignore():
    result = evaluate_watchlist_position({"watchlist_ok": False}, LocationScoreConfig())
    assert result["state"] == "IGNORE"
    assert result["location_score"] == 0
    assert "NOT_ON_WATCHLIST" in result["vetoes"]


def test_full_pass_reaches_buy_ready_with_max_score():
    ctx = _full_pass_ctx()
    ctx["daily_ma_reaction_score"] = 20
    ctx["daily_ma_reaction_state"] = "SMA60_UPWARD_CROSS_STRONG_BULL"
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert result["location_score"] == 100
    assert result["score_components"] == {
        "volume": 30,
        "m60_location": 20,
        "daily_ma_reaction": 20,
        "weekly_trend": 10,
        "slope": 10,
        "recent_5d_bullish": 5,
        "daily_trend_persistence": 5,
        "daily_sma5_distance": 0,
    }
    assert result["state"] == "BUY_READY"
    assert result["vetoes"] == []


def test_sma5_distance_is_an_auxiliary_score_component():
    ctx = _full_pass_ctx()
    ctx["sma5_distance_score"] = -10

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["score_components"]["daily_sma5_distance"] == -10
    assert result["location_score"] == 70


def test_location_decision_exposes_supply_rr_breakdown():
    ctx = _full_pass_ctx()
    ctx.update({
        "price": 100.0,
        "support_price": 95.0,
        "resistance_price": 115.0,
        "supply_zone_method": "swing_high_proxy_v1",
    })

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["rr_breakdown"] == {
        "current_price": 100.0,
        "stop_price": 95.0,
        "target_price": 115.0,
        "expected_loss": 5.0,
        "expected_reward": 15.0,
        "rr": 3.0,
        "supply_zone_method": "swing_high_proxy_v1",
    }


def test_location_decision_exposes_serialized_daily_ma_reaction_details():
    ctx = _full_pass_ctx()
    ctx.update(
        {
            "daily_ma_reaction_score": 12,
            "daily_ma_reaction_state": "SMA20_PULLBACK_RECOVERY",
            "daily_ma_reaction_reasons": ["SMA20_PULLBACK_RECOVERY"],
            "daily_ma_reaction": {
                "reaction": "SMA20_PULLBACK_RECOVERY",
                "base_score": 8,
                "quality_bonus": 4,
                "score": 12,
                "sma5": 101.0,
                "sma20": 100.0,
                "sma60": 95.0,
                "quality_reasons": ["STRONG_BODY", "GOLDEN_CROSS"],
                "five_day_state": "SMA5_RECOVERY",
            },
        }
    )

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["daily_ma_reaction"] == ctx["daily_ma_reaction"]
    assert result["daily_ma_reaction"]["quality_reasons"] == ["STRONG_BODY", "GOLDEN_CROSS"]


def test_score_in_watch_high_band():
    ctx = {
        "watchlist_ok": True,
        "sector_score": None,
        "daily_trend_ok": True,
        "weekly_trend_ok": True,
        "m60_trend_ok": True,
        "m60_slope_pct": 0.01,
        "daily_bull_count_5": 5,
        "daily_bull_count_10": 10,
        "anchor_volume_ok": True,
        "pullback_volume_dry": False,
        "breakout_volume_ok": True,
        "bullish_candle_strength_ok": False,
        "pullback_state": "in_progress",
        "m5_ema20_distance_pct": 0.01,
        "daily_ema10_distance_pct": 0.05,
        "rr": 2.5,
        "overhead_supply_close": False,
        "daily_volume_ratio": 1.7,
        "daily_ma_reaction_score": 0,
        "daily_ma_reaction_state": "NONE",
    }
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert result["location_score"] == 70
    assert result["state"] == "WATCH_HIGH"


def test_score_in_watch_band():
    ctx = {
        "watchlist_ok": True,
        "sector_score": None,
        "daily_trend_ok": True,
        "weekly_trend_ok": True,
        "m60_trend_ok": False,
        "m60_slope_pct": 0.01,
        "daily_bull_count_5": 0,
        "daily_bull_count_10": 0,
        "anchor_volume_ok": True,
        "pullback_volume_dry": True,
        "breakout_volume_ok": False,
        "bullish_candle_strength_ok": False,
        "pullback_state": "in_progress",
        "m5_ema20_distance_pct": 0.04,
        "daily_ema10_distance_pct": 0.11,
        "rr": 1.5,
        "overhead_supply_close": True,
        "daily_volume_ratio": 1.7,
        "daily_ma_reaction_score": 0,
        "daily_ma_reaction_state": "NONE",
    }
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert result["location_score"] == 45
    assert result["state"] == "WATCH"


def test_low_score_without_veto_is_ignore():
    ctx = {
        "watchlist_ok": True,
        "sector_score": None,
        "daily_trend_ok": False,
        "weekly_trend_ok": False,
        "m60_trend_ok": False,
        "m60_slope_pct": 0.0,
        "daily_bull_count_5": 0,
        "daily_bull_count_10": 0,
        "anchor_volume_ok": False,
        "pullback_volume_dry": False,
        "breakout_volume_ok": False,
        "bullish_candle_strength_ok": False,
        "pullback_state": "in_progress",
        "m5_ema20_distance_pct": 0.04,
        "daily_ema10_distance_pct": 0.11,
        "rr": 1.5,
        "overhead_supply_close": True,
        "daily_ma_reaction_score": 0,
        "daily_ma_reaction_state": "NONE",
    }
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert result["location_score"] == 0
    assert result["state"] == "IGNORE"
    assert result["vetoes"] == []


def test_daily_bull_count_is_graduated_not_binary():
    top = _full_pass_ctx()
    top["daily_bull_count_5"], top["daily_bull_count_10"] = 4, 8
    assert evaluate_watchlist_position(top, LocationScoreConfig())["location_score"] == 80

    passing = _full_pass_ctx()
    passing["daily_bull_count_5"], passing["daily_bull_count_10"] = 3, 5
    result = evaluate_watchlist_position(passing, LocationScoreConfig())
    assert result["location_score"] == 78  # 2pt below max: pass tier (3pt) vs top tier (5pt)
    assert "일봉 양봉 개수 기준 통과" in result["reasons"]

    weak = _full_pass_ctx()
    weak["daily_bull_count_5"], weak["daily_bull_count_10"] = 2, 4
    result = evaluate_watchlist_position(weak, LocationScoreConfig())
    assert result["location_score"] == 78  # SSOT scorer gives two bullish days 3/5 points
    assert "일봉 양봉 개수 회복" in result["wait_for"]

    zero = _full_pass_ctx()
    zero["daily_bull_count_5"], zero["daily_bull_count_10"] = 1, 2
    result = evaluate_watchlist_position(zero, LocationScoreConfig())
    assert result["location_score"] == 75  # full 5pt lost


def test_no_pullback_caps_buy_ready_to_watch():
    """Regression: v1 spec bug #1 — score 80 with no pullback must not reach BUY_READY."""
    ctx = _full_pass_ctx()
    ctx["pullback_state"] = "none"
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert result["location_score"] == 80
    assert "NO_PULLBACK" in result["vetoes"]
    assert result["state"] == "WATCH"
    assert result["entry_eligible"] is False


@pytest.mark.parametrize(
    ("field", "value", "expected_veto"),
    [
        ("pullback_state", "none", "NO_PULLBACK"),
        ("m5_ema20_distance_pct", 0.10, "OVERHEATED"),
    ],
)
def test_score_70_watch_high_preserves_observation_but_blocks_entry(
    field: str, value: object, expected_veto: str
):
    ctx = _full_pass_ctx()
    ctx["breakout_volume_ok"] = False
    ctx["daily_volume_ratio"] = 1.7
    ctx[field] = value

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["location_score"] == 70
    assert result["state"] == "WATCH_HIGH"
    assert expected_veto in result["vetoes"]
    assert result["entry_eligible"] is False


def test_rr_below_minimum_forces_ignore_even_at_high_score():
    """Regression: v1 spec bug #2 — score 90 with RR<1.5 must be REJECT-equivalent (IGNORE)."""
    ctx = _full_pass_ctx()
    ctx["rr"] = 1.2
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert result["location_score"] == 80
    assert "RR_TOO_LOW" in result["vetoes"]
    assert result["state"] == "IGNORE"


def test_overheated_distance_caps_buy_ready_to_watch():
    """Regression: v1 spec bug #3 — score 85 while overheated must not reach BUY_READY."""
    ctx = _full_pass_ctx()
    ctx["m5_ema20_distance_pct"] = 0.10
    ctx["daily_ema10_distance_pct"] = 0.20
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert result["location_score"] == 80
    assert "OVERHEATED" in result["vetoes"]
    assert result["state"] == "WATCH"
    assert result["entry_eligible"] is False


def test_sector_gate_disabled_by_default_does_not_veto_weak_sector():
    ctx = _full_pass_ctx()
    ctx["sector_score"] = 30
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert "SECTOR_WEAK" not in result["vetoes"]
    assert result["state"] != "IGNORE"


def test_sector_gate_enabled_forces_ignore_on_weak_sector():
    ctx = _full_pass_ctx()
    ctx["sector_score"] = 30
    cfg = LocationScoreConfig(sector_gate_enabled=True)
    result = evaluate_watchlist_position(ctx, cfg)
    assert result["state"] == "IGNORE"
    assert "SECTOR_WEAK" in result["vetoes"]
    assert result["location_score"] == 0


def test_missing_sector_score_recorded_as_unknown_not_false():
    ctx = {"watchlist_ok": True}
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert "sector_score" in result["unknown_fields"]
    assert result["sector_score"] is None


@pytest.mark.parametrize(
    ("field", "mode"),
    [
        ("weekly_trend_ok", "missing"),
        ("weekly_trend_ok", "UNKNOWN"),
        ("m60_trend_ok", "missing"),
        ("m60_trend_ok", "UNKNOWN"),
        ("m60_slope_pct", "missing"),
        ("m60_slope_pct", "UNKNOWN"),
        ("daily_trend_ok", "missing"),
        ("daily_trend_ok", "UNKNOWN"),
    ],
)
def test_required_entry_context_unknown_is_preserved_and_fails_closed(
    field: str, mode: str
):
    ctx = _full_pass_ctx()
    if mode == "missing":
        ctx.pop(field)
    else:
        ctx[field] = mode

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert field in result["unknown_fields"]
    assert "ENTRY_PREREQUISITE_UNKNOWN" in result["vetoes"]
    assert result["state"] == "WATCH_HIGH"
    assert result["entry_eligible"] is False


def test_buy_ready_with_confirmed_prerequisites_is_entry_eligible():
    result = evaluate_watchlist_position(_full_pass_ctx(), LocationScoreConfig())

    assert result["state"] == "BUY_READY"
    assert result["vetoes"] == []
    assert result["entry_eligible"] is True


def test_reasons_and_wait_for_are_populated():
    result = evaluate_watchlist_position(_full_pass_ctx(), LocationScoreConfig())
    assert "20EMA 부근 눌림 위치" in result["reasons"]
    assert result["wait_for"] == []

    ctx = _full_pass_ctx()
    ctx["pullback_state"] = "none"
    result = evaluate_watchlist_position(ctx, LocationScoreConfig())
    assert "눌림 위치 대기" in result["wait_for"]


@pytest.mark.parametrize(
    ("reaction", "reaction_score", "expected_score"),
    [
        ("NONE", 0, 80),
        ("SMA5_HOLD", 3, 83),
        ("SMA5_RECOVERY", 6, 86),
        ("SMA60_UPWARD_CROSS_STRONG_BULL", 20, 100),
    ],
)
def test_daily_reactions_use_the_actual_ssot_twenty_point_component(
    reaction: str, reaction_score: int, expected_score: int
):
    ctx = _full_pass_ctx()
    ctx["daily_ma_reaction_state"] = reaction
    ctx["daily_ma_reaction_score"] = reaction_score

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["location_score"] == expected_score
    assert result["location_score"] <= 100


def test_strong_daily_reaction_can_promote_watch_high_to_buy_ready():
    ctx = _full_pass_ctx()
    ctx["pullback_volume_dry"] = False
    ctx["breakout_volume_ok"] = False
    ctx["bullish_candle_strength_ok"] = False
    ctx["daily_volume_ratio"] = 1.1
    ctx["daily_ma_reaction_state"] = "SMA60_UPWARD_CROSS_STRONG_BULL"
    ctx["daily_ma_reaction_score"] = 20

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["location_score"] == 80
    assert result["state"] == "BUY_READY"


def test_sma5_close_break_deducts_score_and_applies_watch_pressure():
    ctx = _full_pass_ctx()
    ctx["daily_ma_reaction_state"] = "SMA5_CLOSE_BREAK"
    ctx["daily_ma_reaction_score"] = -4

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["location_score"] == 76
    assert result["state"] == "WATCH"
    assert "DAILY_MA_WATCH_PRESSURE" in result["vetoes"]


def test_rsi_value_is_observation_only_for_entry_eligibility():
    ctx = _full_pass_ctx()
    ctx["daily_ma_reaction_score"] = 20
    ctx["daily_ma_reaction_state"] = "SMA60_UPWARD_CROSS_STRONG_BULL"
    ctx["daily_ma_reaction"] = {
        "reaction": "SMA60_UPWARD_CROSS_STRONG_BULL",
        "score": 20,
        "rsi14": 72.0,
        "unknown_fields": [],
    }

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["state"] == "BUY_READY"
    assert result["entry_eligible"] is True
    assert "DAILY_MA_WATCH_PRESSURE" not in result["vetoes"]
    assert "DAILY_MA_HARD_BLOCK" not in result["vetoes"]


def test_rsi_unknown_field_does_not_create_a_daily_ma_gate():
    ctx = _full_pass_ctx()
    ctx["daily_ma_reaction_score"] = 20
    ctx["daily_ma_reaction_state"] = "SMA60_UPWARD_CROSS_STRONG_BULL"
    ctx["daily_ma_reaction"] = {
        "reaction": "SMA60_UPWARD_CROSS_STRONG_BULL",
        "score": 20,
        "rsi14": None,
        "unknown_fields": ["rsi14"],
    }

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["state"] == "BUY_READY"
    assert result["entry_eligible"] is True
    assert "DAILY_MA_REACTION_UNKNOWN" not in result["vetoes"]
    assert "daily_ma_reaction.rsi14" not in result["unknown_fields"]


def test_sma20_close_break_vetoes_buy_ready():
    ctx = _full_pass_ctx()
    ctx["daily_ma_reaction_state"] = "SMA20_CLOSE_BREAK"
    ctx["daily_ma_reaction_score"] = -8

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["state"] == "IGNORE"
    assert "DAILY_MA_HARD_BLOCK" in result["vetoes"]


def test_unknown_daily_reaction_vetoes_buy_ready_and_exposes_unknown_fields():
    ctx = _full_pass_ctx()
    ctx["daily_ma_reaction_state"] = "UNKNOWN"
    ctx["daily_ma_reaction_score"] = 0
    ctx["daily_ma_reaction"] = {
        "reaction": "UNKNOWN",
        "score": 0,
        "unknown_fields": ["SMA60", "ATR14"],
    }

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["state"] == "IGNORE"
    assert "DAILY_MA_REACTION_UNKNOWN" in result["vetoes"]
    assert "daily_ma_reaction.SMA60" in result["unknown_fields"]
    assert "daily_ma_reaction.ATR14" in result["unknown_fields"]


@pytest.mark.parametrize(
    ("case", "expected_reaction", "expected_component", "expected_state"),
    [
        ("sma5_break", "SMA5_CLOSE_BREAK", -4, "WATCH"),
        ("sma20_break", "SMA20_CLOSE_BREAK", -8, "IGNORE"),
        ("recovery", "SMA5_RECOVERY", 12, "BUY_READY"),
        ("unknown", "UNKNOWN", 0, "IGNORE"),
    ],
)
def test_evaluator_component_matches_detected_reaction_payload_score(
    case: str,
    expected_reaction: str,
    expected_component: int,
    expected_state: str,
):
    ctx = _full_pass_ctx_with_detected_reaction(case)

    result = evaluate_watchlist_position(ctx, LocationScoreConfig())

    assert result["daily_ma_reaction"]["reaction"] == expected_reaction
    assert result["daily_ma_reaction"]["score"] == expected_component
    assert result["score_components"]["daily_ma_reaction"] == expected_component
    assert result["state"] == expected_state
