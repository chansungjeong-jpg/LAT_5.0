from datetime import datetime

from lat5.collector_store import CollectorStore
from lat5.leader_collector import collect_market_leaders
from lat5.kiwoom_client import ApiPage


class FakeClient:
    def post_pages(self, api_id, path, body):
        market = body["mrkt_tp"]
        if api_id == "ka10032":
            yield ApiPage(
                api_id,
                1,
                {
                    "trde_prica_upper": [{
                        "stk_cd": "005930" if market == "001" else "A0001",
                        "stk_nm": "K" if market == "001" else "Q",
                        "trde_prica": "1000",
                    }],
                },
                "N",
                "",
            )
        else:
            yield ApiPage(
                api_id,
                1,
                {
                    "pred_pre_flu_rt_upper": [{
                        "stk_cd": "005930" if market == "001" else "A0001",
                        "stk_nm": "K" if market == "001" else "Q",
                        "flu_rt": "2",
                    }],
                },
                "N",
                "",
            )


def test_collect_market_leaders_uses_both_rank_apis_and_persists(tmp_path):
    with CollectorStore(tmp_path / "market.db") as store:
        run_id = store.start_run(0, datetime(2026, 8, 12, 9, 0, 0))
        leaders = collect_market_leaders(
            FakeClient(), store, run_id, as_of="2026-08-12"
        )
        api_ids = [row[0] for row in store.conn.execute(
            "SELECT api_id FROM raw_api_responses ORDER BY id"
        ).fetchall()]
        count = store.conn.execute(
            "SELECT COUNT(*) FROM leader_observations"
        ).fetchone()[0]

    assert [leader.market for leader in leaders] == ["KOSDAQ", "KOSPI"]
    assert api_ids == ["ka10032", "ka10027", "ka10032", "ka10027"]
    assert count == 2
