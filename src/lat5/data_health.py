from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from lat5.data import WatchItem


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _coverage(conn: sqlite3.Connection, table: str, symbols: set[str]) -> tuple[int, str | None]:
    if not symbols or not _table_exists(conn, table):
        return 0, None
    date_column = "datetime" if table in {"ohlcv_minute", "execution_strength"} else "date"
    placeholders = ",".join("?" for _ in symbols)
    row = conn.execute(
        f"SELECT COUNT(DISTINCT ticker), MAX({date_column}) FROM {table} "
        f"WHERE provider='kiwoom' AND ticker IN ({placeholders})",
        tuple(sorted(symbols)),
    ).fetchone()
    return int(row[0]), row[1]


def build_data_health(db_path: str | Path, items: Iterable[WatchItem]) -> dict[str, object]:
    symbols = {item.ticker for item in items}
    conn = sqlite3.connect(Path(db_path))
    try:
        daily, daily_latest = _coverage(conn, "ohlcv_daily", symbols)
        minute, minute_latest = _coverage(conn, "ohlcv_minute", symbols)
        flow, flow_latest = _coverage(conn, "investor_flow", symbols)
        strength, strength_latest = _coverage(conn, "execution_strength", symbols)
        latest_run = (
            conn.execute(
                "SELECT run_id, status, watchlist_count, success_count, error_count "
                "FROM collection_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            if _table_exists(conn, "collection_runs")
            else None
        )
        latest_error = None
        if latest_run and _table_exists(conn, "collection_errors"):
            error_row = conn.execute(
                "SELECT message FROM collection_errors WHERE run_id=? ORDER BY id DESC LIMIT 1",
                (latest_run[0],),
            ).fetchone()
            latest_error = error_row[0] if error_row else None
        invalid_ohlcv = 0
        for table in ("ohlcv_daily", "ohlcv_minute"):
            if not _table_exists(conn, table):
                continue
            interval_clause = " AND interval='5'" if table == "ohlcv_minute" else ""
            invalid_ohlcv += int(
                conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE provider='kiwoom'"
                    f"{interval_clause} AND (open<=0 OR high<=0 OR low<=0 OR close<=0 OR high<low)"
                ).fetchone()[0]
            )
        sqlite_ok = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    total = len(symbols)
    latest_run_id = latest_run[0] if latest_run else None
    latest_run_status = latest_run[1] if latest_run else None
    latest_run_watchlist = int(latest_run[2]) if latest_run else 0
    latest_run_success = int(latest_run[3]) if latest_run else 0
    latest_run_errors = int(latest_run[4]) if latest_run else 0
    latest_scope_ok = bool(
        latest_run
        and latest_run_watchlist >= total
        and latest_run_success >= total
        and latest_run_errors == 0
    )
    latest_complete = bool(latest_run and latest_run_status == "COMPLETE" and latest_scope_ok)

    def pct(value: int) -> float:
        return round(value * 100 / total, 2) if total else 0.0

    result: dict[str, object] = {
        "watchlist_symbols": total,
        "daily_symbols": daily,
        "daily_coverage_pct": pct(daily),
        "daily_latest": daily_latest,
        "minute_symbols": minute,
        "minute_coverage_pct": pct(minute),
        "minute_latest": minute_latest,
        "foreign_flow_symbols": flow,
        "foreign_flow_coverage_pct": pct(flow),
        "foreign_flow_latest": flow_latest,
        "strength_symbols": strength,
        "strength_schema_ok": strength > 0,
        "strength_coverage_pct": pct(strength),
        "strength_latest": strength_latest,
        "latest_collection_run_id": latest_run_id,
        "latest_collection_status": latest_run_status,
        "latest_collection_watchlist_count": latest_run_watchlist,
        "latest_collection_success_count": latest_run_success,
        "latest_collection_error_count": latest_run_errors,
        "latest_collection_scope_ok": latest_scope_ok,
        "latest_collection_error": latest_error,
        "latest_collection_complete": latest_complete,
        "data_integrity_ok": bool(sqlite_ok and invalid_ohlcv == 0),
        "invalid_ohlcv_rows": invalid_ohlcv,
    }
    result["status"] = (
        "PASS"
        if result["daily_coverage_pct"] >= 95
        and result["minute_coverage_pct"] >= 90
        and result["foreign_flow_coverage_pct"] >= 90
        and result["strength_coverage_pct"] >= 90
        and result["latest_collection_complete"]
        and result["data_integrity_ok"]
        else "FAIL"
    )
    return result


def write_data_health(health: dict[str, object], output_dir: str | Path) -> tuple[Path, Path]:
    root = Path(output_dir)
    artifacts = root / "artifacts"
    reports = root / "reports"
    artifacts.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    json_path = artifacts / "data_health_latest.json"
    md_path = reports / "data_health_latest.md"
    json_path.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        "# LAT 5.0 Data Health\n\n"
        f"**Status: {health['status']}**\n\n"
        f"Latest collection: `{health['latest_collection_status'] or 'NONE'}`"
        f" (run {health['latest_collection_run_id'] or '-'})\n\n"
        f"Latest error: `{health['latest_collection_error'] or '-'}`\n\n"
        f"Latest scope: `{health['latest_collection_success_count']}/"
        f"{health['watchlist_symbols']}` success "
        f"(run scope={health['latest_collection_watchlist_count']}), "
        f"errors={health['latest_collection_error_count']}, "
        f"scope_ok={health['latest_collection_scope_ok']}\n\n"
        "| Dataset | Symbols | Coverage | Latest | Gate |\n"
        "|---|---:|---:|---|---:|\n"
        f"| Daily | {health['daily_symbols']} | {health['daily_coverage_pct']}% | {health['daily_latest'] or '-'} | 95% |\n"
        f"| 5-minute | {health['minute_symbols']} | {health['minute_coverage_pct']}% | {health['minute_latest'] or '-'} | 90% |\n"
        f"| Foreign flow | {health['foreign_flow_symbols']} | {health['foreign_flow_coverage_pct']}% | {health['foreign_flow_latest'] or '-'} | 90% |\n"
        f"| Execution strength | {health['strength_symbols']} | schema={health['strength_schema_ok']} | {health['strength_latest'] or '-'} | required |\n"
        f"\nCollection complete: `{health['latest_collection_complete']}`  \n"
        f"OHLCV integrity: `{health['data_integrity_ok']}` (invalid rows: {health['invalid_ohlcv_rows']})\n",
        encoding="utf-8",
    )
    return json_path, md_path
