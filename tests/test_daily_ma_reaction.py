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
