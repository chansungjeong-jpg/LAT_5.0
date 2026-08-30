import json
import sqlite3
from datetime import datetime

import pytest

from lat5.cli import build_parser, main
from lat5.collector_store import CollectorStore
from lat5.data import WatchItem
from lat5.data_health import build_data_health
from lat5.lat_credentials import CredentialsError
from lat5.token_provider import TokenSnapshot


def test_collect_parser_supports_probe_and_selects_samsung_only():
    args = build_parser().parse_args(
        ["collect", "--db", "market.db", "--watchlist", "watch.md", "--probe"]
    )
    assert args.command == "collect"
    assert args.probe is True
    assert args.env.endswith(".env")
    assert args.token_cache.endswith("data\\kiwoom_token_cache.json")


def test_collect_parser_accepts_one_core_ticker():
    args = build_parser().parse_args(
        [
            "collect", "--db", "market.db", "--watchlist", "watch.md",
            "--ticker", "000660",
        ]
    )
    assert args.ticker == "000660"


def test_data_health_deduplicates_watchlist_symbols(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        run_id = store.start_run(2, datetime(2026, 8, 9, 7, 14, 34))
        store.save_daily(run_id, [{
            "ticker": "005930", "date": "2026-08-08", "open": 1, "high": 1,
            "low": 1, "close": 1, "volume": 1, "amount": 1,
        }])
        store.save_minutes(run_id, [{
            "ticker": "005930", "datetime": "2026-08-08T15:25:00", "interval": "5",
            "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1, "amount": 1,
        }])
        store.save_foreign_flow(run_id, [{
            "ticker": "005930", "date": "2026-08-08", "foreign_net_thousand": 1,
        }])
        store.save_strength(run_id, [{
            "ticker": "005930", "datetime": "2026-08-08T15:25:00", "strength": 100,
        }])
    items = [
        WatchItem("005930", "Samsung", "semi"),
        WatchItem("005930", "Samsung", "duplicate"),
        WatchItem("000660", "SK", "semi"),
    ]

    health = build_data_health(db, items)

    assert health["watchlist_symbols"] == 2
    assert health["daily_coverage_pct"] == 50.0
    assert health["minute_coverage_pct"] == 50.0
    assert health["foreign_flow_coverage_pct"] == 50.0
    assert health["strength_schema_ok"] is True
    assert health["status"] == "FAIL"


def test_collect_returns_blocked_code_when_lat_credentials_are_missing(monkeypatch, tmp_path, capsys):
    watchlist = tmp_path / "watch.md"
    watchlist.write_text("## 3. Core Watchlist\n", encoding="utf-8")
    monkeypatch.setattr(
        "lat5.cli.load_credentials",
        lambda path: (_ for _ in ()).throw(CredentialsError("missing .env")),
    )

    code = main([
        "collect", "--db", str(tmp_path / "market.db"),
        "--watchlist", str(watchlist), "--env", str(tmp_path / ".env"),
        "--token-cache", str(tmp_path / "token.json"),
    ])

    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_data_health_exposes_latest_collection_blocker(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        run_id = store.start_run(1, datetime(2026, 8, 9, 7, 14, 34))
        store.record_error(run_id, "005930", "TOKEN", "TOKEN_ERROR", "8005 invalid token")
        store.finish_run(run_id, "BLOCKED", 0, 1)

    health = build_data_health(db, [WatchItem("005930", "Samsung", "semi")])

    assert health["latest_collection_status"] == "BLOCKED"
    assert health["latest_collection_error"] == "8005 invalid token"


def test_data_health_requires_complete_run_and_reports_strength_coverage(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        run_id = store.start_run(1, datetime(2026, 8, 9, 7, 14, 34))
        store.finish_run(run_id, "PARTIAL", 1, 1)

    health = build_data_health(db, [WatchItem("005930", "Samsung", "semi")])

    assert health["strength_coverage_pct"] == 0.0
    assert health["latest_collection_complete"] is False
    assert health["latest_collection_scope_ok"] is False
    assert health["data_integrity_ok"] is True
    assert health["status"] == "FAIL"


def test_data_health_does_not_treat_single_ticker_run_as_full_collection(tmp_path):
    db = tmp_path / "market.db"
    with CollectorStore(db) as store:
        run_id = store.start_run(1, datetime(2026, 8, 9, 7, 14, 34))
        store.finish_run(run_id, "COMPLETE", 1, 0)

    health = build_data_health(
        db,
        [
            WatchItem("005930", "Samsung", "semi"),
            WatchItem("000660", "SK", "semi"),
        ],
    )

    assert health["latest_collection_status"] == "COMPLETE"
    assert health["latest_collection_scope_ok"] is False
    assert health["latest_collection_complete"] is False
    assert health["status"] == "FAIL"


def test_collect_closes_run_as_blocked_instead_of_leaving_it_running_forever(
    monkeypatch, tmp_path, capsys
):
    """Regression: 2026-08-27's ReadTimeout crash propagated straight out of
    collect_watchlist and left the run row stuck at status=RUNNING forever,
    since only KiwoomTokenError was ever caught here."""
    watchlist = tmp_path / "watch.md"
    watchlist.write_text(
        "## 3. Core Watchlist\n\n| 우선순위 | 종목명 | 코드 | 역할 |\n"
        "|---:|---|---:|---|\n| 1 | Samsung | 005930 | test |\n",
        encoding="utf-8",
    )
    db = tmp_path / "market.db"
    monkeypatch.setattr("lat5.cli.load_credentials", lambda path: object())
    monkeypatch.setattr(
        "lat5.cli.get_lat_token",
        lambda credentials, cache: TokenSnapshot("tok", datetime(2026, 8, 27), tmp_path / "t.json"),
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("read timed out")

    monkeypatch.setattr("lat5.cli.collect_watchlist", _boom)

    with pytest.raises(RuntimeError, match="read timed out"):
        main([
            "collect", "--db", str(db), "--watchlist", str(watchlist),
            "--env", str(tmp_path / ".env"), "--token-cache", str(tmp_path / "token.json"),
        ])

    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    con = sqlite3.connect(db)
    status, error_count = con.execute(
        "SELECT status, error_count FROM collection_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert status == "BLOCKED"
    assert error_count == 1
    message = con.execute(
        "SELECT message FROM collection_errors ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    assert "read timed out" in message
