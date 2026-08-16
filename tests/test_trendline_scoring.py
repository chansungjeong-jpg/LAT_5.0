import pandas as pd

from lat5.trendline_breakout import find_trendline_ma_breakout
from lat5.trendline_scoring import score_trendline_candidate


def _frame() -> pd.DataFrame:
    rows = []
    for i in range(30):
        base = 100 + i * 0.4
        rows.append({"open": base, "high": base + 2, "low": base - 2, "close": base + 1, "volume": 100})
    rows[10]["low"] = 100
    rows[15]["low"] = 103
    rows[25]["high"] = 140
    rows[-1].update({"open": 118, "high": 130, "low": 116, "close": 128, "volume": 300,
                     "ema60": 125, "ema120": 115, "atr14": 3})
    rows[-2].update({"close": 110, "ema60": 126, "ema120": 114, "atr14": 3})
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=30, freq="h"))


def test_trendline_breakout_requires_higher_low_and_close_cross():
    signal = find_trendline_ma_breakout(_frame(), left=1, right=1, min_gap_bars=3)
    assert signal is not None
    assert signal.breakout_pos == 29
    assert signal.low_points[1] > signal.low_points[0]


def test_score_has_one_hundred_point_cap_and_exposes_components():
    signal = find_trendline_ma_breakout(_frame(), left=1, right=1, min_gap_bars=3)
    result = score_trendline_candidate(_frame(), signal, weekly_above=True, monthly_above=True)
    assert result.total_score <= 100
    assert result.components["trendline"] > 0
    assert result.components["volume"] > 0
    assert result.hard_blocks == ()
