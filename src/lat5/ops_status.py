"""Read-only operations status for the dashboard: scheduled-task state,
pipeline run logs and collection-run history. Nothing here starts, stops or
modifies a task or a run."""
from __future__ import annotations

import csv
import io
import json
import locale
import re
import sqlite3
import subprocess
from pathlib import Path

import pandas as pd

# schtasks prints localized text in the console codepage (cp949 on Korean
# Windows) and its /FO CSV column order is fixed -- parse by index.
_NEXT_RUN, _STATE, _LAST_RUN, _LAST_RESULT, _SCHED_STATE = 2, 3, 5, 6, 11
_OK_CODES = {"0", "267009", "267011"}  # success / currently running / never run yet
_RUNNING_CODE = "267009"


def parse_task_csv(text: str) -> dict | None:
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if len(rows) < 2 or len(rows[1]) <= _SCHED_STATE:
        return None
    row = rows[1]
    last_result = row[_LAST_RESULT].strip()
    sched_state = row[_SCHED_STATE].strip()
    return {
        "name": row[1].lstrip("\\"),
        "state": row[_STATE].strip(),
        "next_run": row[_NEXT_RUN].strip(),
        "last_run": row[_LAST_RUN].strip(),
        "last_result": last_result,
        "running": last_result == _RUNNING_CODE,
        "enabled": "사용 안 함" not in sched_state and sched_state.lower() != "disabled",
        "ok": last_result in _OK_CODES,
    }


def query_task(name: str) -> dict | None:
    try:
        completed = subprocess.run(
            ["schtasks", "/Query", "/TN", name, "/FO", "CSV", "/V"],
            capture_output=True, text=True, timeout=30,
            encoding=locale.getpreferredencoding(False), errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return parse_task_csv(completed.stdout)


_STARTED = re.compile(r"=== run started_at=(\S+) ===")
_RESULT = re.compile(r"^=== run result=(\w+)(.*?)\s*===\s*$", re.MULTILINE)


def summarize_pipeline_log(text: str) -> dict:
    started = _STARTED.search(text)
    result = _RESULT.search(text)
    summary = {
        "started_at": started.group(1) if started else None,
        "result": result.group(1) if result else "INCOMPLETE",
        "run_id": None, "symbols": None, "success": None, "errors": None,
        "health": None, "detail": None,
    }
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if "run_id" in payload and summary["run_id"] is None:
            summary["run_id"] = payload["run_id"]
            summary["symbols"] = payload.get("symbols")
            summary["success"] = payload.get("success_symbols")
            summary["errors"] = payload.get("api_errors")
            if payload.get("error"):
                summary["detail"] = str(payload["error"])
        elif "json" in payload:
            summary["health"] = payload.get("status")
    if summary["detail"] is None and summary["result"] == "BLOCKED" and result:
        summary["detail"] = result.group(2).strip() or None
    return summary


def load_pipeline_runs(log_dir: Path | str, limit: int = 14) -> list[dict]:
    folder = Path(log_dir)
    if not folder.exists():
        return []
    logs = sorted((p for p in folder.glob("*.log") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem)),
                  key=lambda p: p.stem, reverse=True)[:limit]
    runs = []
    for path in logs:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        runs.append({"date": path.stem, **summarize_pipeline_log(text)})
    return runs


def load_collection_runs(db_path: Path | str, limit: int = 14) -> pd.DataFrame:
    columns = ["run_id", "started_at", "finished_at", "status", "success_count", "error_count", "minutes"]
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            frame = pd.read_sql_query(
                "SELECT run_id, started_at, finished_at, status, success_count, error_count "
                "FROM collection_runs ORDER BY run_id DESC LIMIT ?", conn, params=(int(limit),))
        finally:
            conn.close()
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame(columns=columns)
    started = pd.to_datetime(frame["started_at"], errors="coerce", utc=True)
    finished = pd.to_datetime(frame["finished_at"], errors="coerce", utc=True)
    # An unfinished run has no duration (NaN) -- never shown as 0 minutes.
    frame["minutes"] = (finished - started).dt.total_seconds() / 60.0
    return frame[columns]


_VERDICT_BY_EXIT = {"0": "PASS", "1": "WARN", "2": "FAIL"}


def describe_task(info: dict | None, *, health_check: bool = False) -> str:
    """One-word status for a task card. The morning health check signals its
    own verdict through its exit code (0/1/2 = PASS/WARN/FAIL), so a code of
    2 means "the check ran and found a problem", not "the task crashed"."""
    if info is None:
        return "확인 불가"
    if not info["enabled"]:
        return "비활성"
    if info["running"]:
        return "실행 중"
    if health_check and info["last_result"] in _VERDICT_BY_EXIT:
        return f"점검 판정 {_VERDICT_BY_EXIT[info['last_result']]}"
    return "정상" if info["ok"] else f"실패 코드 {info['last_result']}"
