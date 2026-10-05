import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from lat5.cli import main
from lat5.collector_store import CollectorStore
from lat5.token_provider import TokenSnapshot as _Token


def _insert_run(db, started, status="RUNNING", finished=None):
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO collection_runs (started_at, finished_at, status, watchlist_count, token_cache_time) "
        "VALUES (?,?,?,?,?)", (started.astimezone().isoformat(), finished, status, 154, "x"))
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def test_close_orphaned_runs_closes_only_stale_running_rows(tmp_path):
    db = tmp_path / "m.db"
    with CollectorStore(db) as store:
        pass
    now = datetime.now()
    stale = _insert_run(db, now - timedelta(hours=22))
    recent = _insert_run(db, now - timedelta(minutes=20))
    done = _insert_run(db, now - timedelta(hours=30), status="COMPLETE",
                       finished=now.astimezone().isoformat())

    with CollectorStore(db) as store:
        closed = store.close_orphaned_runs(older_than_hours=3)

    assert closed == [stale]
    conn = sqlite3.connect(db)
    statuses = dict(conn.execute("SELECT run_id, status FROM collection_runs"))
    assert statuses[stale] == "BLOCKED"
    assert statuses[recent] == "RUNNING"  # may be a collection genuinely in flight
    assert statuses[done] == "COMPLETE"
    finished_at = conn.execute("SELECT finished_at FROM collection_runs WHERE run_id=?", (stale,)).fetchone()[0]
    assert finished_at is not None
    code, message = conn.execute(
        "SELECT error_code, message FROM collection_errors WHERE run_id=?", (stale,)).fetchone()
    assert code == "ORPHANED_RUN" and "interrupted" in message


def test_close_orphaned_runs_is_a_noop_when_nothing_is_stale(tmp_path):
    with CollectorStore(tmp_path / "m.db") as store:
        assert store.close_orphaned_runs(older_than_hours=3) == []


def test_connection_waits_for_a_locked_database_instead_of_failing_in_five_seconds(tmp_path):
    with CollectorStore(tmp_path / "m.db") as store:
        assert store.conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 60_000


class _FlakyConn:
    def __init__(self, failures, message="database is locked"):
        self.failures = failures
        self.message = message
        self.commits = 0

    def commit(self):
        self.commits += 1
        if self.failures > 0:
            self.failures -= 1
            raise sqlite3.OperationalError(self.message)


def _store_with_fake_conn(tmp_path, fake):
    """A real store whose connection is swapped for ``fake`` (restored by the caller)."""
    store = CollectorStore(tmp_path / "m.db")
    real = store.conn
    store.conn = fake
    return store, real


def test_commit_retries_a_transient_lock(tmp_path):
    fake = _FlakyConn(failures=2)
    store, real = _store_with_fake_conn(tmp_path, fake)
    slept = []
    store._sleep = slept.append

    store._commit()

    assert fake.commits == 3
    assert len(slept) == 2 and slept[0] > 0
    real.close()


def test_commit_gives_up_after_the_retry_budget(tmp_path):
    fake = _FlakyConn(failures=99)
    store, real = _store_with_fake_conn(tmp_path, fake)
    store._sleep = lambda seconds: None

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        store._commit()
    assert fake.commits == store.COMMIT_ATTEMPTS
    real.close()


def test_commit_does_not_swallow_other_database_errors(tmp_path):
    fake = _FlakyConn(failures=1, message="disk I/O error")
    store, real = _store_with_fake_conn(tmp_path, fake)
    store._sleep = lambda seconds: pytest.fail("must not retry unrelated errors")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        store._commit()
    assert fake.commits == 1
    real.close()


def test_collect_sweeps_orphaned_runs_at_start_and_reports_them(monkeypatch, tmp_path, capsys):
    watchlist = tmp_path / "watch.md"
    watchlist.write_text(
        "## 3. Core Watchlist\n\n| 우선순위 | 종목명 | 코드 | 역할 |\n"
        "|---:|---|---:|---|\n| 1 | Samsung | 005930 | test |\n", encoding="utf-8")
    db = tmp_path / "market.db"
    with CollectorStore(db):
        pass
    orphan = _insert_run(db, datetime.now() - timedelta(hours=22))
    monkeypatch.setattr("lat5.cli.load_credentials", lambda path: object())
    monkeypatch.setattr("lat5.cli.get_lat_token",
                        lambda credentials, cache: _Token("tok", datetime(2026, 10, 5), tmp_path / "t.json"))
    monkeypatch.setattr("lat5.cli.collect_watchlist",
                        lambda client, store, run_id, symbols, base_date: {"success_symbols": 1, "api_errors": 0})

    code = main(["collect", "--db", str(db), "--watchlist", str(watchlist),
                 "--env", str(tmp_path / ".env"), "--token-cache", str(tmp_path / "token.json")])

    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["status"] == "COMPLETE"
    assert payload["closed_orphan_runs"] == [orphan]
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status FROM collection_runs WHERE run_id=?", (orphan,)).fetchone()[0] == "BLOCKED"
