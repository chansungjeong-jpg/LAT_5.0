import pandas as pd

from lat5.data import drop_incomplete_trailing_session


def _daily(volumes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-08-20", periods=len(volumes), freq="B")
    return pd.DataFrame(
        {
            "open": [100.0] * len(volumes),
            "high": [100.0] * len(volumes),
            "low": [100.0] * len(volumes),
            "close": [100.0] * len(volumes),
            "volume": volumes,
        },
        index=index,
    )


def test_drops_a_single_trailing_zero_volume_placeholder_session():
    daily = _daily([500.0, 600.0, 700.0, 0.0])

    result = drop_incomplete_trailing_session(daily)

    assert len(result) == 3
    assert result["volume"].iloc[-1] == 700.0


def test_keeps_a_zero_volume_day_buried_earlier_in_history():
    daily = _daily([500.0, 0.0, 700.0, 800.0])

    result = drop_incomplete_trailing_session(daily)

    assert len(result) == 4


def test_no_trailing_zero_leaves_frame_unchanged():
    daily = _daily([500.0, 600.0, 700.0])

    result = drop_incomplete_trailing_session(daily)

    assert len(result) == 3


def test_empty_frame_passes_through():
    daily = _daily([])

    result = drop_incomplete_trailing_session(daily)

    assert result.empty


def test_all_zero_volume_drops_everything():
    daily = _daily([0.0, 0.0])

    result = drop_incomplete_trailing_session(daily)

    assert result.empty


def test_frame_without_volume_column_passes_through_unchanged():
    daily = pd.DataFrame({"close": [100.0, 101.0]})

    result = drop_incomplete_trailing_session(daily)

    assert len(result) == 2
