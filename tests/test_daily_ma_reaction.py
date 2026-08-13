import pandas as pd
import pytest

from lat5.daily_ma_reaction import (
    DailyMAReactionInputs,
    score_daily_ma_reaction,
    score_daily_reaction,
)


def frame_with_bars(count: int = 70) -> pd.DataFrame:
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


def rsi_recovery_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(70)
    closes = [100.0, *range(99, 86, -1), 91.0, 94.0]
    frame.loc[frame.index[-len(closes):], "close"] = closes
    frame.loc[:, "open"] = frame["close"] - 1.0
    frame.loc[:, "high"] = frame["close"] + 1.0
    frame.loc[:, "low"] = frame["close"] - 2.0
    return frame, frame.index[-1] + pd.Timedelta(days=1)


def test_rsi_uses_wilder_fourteen_period_value_from_completed_bars():
    frame, as_of = rsi_recovery_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.rsi14 == pytest.approx(30.621547440354206)


def test_rsi_requires_fifteen_completed_closes_and_fails_closed():
    frame = frame_with_bars(14)

    result = score_daily_reaction(frame, as_of=frame.index[-1] + pd.Timedelta(days=1))

    assert result.status == "UNKNOWN"
    assert result.rsi14 is None
    assert "rsi14" in result.unknown_fields


def test_rsi_ignores_current_day_and_future_daily_bars():
    frame, as_of = rsi_recovery_fixture()
    expected = score_daily_reaction(frame, as_of=as_of)
    frame.loc[as_of, ["open", "high", "low", "close", "volume"]] = [1.0, 1_000.0, 0.1, 1_000.0, 1.0]

    actual = score_daily_reaction(frame, as_of=as_of)

    assert actual.rsi14 == expected.rsi14


def test_rsi_cannot_change_daily_reaction_score():
    frame = frame_with_bars(70)
    frame.loc[:, "close"] = 100.0
    closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0, 89.0, 88.0, 80.0, 105.0]
    frame.loc[frame.index[-len(closes):], "close"] = closes
    frame.loc[:, "open"] = frame["close"] - 1.0
    frame.loc[:, "high"] = frame["close"] + 1.0
    frame.loc[:, "low"] = frame["close"] - 2.0
    frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = [99.0, 106.0, 98.0, 105.0]

    result = score_daily_reaction(frame, as_of=frame.index[-1] + pd.Timedelta(days=1))

    assert result.base_score == 10
    assert result.quality_bonus == 8
    assert result.total_score == 18


def sixty_cross_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [100.0, 104.0, 99.0, 103.0]
    return frame, last + pd.Timedelta(days=1)


def test_sixty_sma_upward_cross_with_strong_bullish_bar_scores_ten():
    frame, as_of = sixty_cross_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA60_UPWARD_CROSS_STRONG_BULL"
    assert result.base_score == 10
    assert result.five_day_state == "SMA5_HOLD"


def test_sma60_cross_accepts_previous_close_equal_to_previous_sma60():
    frame, as_of = sixty_cross_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA60_UPWARD_CROSS_STRONG_BULL"
    assert result.base_score == 10


def test_sma60_current_close_equal_to_sma60_is_not_an_upward_cross():
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    last = frame.index[-1]

    result = score_daily_reaction(frame, as_of=last + pd.Timedelta(days=1))

    assert result.reaction == "SMA5_HOLD"
    assert result.reaction != "SMA60_UPWARD_CROSS_STRONG_BULL"


@pytest.mark.parametrize(
    ("open_price", "close", "expected_reason"),
    [
        (102.5, 103.0, "atr_body_ratio_below_0_8"),
        (101.0, 102.0, "recent_body_percentile_below_p80"),
    ],
    ids=("weak_atr_body", "weak_recent_body_percentile"),
)
def test_sma60_bullish_cross_without_strong_body_is_not_strong_bull(
    open_price: float, close: float, expected_reason: str
):
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [
        open_price,
        104.0,
        99.0,
        close,
    ]

    result = score_daily_reaction(frame, as_of=last + pd.Timedelta(days=1))

    assert result.reaction != "SMA60_UPWARD_CROSS_STRONG_BULL", expected_reason
    assert result.base_score != 10


def twenty_pullback_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(61)
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [155.0, 161.0, 150.7, 160.0]
    return frame, last + pd.Timedelta(days=1)


def test_twenty_sma_pullback_recovery_scores_eight():
    frame, as_of = twenty_pullback_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA20_PULLBACK_RECOVERY"
    assert result.base_score == 8


def twenty_pullback_boundary_fixture(low_offset: float = 0.0) -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, ["open", "high", "low", "close"]] = [99.5, 101.5, 98.5, 100.5]
    frame.loc[last, ["open", "high", "low", "close"]] = [100.5, 102.0, 100.798214285714 + low_offset, 101.0]
    return frame, last + pd.Timedelta(days=1)


def test_sma20_pullback_accepts_exactly_quarter_atr_low_distance():
    frame, as_of = twenty_pullback_boundary_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA20_PULLBACK_RECOVERY"
    assert result.base_score == 8


def test_sma20_pullback_rejects_low_just_outside_quarter_atr_distance():
    frame, as_of = twenty_pullback_boundary_fixture(low_offset=1e-6)

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA5_HOLD"
    assert result.reaction != "SMA20_PULLBACK_RECOVERY"


def test_sma20_close_break_is_the_representative_hard_break():
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [98.5, 99.2, 98.0, 99.0]

    result = score_daily_reaction(frame, as_of=last + pd.Timedelta(days=1))

    assert result.reaction == "SMA20_CLOSE_BREAK"
    assert result.base_score == -8
    assert result.quality_bonus == 0
    assert result.quality_reasons == ()
    assert result.total_score == -8


def five_recovery_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(70)
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, "close"] = 155.0
    frame.loc[last, ["open", "high", "low", "close"]] = [165.0, 171.0, 169.0, 170.0]
    return frame, last + pd.Timedelta(days=1)


def test_five_sma_break_then_next_day_recovery_scores_six():
    frame, as_of = five_recovery_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA5_RECOVERY"
    assert result.base_score == 6


def five_recovery_equal_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, "close"] = 99.0
    frame.loc[last, ["open", "high", "low", "close"]] = [99.0, 100.5, 98.5, 99.75]
    return frame, last + pd.Timedelta(days=1)


def test_sma5_recovery_accepts_current_close_equal_to_sma5():
    frame, as_of = five_recovery_equal_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA5_RECOVERY"
    assert result.base_score == 6


def five_break_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(70)
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [164.5, 165.2, 164.0, 165.0]
    return frame, last + pd.Timedelta(days=1)


def test_five_sma_close_break_is_deduction_not_unknown_or_hard_reject():
    frame, as_of = five_break_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA5_CLOSE_BREAK"
    assert result.base_score == -4
    assert result.quality_bonus == 0
    assert result.quality_reasons == ()
    assert result.total_score == -4


def five_break_equal_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(70)
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, "close"] = 165.5
    frame.loc[last, ["open", "high", "low", "close"]] = [162.0, 163.0, 159.0, 160.0]
    return frame, last + pd.Timedelta(days=1)


def test_sma5_break_accepts_previous_close_equal_to_previous_sma5():
    frame, as_of = five_break_equal_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA5_CLOSE_BREAK"
    assert result.base_score == -4


@pytest.mark.parametrize(
    ("previous_close", "current_close", "expected_reaction", "expected_score"),
    [(100.5, 101.0, "SMA5_HOLD", 3), (99.0, 99.0, "NONE", 0)],
    ids=("above_sma5", "below_sma5"),
)
def test_sma5_same_side_reports_actual_hold_state(
    previous_close: float,
    current_close: float,
    expected_reaction: str,
    expected_score: int,
):
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, "close"] = previous_close
    frame.loc[last, ["open", "high", "low", "close"]] = [current_close - 1.0, current_close + 1.0, current_close - 2.0, current_close]

    result = score_daily_reaction(frame, as_of=last + pd.Timedelta(days=1))

    assert result.reaction == expected_reaction
    assert result.base_score == expected_score


def overlapping_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, "close"] = 99.0
    frame.loc[last, ["open", "high", "low", "close"]] = [100.0, 104.0, 102.0, 103.0]
    return frame, last + pd.Timedelta(days=1)


def test_multiple_reactions_use_only_highest_priority_reaction():
    frame, as_of = overlapping_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.reaction == "SMA60_UPWARD_CROSS_STRONG_BULL"
    assert result.base_score == 10


def test_intraday_low_below_sma5_without_close_break_is_not_a_break():
    frame = frame_with_bars(70)
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [160.0, 171.0, 150.0, 170.0]

    result = score_daily_reaction(frame, as_of=last + pd.Timedelta(days=1))

    assert result.reaction == "SMA5_HOLD"
    assert "CLOSE_BREAK" not in result.reaction


def test_daily_ma_reaction_inputs_are_public_contract_dataclass():
    frame = frame_with_bars()
    inputs = DailyMAReactionInputs(frame, frame.index[-1])

    assert inputs.daily is frame
    assert inputs.as_of == frame.index[-1]


def test_reaction_requires_at_least_sixty_completed_daily_bars():
    short_frame = frame_with_bars(20)

    result = score_daily_reaction(short_frame, as_of=short_frame.index[-1])

    assert result.status == "UNKNOWN"
    assert "SMA60" in result.unknown_fields


def test_plan_public_api_is_available_and_legacy_name_is_compatibility_alias():
    frame = frame_with_bars()
    as_of = frame.index[-1] + pd.Timedelta(days=1)

    canonical = score_daily_ma_reaction(frame, as_of=as_of)
    legacy = score_daily_reaction(frame, as_of=as_of)

    assert canonical == legacy
    assert score_daily_reaction is score_daily_ma_reaction


def test_sma_values_use_only_completed_dates_before_as_of():
    frame = frame_with_bars()
    as_of = pd.Timestamp("2026-08-12 10:00")
    frame.loc[as_of, "close"] = 10_000.0

    result = score_daily_ma_reaction(frame, as_of=as_of)

    expected = frame.loc[frame.index.normalize() < as_of.normalize(), "close"]
    assert result.status == "KNOWN"
    assert result.sma5 == pytest.approx(expected.tail(5).mean())
    assert result.sma20 == pytest.approx(expected.tail(20).mean())
    assert result.sma60 == pytest.approx(expected.tail(60).mean())


def test_reaction_marks_missing_ohlcv_column_unknown():
    frame = frame_with_bars().drop(columns="volume")

    result = score_daily_ma_reaction(frame, as_of=frame.index[-1])

    assert result.status == "UNKNOWN"
    assert "volume" in result.unknown_fields


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("bad_value", [None, float("nan"), float("inf")])
def test_reaction_rejects_non_finite_completed_ohlcv_values(field, bad_value):
    frame = frame_with_bars()
    frame.loc[frame.index[-1], field] = bad_value
    as_of = frame.index[-1] + pd.Timedelta(days=1)

    result = score_daily_ma_reaction(frame, as_of=as_of)

    assert result.status == "UNKNOWN"
    assert field in result.unknown_fields


def test_future_non_finite_ohlcv_values_are_outside_the_validation_window():
    frame = frame_with_bars()
    future = frame.index[-1] + pd.Timedelta(days=1)
    frame.loc[future, "volume"] = float("inf")

    result = score_daily_ma_reaction(frame, as_of=future)

    assert result.status == "KNOWN"
    assert result.sma60 is not None
    assert "volume" not in result.unknown_fields


def test_reaction_fails_closed_for_non_datetime_index():
    frame = frame_with_bars()
    frame.index = range(len(frame))

    result = score_daily_ma_reaction(frame, as_of=pd.Timestamp("2026-08-13"))

    assert result.status == "UNKNOWN"
    assert "datetime_index" in result.unknown_fields


def test_reaction_fails_closed_for_unsorted_datetime_index():
    frame = frame_with_bars().iloc[::-1]

    result = score_daily_ma_reaction(frame, as_of=pd.Timestamp("2026-08-13"))

    assert result.status == "UNKNOWN"
    assert "datetime_index" in result.unknown_fields


def test_reaction_fails_closed_for_multiple_timestamps_on_one_date():
    frame = frame_with_bars()
    same_day = frame.index[-1] + pd.Timedelta(hours=12)
    frame.loc[same_day] = frame.iloc[-1]

    result = score_daily_ma_reaction(
        frame, as_of=frame.index[-1] + pd.Timedelta(days=1)
    )

    assert result.status == "UNKNOWN"
    assert "datetime_index" in result.unknown_fields


def test_reaction_fails_closed_for_duplicate_daily_timestamp():
    frame = pd.concat([frame_with_bars(), frame_with_bars().iloc[[-1]]])

    result = score_daily_ma_reaction(
        frame, as_of=frame.index[-1] + pd.Timedelta(days=1)
    )

    assert result.status == "UNKNOWN"
    assert "datetime_index" in result.unknown_fields


def strong_body_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(70)
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [165.0, 172.0, 164.0, 170.0]
    return frame, last + pd.Timedelta(days=1)


def test_strong_body_uses_atr_and_recent_body_percentile():
    frame, as_of = strong_body_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert "STRONG_BODY" in result.quality_reasons
    assert result.quality_components["strong_body"] == 3
    assert result.quality_bonus >= 3
    assert result.quality_method == "body_atr_ratio_and_recent_20_body_p80"


def close_near_high_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(70)
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [165.0, 172.0, 164.0, 170.0]
    return frame, last + pd.Timedelta(days=1)


def test_close_near_high_adds_two_points():
    frame, as_of = close_near_high_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert "CLOSE_NEAR_HIGH" in result.quality_reasons
    assert result.quality_components["close_near_high"] == 2


def test_none_reaction_never_receives_candle_quality_bonus():
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, "close"] = 99.0
    frame.loc[last, ["open", "high", "low", "close"]] = [90.0, 99.1, 89.0, 99.0]

    result = score_daily_reaction(frame, as_of=last + pd.Timedelta(days=1))

    assert result.reaction == "NONE"
    assert result.quality_bonus == 0
    assert result.quality_reasons == ()
    assert result.total_score == 0


@pytest.mark.parametrize(
    ("close", "expected"),
    [(169.6, 2), (169.599999, 0)],
    ids=("exactly_70_percent", "just_below_70_percent"),
)
def test_close_near_high_uses_inclusive_70_percent_boundary(close: float, expected: int):
    frame, as_of = close_near_high_fixture()
    last = frame.index[-1]
    frame.loc[last, "close"] = close

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.quality_components["close_near_high"] == expected


def reaction_slope_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame, as_of = sixty_cross_fixture()
    return frame, as_of


def test_reaction_slope_up_adds_three_points_for_representative_sma():
    frame, as_of = reaction_slope_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert "REACTION_SLOPE_UP" in result.quality_reasons
    assert result.quality_components["reaction_slope_up"] == 3


def golden_cross_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [100.0, 121.0, 99.0, 120.0]
    return frame, last + pd.Timedelta(days=1)


def test_sma20_crosses_above_sma60_adds_two_point_golden_cross_bonus():
    frame, as_of = golden_cross_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert "GOLDEN_CROSS" in result.quality_reasons
    assert result.quality_components["golden_cross"] == 2


def test_golden_cross_requires_strict_current_sma20_above_sma60():
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    last = frame.index[-1]
    frame.loc[last, ["open", "high", "low", "close"]] = [100.0, 101.0, 99.0, 100.0]

    result = score_daily_reaction(frame, as_of=last + pd.Timedelta(days=1))

    assert result.quality_components["golden_cross"] == 0


def all_quality_conditions_fixture() -> tuple[pd.DataFrame, pd.Timestamp]:
    frame = frame_with_bars(61)
    frame.loc[:, "close"] = 100.0
    frame.loc[:, "open"] = 99.0
    frame.loc[:, "high"] = 101.0
    frame.loc[:, "low"] = 98.0
    previous = frame.index[-2]
    last = frame.index[-1]
    frame.loc[previous, ["open", "high", "low", "close"]] = [99.0, 101.0, 98.0, 99.0]
    frame.loc[last, ["open", "high", "low", "close"]] = [100.0, 125.0, 99.0, 120.0]
    return frame, last + pd.Timedelta(days=1)


def test_reaction_total_is_capped_at_twenty():
    frame, as_of = all_quality_conditions_fixture()

    result = score_daily_reaction(frame, as_of=as_of)

    assert result.quality_bonus > 0
    assert result.total_score <= 20
