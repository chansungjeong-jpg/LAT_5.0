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
                "SELECT run_id, status FROM collection_runs ORDER BY run_id DESC LIMIT 1"
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
    finally:
        conn.close()
    total = len(symbols)

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
        "strength_latest": strength_latest,
        "latest_collection_run_id": latest_run[0] if latest_run else None,
        "latest_collection_status": latest_run[1] if latest_run else None,
        "latest_collection_error": latest_error,
    }
    result["status"] = (
        "PASS"
        if result["daily_coverage_pct"] >= 95
        and result["minute_coverage_pct"] >= 90
        and result["foreign_flow_coverage_pct"] >= 90
        and result["strength_schema_ok"]
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
        "| Dataset | Symbols | Coverage | Latest | Gate |\n"
        "|---|---:|---:|---|---:|\n"
        f"| Daily | {health['daily_symbols']} | {health['daily_coverage_pct']}% | {health['daily_latest'] or '-'} | 95% |\n"
        f"| 5-minute | {health['minute_symbols']} | {health['minute_coverage_pct']}% | {health['minute_latest'] or '-'} | 90% |\n"
        f"| Foreign flow | {health['foreign_flow_symbols']} | {health['foreign_flow_coverage_pct']}% | {health['foreign_flow_latest'] or '-'} | 90% |\n"
        f"| Execution strength | {health['strength_symbols']} | schema={health['strength_schema_ok']} | {health['strength_latest'] or '-'} | required |\n",
        encoding="utf-8",
    )
    return json_path, md_path
