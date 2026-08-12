from datetime import date

import pandas as pd
import pytest

from lat5.us_featured_data import featured_inputs_from_daily


def test_daily_history_produces_rise_volume_ratio_and_trading_value():
    history = {
        "NVDA": pd.DataFrame(
            {
                "Close": [100.0, 100.0, 110.0],
                "Volume": [100, 200, 600],
            },
            index=pd.to_datetime(["2026-08-10", "2026-08-11", "2026-08-12"]),
        )
    }

    rows = featured_inputs_from_daily(history, as_of=date(2026, 8, 12))

    assert rows == (rows[0],)
    assert rows[0].symbol == "NVDA"
    assert rows[0].change_pct == pytest.approx(0.10)
    assert rows[0].volume_ratio == 4.0
    assert rows[0].trading_value == 66000.0


def test_daily_history_excludes_unmapped_or_insufficient_rows():
    history = {
        "UNKNOWN": pd.DataFrame({"Close": [1, 2], "Volume": [1, 2]}),
        "MU": pd.DataFrame({"Close": [1], "Volume": [1]}),
    }

    assert featured_inputs_from_daily(history, as_of=date(2026, 8, 12)) == ()
