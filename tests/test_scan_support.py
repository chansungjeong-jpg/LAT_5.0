import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lat5.scan_support import should_update_latest, truncate_daily_as_of
from scripts import relative_strength_scan


def _frame(dates):
    return pd.DataFrame({"close": range(len(dates))}, index=pd.to_datetime(dates))


def test_truncate_daily_as_of_is_inclusive_and_drops_later_rows():
    daily = _frame(["2026-09-14", "2026-09-15", "2026-09-16"])

    out = truncate_daily_as_of(daily, pd.Timestamp("2026-09-15"))

    assert list(out.index.strftime("%Y-%m-%d")) == ["2026-09-14", "2026-09-15"]


def test_truncate_daily_as_of_handles_intraday_index_and_empty():
    daily = pd.DataFrame({"close": [1, 2]},
                         index=pd.to_datetime(["2026-09-15 00:00", "2026-09-16 00:00"]))
    assert len(truncate_daily_as_of(daily, pd.Timestamp("2026-09-15 16:00"))) == 1
    assert truncate_daily_as_of(pd.DataFrame(), pd.Timestamp("2026-09-15")).empty


def test_should_update_latest_when_missing_corrupt_older_or_equal(tmp_path):
    path = tmp_path / "latest.json"
    assert should_update_latest(path, "2026-10-02") is True  # missing
    path.write_text("{bad", encoding="utf-8")
    assert should_update_latest(path, "2026-10-02") is True  # corrupt
    path.write_text(json.dumps({"as_of": "2026-10-01"}), encoding="utf-8")
    assert should_update_latest(path, "2026-10-02") is True  # older
    assert should_update_latest(path, "2026-10-01") is True  # equal


def test_should_update_latest_false_when_existing_is_newer(tmp_path):
    path = tmp_path / "latest.json"
    path.write_text(json.dumps({"as_of": "2026-10-04"}), encoding="utf-8")

    assert should_update_latest(path, "2026-09-30") is False


def _make_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE ohlcv_daily (provider TEXT, ticker TEXT, date TEXT, open REAL, high REAL, "
                 "low REAL, close REAL, volume REAL, amount REAL, collected_at TEXT, run_id INTEGER)")
    days = pd.bdate_range("2026-09-01", "2026-09-30")
    rows = []
    for ticker in ("000001", "000002", "000003"):
        for day in days:
            # 000003 climbs every day after 09-15; the others stay flat.
            after = max(0, (day - pd.Timestamp("2026-09-15")).days)
            price = 100.0 + 10.0 * after if ticker == "000003" else 100.0
            rows.append(("kiwoom", ticker, day.strftime("%Y-%m-%d"), price, price, price, price,
                         1000.0, 0.0, "x", 1))
    conn.executemany("INSERT INTO ohlcv_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _watchlist(path):
    path.write_text("## 3. Core Watchlist\n### 반도체\n| 1 | A | 000001 |\n| 2 | B | 000002 |\n"
                    "| 3 | C | 000003 |\n## 4. End\n", encoding="utf-8")


def _run_rs(tmp_path, as_of, json_name="rs.json"):
    db, watch = tmp_path / "m.db", tmp_path / "w.md"
    if not db.exists():
        _make_db(db)
        _watchlist(watch)
    out_json = tmp_path / json_name
    relative_strength_scan.main([
        "--db", str(db), "--watchlist", str(watch), "--as-of", as_of, "--days", "5",
        "--output-dir", str(tmp_path / "reports"), "--json-output", str(out_json),
    ])
    return out_json


def test_rs_scan_past_as_of_ignores_later_bars(tmp_path):
    out_json = _run_rs(tmp_path, "2026-09-15")

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    by_ticker = {row["ticker"]: row for row in payload["rows"]}
    # Without truncation 000003 would show a large 5-day return from the later climb.
    assert by_ticker["000003"]["stock_return"] == 0.0
    assert payload["market_return"] == 0.0


def test_rs_scan_latest_as_of_sees_all_bars(tmp_path):
    out_json = _run_rs(tmp_path, "2026-09-30")

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    by_ticker = {row["ticker"]: row for row in payload["rows"]}
    assert by_ticker["000003"]["stock_return"] > 0


def test_rs_scan_does_not_overwrite_newer_latest_json(tmp_path):
    newest = _run_rs(tmp_path, "2026-09-30")
    before = newest.read_text(encoding="utf-8")

    _run_rs(tmp_path, "2026-09-15")  # same json path, older as_of

    assert newest.read_text(encoding="utf-8") == before
    assert (tmp_path / "reports" / "2026-09-15.md").exists()  # dated report still written
