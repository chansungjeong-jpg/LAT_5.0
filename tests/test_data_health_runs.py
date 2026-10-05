from datetime import datetime

from lat5.collector_store import CollectorStore
from lat5.data import WatchItem
from lat5.data_health import build_data_health, write_data_health

ITEMS = [WatchItem("005930", "Samsung", "semi")]


def _save_full_data(store, run_id):
    store.save_daily(run_id, [{"ticker": "005930", "date": "2026-10-02", "open": 1, "high": 1, "low": 1,
                               "close": 1, "volume": 1, "amount": 1}])
    store.save_minutes(run_id, [{"ticker": "005930", "datetime": "2026-10-02T15:25:00", "interval": "5",
                                 "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "amount": 1}])
    store.save_foreign_flow(run_id, [{"ticker": "005930", "date": "2026-10-02", "foreign_net_thousand": 1}])
    store.save_strength(run_id, [{"ticker": "005930", "datetime": "2026-10-02T15:25:00", "strength": 100}])


def _complete_run(store, when):
    run_id = store.start_run(1, when)
    _save_full_data(store, run_id)
    store.finish_run(run_id, "COMPLETE", 1, 0)
    return run_id


def test_orphaned_running_run_does_not_hide_the_last_finished_run(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        good = _complete_run(store, datetime(2026, 10, 2, 16, 0))
        store.start_run(1, datetime(2026, 10, 2, 16, 24))  # killed mid-run, stays RUNNING

    health = build_data_health(db, ITEMS)

    assert health["latest_collection_run_id"] == good
    assert health["latest_collection_status"] == "COMPLETE"
    assert health["status"] == "PASS"
    assert health["in_progress_runs"] == 1  # surfaced, not silently dropped


def test_newest_finished_failure_still_fails_health(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        _complete_run(store, datetime(2026, 10, 2, 16, 0))
        bad = store.start_run(1, datetime(2026, 10, 3, 16, 0))
        store.finish_run(bad, "BLOCKED", 0, 1)

    health = build_data_health(db, ITEMS)

    assert health["latest_collection_run_id"] == bad
    assert health["latest_collection_status"] == "BLOCKED"
    assert health["status"] == "FAIL"


def test_only_running_runs_means_no_finished_collection(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        run_id = store.start_run(1, datetime(2026, 10, 2, 16, 0))
        _save_full_data(store, run_id)

    health = build_data_health(db, ITEMS)

    assert health["latest_collection_run_id"] is None
    assert health["latest_collection_complete"] is False
    assert health["status"] == "FAIL"
    assert health["in_progress_runs"] == 1


def test_report_mentions_in_progress_runs_only_when_present(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        _complete_run(store, datetime(2026, 10, 2, 16, 0))
    clean = build_data_health(db, ITEMS)
    _, md_path = write_data_health(clean, tmp_path / "clean")
    assert "In-progress" not in md_path.read_text(encoding="utf-8")

    with CollectorStore(db) as store:
        store.start_run(1, datetime(2026, 10, 2, 16, 24))
    dirty = build_data_health(db, ITEMS)
    _, md_path = write_data_health(dirty, tmp_path / "dirty")
    assert "In-progress/unfinished runs: 1" in md_path.read_text(encoding="utf-8")
