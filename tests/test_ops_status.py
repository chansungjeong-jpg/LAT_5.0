import sqlite3

import pandas as pd
import pytest

from lat5 import dashboard_data as dd
from lat5 import ops_status as ops

TASK_CSV = (
    '"호스트 이름","작업 이름","다음 실행 시간","상태","로그온 모드","마지막 실행 시간","마지막 결과",'
    '"만든 이","실행할 작업","시작 위치","주석","예약된 작업 상태"\n'
    '"DYCOM","\\LAT5_Monthly10_Weekly5_Recovery","2026-10-05 오후 4:00:00","준비","대화형","2026-10-04 오후 4:00:00",'
    '"0","DYCOM\\User","python x.py","N/A","N/A","사용"\n'
)


def test_parse_task_csv_reads_fixed_columns():
    info = ops.parse_task_csv(TASK_CSV)

    assert info["last_result"] == "0"
    assert info["next_run"] == "2026-10-05 오후 4:00:00"
    assert info["last_run"] == "2026-10-04 오후 4:00:00"
    assert info["ok"] is True


def test_parse_task_csv_flags_nonzero_result_as_not_ok():
    info = ops.parse_task_csv(TASK_CSV.replace('"0","DYCOM\\User"', '"-2147020576","DYCOM\\User"'))

    assert info["ok"] is False
    assert info["last_result"] == "-2147020576"


def test_parse_task_csv_treats_running_code_as_ok():
    # 267009 == SCHED_S_TASK_RUNNING: still executing, not a failure.
    info = ops.parse_task_csv(TASK_CSV.replace('"0","DYCOM\\User"', '"267009","DYCOM\\User"'))

    assert info["ok"] is True and info["running"] is True


def test_parse_task_csv_unparseable_returns_none():
    assert ops.parse_task_csv("") is None
    assert ops.parse_task_csv("garbage") is None


COMPLETE_LOG = """=== run started_at=2026-10-04T16:00:02 ===
$ python -m lat5.cli collect --db x --base-date 20261004
{"status": "COMPLETE", "run_id": 55, "symbols": 154, "success_symbols": 154, "api_errors": 0}
$ python -m lat5.cli data-health
{"status": "PASS", "json": "x"}
=== run result=COMPLETE ===
"""

BLOCKED_LOG = """=== run started_at=2026-10-03T16:00:01 ===
$ python -m lat5.cli collect --db x --base-date 20261003
{"status": "BLOCKED", "run_id": 54, "error": "database is locked"}
=== run result=BLOCKED command_exit=1 ===
"""

HEADER_ONLY_LOG = "=== run started_at=2026-09-30T21:55:58 ===\n"


def test_summarize_pipeline_log_complete():
    summary = ops.summarize_pipeline_log(COMPLETE_LOG)

    assert summary["result"] == "COMPLETE"
    assert summary["run_id"] == 55 and summary["symbols"] == 154 and summary["errors"] == 0
    assert summary["started_at"] == "2026-10-04T16:00:02"
    assert summary["health"] == "PASS"
    assert summary["detail"] is None


def test_summarize_pipeline_log_blocked_keeps_the_reason():
    summary = ops.summarize_pipeline_log(BLOCKED_LOG)

    assert summary["result"] == "BLOCKED"
    assert "database is locked" in summary["detail"]


def test_summarize_pipeline_log_header_only_is_incomplete():
    summary = ops.summarize_pipeline_log(HEADER_ONLY_LOG)

    assert summary["result"] == "INCOMPLETE"
    assert summary["run_id"] is None


def test_load_pipeline_runs_newest_first_and_limited(tmp_path):
    (tmp_path / "2026-10-03.log").write_text(BLOCKED_LOG, encoding="utf-8")
    (tmp_path / "2026-10-04.log").write_text(COMPLETE_LOG, encoding="utf-8")
    (tmp_path / "2026-09-30.log").write_text(HEADER_ONLY_LOG, encoding="utf-8")

    runs = ops.load_pipeline_runs(tmp_path, limit=2)

    assert [r["date"] for r in runs] == ["2026-10-04", "2026-10-03"]
    assert ops.load_pipeline_runs(tmp_path / "nope") == []


def test_load_collection_runs_computes_duration_and_handles_open_runs(tmp_path):
    db = tmp_path / "m.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE collection_runs (run_id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT, "
                 "status TEXT, watchlist_count INT, success_count INT, error_count INT, token_cache_time TEXT)")
    conn.executemany("INSERT INTO collection_runs VALUES (?,?,?,?,?,?,?,?)", [
        (1, "2026-10-04T16:00:02+09:00", "2026-10-04T16:35:32+09:00", "COMPLETE", 154, 154, 0, "x"),
        (2, "2026-10-05T16:00:00+09:00", None, "RUNNING", 154, 0, 0, "x"),
    ])
    conn.commit()
    conn.close()

    frame = ops.load_collection_runs(db, limit=10)

    assert list(frame["run_id"]) == [2, 1]
    assert frame.loc[frame["run_id"] == 1, "minutes"].iloc[0] == pytest.approx(35.5)
    assert pd.isna(frame.loc[frame["run_id"] == 2, "minutes"].iloc[0])
    assert ops.load_collection_runs(tmp_path / "nope.db").empty


def _minute_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE ohlcv_minute (provider TEXT, ticker TEXT, datetime TEXT, interval TEXT, open REAL, "
                 "high REAL, low REAL, close REAL, volume REAL, amount REAL, collected_at TEXT, run_id INT)")
    rows = []
    for day in ("2026-10-01", "2026-10-02"):
        for minutes in range(0, 12 * 60, 5):  # 09:00 .. 20:55
            stamp = pd.Timestamp(day) + pd.Timedelta(hours=9, minutes=minutes)
            price = 100.0 + minutes / 10
            rows.append(("kiwoom", "A", stamp.strftime("%Y-%m-%dT%H:%M:%S"), "5", price, price + 1,
                         price - 1, price, 10.0, 0.0, "x", 1))
    conn.executemany("INSERT INTO ohlcv_minute VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_load_minute_frame_keeps_regular_session_only_and_orders(tmp_path):
    db = tmp_path / "m.db"
    _minute_db(db)

    frame = dd.load_minute_frame(db, "A", interval="5", limit=500)

    stamps = pd.to_datetime(frame["datetime"])
    assert stamps.is_monotonic_increasing
    assert stamps.dt.hour.min() == 9
    assert (stamps.dt.hour * 60 + stamps.dt.minute).max() <= 15 * 60 + 30
    assert {"open", "high", "low", "close", "volume"} <= set(frame.columns)


def test_load_minute_frame_missing_db_is_empty(tmp_path):
    assert dd.load_minute_frame(tmp_path / "nope.db", "A").empty


def test_hourly_from_minutes_aggregates_to_60m_bars(tmp_path):
    db = tmp_path / "m.db"
    _minute_db(db)

    hourly = dd.load_hourly_frame(db, "A", limit_5m=1000)

    # 09:00..15:30 regular session -> blocks 09,10,11,12,13,14,15 per day.
    assert len(hourly) == 14
    first = hourly.iloc[0]
    assert first["open"] == pytest.approx(100.0)
    assert first["high"] == pytest.approx(100.0 + 55 / 10 + 1)


def test_with_emas_adds_requested_spans():
    frame = pd.DataFrame({"close": [float(i) for i in range(1, 31)]})

    out = dd.with_emas(frame, (5, 20))

    assert "ema5" in out and "ema20" in out
    assert pd.isna(out["ema20"].iloc[18]) and not pd.isna(out["ema20"].iloc[19])


def _info(**overrides):
    base = {"enabled": True, "running": False, "ok": True, "last_result": "0"}
    base.update(overrides)
    return base


def test_describe_task_plain_task_states():
    assert ops.describe_task(None) == "확인 불가"
    assert ops.describe_task(_info()) == "정상"
    assert ops.describe_task(_info(ok=False, last_result="-2147020576")) == "실패 코드 -2147020576"
    assert ops.describe_task(_info(running=True, last_result="267009")) == "실행 중"
    assert ops.describe_task(_info(enabled=False)) == "비활성"


def test_describe_task_health_check_exit_code_is_a_verdict_not_a_crash():
    assert ops.describe_task(_info(ok=False, last_result="2"), health_check=True) == "점검 판정 FAIL"
    assert ops.describe_task(_info(ok=False, last_result="1"), health_check=True) == "점검 판정 WARN"
    assert ops.describe_task(_info(), health_check=True) == "점검 판정 PASS"
    # a genuine launch failure is still a failure for the health-check task
    assert ops.describe_task(_info(ok=False, last_result="-2147020576"), health_check=True) \
        == "실패 코드 -2147020576"
