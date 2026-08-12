from datetime import date, datetime

from lat5.collector_store import CollectorStore
from lat5.us_market_flow import CompanyFlowDecision, MarketGateDecision, USMarketObservation
from lat5.us_featured import USFeaturedStock


def test_store_persists_us_market_context_and_flow(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(0, datetime(2026, 8, 13, 8, 0, 0))
        store.save_us_observations(
            run_id,
            [USMarketObservation("US10Y", date(2026, 8, 12), 4.0, 4.1, date(2026, 8, 13))],
        )
        store.save_us_market_gate(
            run_id,
            date(2026, 8, 13),
            MarketGateDecision("SELECTIVE_BUY", "US_MARKET_FLOW", "US10Y", 2, ("INDEX_BREADTH_SELECTIVE",)),
        )
        store.save_us_company_flows(
            run_id,
            date(2026, 8, 13),
            [CompanyFlowDecision("US_SOLAR_FLOW", "POSITIVE", 0.03, ("RUN", "FSLR"))],
        )

        obs = store.conn.execute("SELECT symbol, close FROM us_market_observations").fetchone()
        gate = store.conn.execute("SELECT state, flow FROM us_market_gates").fetchone()
        flow = store.conn.execute("SELECT flow, direction FROM us_company_flows").fetchone()

    assert obs == ("US10Y", 4.1)
    assert gate == ("SELECTIVE_BUY", "US_MARKET_FLOW")
    assert flow == ("US_SOLAR_FLOW", "POSITIVE")


def test_store_persists_featured_us_stocks_with_domestic_mapping(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(0, datetime(2026, 8, 13, 8, 0, 0))
        count = store.save_us_featured_stocks(
            run_id,
            date(2026, 8, 13),
            [USFeaturedStock("NVDA", "US_AI_FLOW", 0.05, 2.4, 1_000_000, 80.0, "RISE_VOLUME_TRADING_VALUE_RANKED")],
        )
        row = store.conn.execute(
            "SELECT symbol,flow,featured_score,kr_tickers_json FROM us_featured_stocks"
        ).fetchone()

    assert count == 1
    assert row == ("NVDA", "US_AI_FLOW", 80.0, '["000660", "005930", "042700"]')
