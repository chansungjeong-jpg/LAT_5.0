import pandas as pd
import pytest

from lat5.relative_strength import (
    market_average_return,
    n_day_return,
    relative_strength,
)


def _daily(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=index)


def test_n_day_return_compares_latest_close_to_n_sessions_back():
    daily = _daily([100.0] * 10 + [110.0])

    assert n_day_return(daily, days=5) == pytest.approx(0.10)


def test_n_day_return_skips_a_pre_market_placeholder_session():
    """Regression: 2026-09-01 -- collecting before market open leaves a
    trailing row with volume=0 and close carried forward from the prior
    day, which silently shifted the whole N-day window back by one
    session instead of using the actual latest completed close."""
    index = pd.date_range("2026-01-02", periods=12, freq="B")
    closes = [100.0] * 10 + [110.0, 110.0]
    volumes = [1000.0] * 11 + [0.0]
    daily = pd.DataFrame({"close": closes, "volume": volumes}, index=index)

    assert n_day_return(daily, days=5) == pytest.approx(0.10)


def test_n_day_return_none_when_not_enough_history():
    daily = _daily([100.0] * 5)

    assert n_day_return(daily, days=5) is None


def test_market_average_return_is_equal_weighted_across_tickers():
    frames = {
        "A": _daily([100.0] * 5 + [110.0]),  # +10%
        "B": _daily([100.0] * 5 + [90.0]),  # -10%
        "C": _daily([100.0] * 4),  # insufficient history, excluded
    }

    assert market_average_return(frames, days=5) == pytest.approx(0.0)


def test_market_average_return_none_when_no_ticker_has_enough_history():
    frames = {"A": _daily([100.0] * 3)}

    assert market_average_return(frames, days=5) is None


def test_relative_strength_positive_when_stock_beats_market_proxy():
    daily = _daily([100.0] * 5 + [115.0])  # +15%

    result = relative_strength(daily, market_return=0.05, days=5)

    assert result is not None
    assert result.stock_return == pytest.approx(0.15)
    assert result.market_return == pytest.approx(0.05)
    assert result.rs == pytest.approx(0.10)


def test_relative_strength_none_when_market_return_unavailable():
    daily = _daily([100.0] * 5 + [115.0])

    assert relative_strength(daily, market_return=None, days=5) is None


def test_relative_strength_none_when_stock_history_insufficient():
    daily = _daily([100.0] * 3)

    assert relative_strength(daily, market_return=0.05, days=5) is None
