from datetime import date

import pandas as pd
import pytest

from lat5.us_market_data import YFinanceDailyProvider
from lat5.us_market_data import collect_us_context
from lat5.collector_store import CollectorStore
from datetime import datetime


def test_provider_normalizes_latest_two_closes_per_symbol():
    def downloader(symbols, start, end):
        return {
            "SPY": pd.DataFrame(
                {"Close": [100.0, 101.0]},
                index=pd.to_datetime(["2026-08-11", "2026-08-12"]),
            ),
            "US10Y": pd.DataFrame(
                {"Close": [4.0, 4.1]},
                index=pd.to_datetime(["2026-08-11", "2026-08-12"]),
            ),
        }

    observations = YFinanceDailyProvider(downloader).fetch(
        ("SPY", "US10Y"), as_of=date(2026, 8, 12)
    )

    assert observations[0].symbol == "SPY"
    assert observations[0].previous_close == 100.0
    assert observations[0].close == 101.0
    assert observations[1].symbol == "US10Y"


def test_provider_rejects_missing_close_history():
    def downloader(symbols, start, end):
        return {"SPY": pd.DataFrame({"Open": [1, 2]})}

    with pytest.raises(ValueError, match="Close"):
        YFinanceDailyProvider(downloader).fetch(("SPY",), as_of=date(2026, 8, 12))


def test_collect_us_context_persists_gate_and_company_flows(tmp_path):
    def downloader(symbols, start, end):
        index = pd.to_datetime(["2026-08-11", "2026-08-12"])
        return {
            symbol: pd.DataFrame({"Close": [100.0, 101.0]}, index=index)
            for symbol in symbols
        }

    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(0, datetime(2026, 8, 12, 18, 0, 0))
        result = collect_us_context(
            YFinanceDailyProvider(downloader), store, run_id,
            as_of=date(2026, 8, 12),
            symbols=("SPY", "QQQ", "IWM", "DIA", "VIX", "US10Y", "MU"),
        )
        gate_count = store.conn.execute("SELECT COUNT(*) FROM us_market_gates").fetchone()[0]

    assert result.market_gate.flow == "US_MARKET_FLOW"
    assert gate_count == 1
    assert "US_AI_FLOW" in result.company_flows
