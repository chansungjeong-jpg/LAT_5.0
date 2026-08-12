import pandas as pd
import pytest

from lat5.daily_ma_reaction import (
    DailyMAReactionInputs,
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


def test_sma_values_use_only_rows_before_as_of():
    frame = frame_with_bars()
    as_of = pd.Timestamp("2026-08-12")
    frame.loc[pd.Timestamp("2026-08-13"), "close"] = 10_000.0

    result = score_daily_reaction(frame, as_of=as_of)

    expected = frame.loc[frame.index <= as_of, "close"]
    assert result.sma5 == pytest.approx(expected.tail(5).mean())
    assert result.sma20 == pytest.approx(expected.tail(20).mean())
    assert result.sma60 == pytest.approx(expected.tail(60).mean())


def test_reaction_marks_missing_ohlcv_columns_unknown():
    frame = frame_with_bars().drop(columns="volume")

    result = score_daily_reaction(frame, as_of=frame.index[-1])

    assert result.status == "UNKNOWN"
    assert "volume" in result.unknown_fields
