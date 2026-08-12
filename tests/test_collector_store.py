import json
from datetime import datetime

from lat5.collector_store import CollectorStore
from lat5.kiwoom_client import ApiPage
from lat5.leader_score import MarketLeader


def test_store_keeps_provider_in_daily_primary_key_and_upserts_same_provider(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(154, datetime(2026, 8, 9, 7, 14, 34))
        base = {
            "ticker": "005930",
            "date": "2026-08-08",
            "open": 100,
            "high": 110,
            "low": 90,
            "close": 105,
            "volume": 1000,
            "amount": 105000,
        }
        store.save_daily(run_id, [base], provider="kiwoom")
        store.save_daily(run_id, [{**base, "close": 106}], provider="kiwoom")
        store.save_daily(run_id, [{**base, "close": 200}], provider="kis")

        rows = store.conn.execute(
            "SELECT provider, close FROM ohlcv_daily ORDER BY provider"
        ).fetchall()
        assert rows == [("kis", 200.0), ("kiwoom", 106.0)]


def test_raw_pages_are_append_only(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(1, datetime(2026, 8, 9, 7, 14, 34))
        page = ApiPage("ka10081", 1, {"rows": [1]}, "N", "")
        store.save_raw_page(run_id, "005930", page)
        store.save_raw_page(run_id, "005930", page)
        payloads = store.conn.execute(
            "SELECT payload_json FROM raw_api_responses ORDER BY id"
        ).fetchall()
        assert len(payloads) == 2
        assert json.loads(payloads[0][0]) == {"rows": [1]}


def test_run_state_and_errors_are_auditable(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(154, datetime(2026, 8, 9, 7, 14, 34))
        assert store.run_status(run_id) == "RUNNING"
        store.record_error(run_id, "005930", "ka10046", "SCHEMA_MISMATCH", "missing strength")
        store.finish_run(run_id, "PARTIAL", success_count=153, error_count=1)
        assert store.run_status(run_id) == "PARTIAL"
        assert store.conn.execute("SELECT COUNT(*) FROM collection_errors").fetchone()[0] == 1


def test_store_saves_minute_strength_and_foreign_flow(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(1, datetime(2026, 8, 9, 7, 14, 34))
        store.save_minutes(
            run_id,
            [{
                "ticker": "005930", "datetime": "2026-08-08T15:25:00",
                "interval": "5", "open": 70000, "high": 70500, "low": 69900,
                "close": 70300, "volume": 100, "amount": 7030000,
            }],
        )
        store.save_strength(
            run_id,
            [{"ticker": "005930", "datetime": "2026-08-08T15:25:00", "strength": 123.45}],
        )
        store.save_foreign_flow(
            run_id,
            [{"ticker": "005930", "date": "2026-08-08", "foreign_net_thousand": -1250}],
        )

        assert store.conn.execute("SELECT COUNT(*) FROM ohlcv_minute").fetchone()[0] == 1
        assert store.conn.execute("SELECT strength FROM execution_strength").fetchone()[0] == 123.45
        assert store.conn.execute("SELECT foreign_net_thousand FROM investor_flow").fetchone()[0] == -1250


def test_leader_observations_are_persisted_with_nullable_sector(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(0, datetime(2026, 8, 12, 9, 0, 0))
        count = store.save_leader_observations(
            run_id,
            "2026-08-12",
            [MarketLeader("005930", "삼성전자", "KOSPI", None, 1000, 3, 1, 2, 80)],
        )
        row = store.conn.execute(
            "SELECT market,ticker,sector,leader_score FROM leader_observations"
        ).fetchone()

    assert count == 1
    assert row == ("KOSPI", "005930", None, 80.0)
