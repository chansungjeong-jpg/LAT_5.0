import json
import sqlite3
from datetime import date

import pandas as pd
import pytest

from lat5 import dashboard_data as dd


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _scoring_dir(root):
    return root / "artifacts" / "latest_scoring"


def test_load_payloads_reports_missing_files_instead_of_guessing(tmp_path):
    payloads = dd.load_payloads(tmp_path)

    assert payloads.diagnostics is None
    assert payloads.filter_payload is None
    assert payloads.rs_payload is None
    assert {issue["source"] for issue in payloads.issues} == {
        "backtest_diagnostics.json",
        "monthly_weekly_filter.json",
        "relative_strength.json",
    }


def test_load_payloads_reads_existing_files(tmp_path):
    _write(_scoring_dir(tmp_path) / "backtest_diagnostics.json",
           {"diagnostics": {"universe_symbols": 154, "location_decisions": []}})
    _write(_scoring_dir(tmp_path) / "monthly_weekly_filter.json", {"as_of": "2026-10-02", "rows": []})
    _write(_scoring_dir(tmp_path) / "relative_strength.json", {"as_of": "2026-10-02", "rows": []})

    payloads = dd.load_payloads(tmp_path)

    assert payloads.issues == []
    assert payloads.diagnostics["universe_symbols"] == 154
    assert payloads.filter_payload["as_of"] == "2026-10-02"


def test_load_payloads_marks_corrupt_json_as_issue(tmp_path):
    path = _scoring_dir(tmp_path) / "relative_strength.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    payloads = dd.load_payloads(tmp_path)

    assert payloads.rs_payload is None
    assert any(i["source"] == "relative_strength.json" for i in payloads.issues)


def _board_rows():
    filter_rows = [
        {"ticker": "A", "name": "AA", "sector": "반도체", "provisional": False, "volume_ratio": 1.3},
        {"ticker": "B", "name": "BB", "sector": "반도체", "provisional": False, "volume_ratio": 0.9},
        {"ticker": "C", "name": "CC", "sector": "건설", "provisional": True, "volume_ratio": 1.0},
    ]
    rs_rows = [
        {"ticker": "A", "rs": 0.05, "stock_return": 0.10},
        {"ticker": "B", "rs": -0.02, "stock_return": 0.01},
        {"ticker": "C", "rs": 0.01, "stock_return": 0.04},
    ]
    decisions = [
        {"symbol": "A", "evaluated_at": "2026-10-02 11:00:00", "location_score": 86,
         "final_state": "BUY_READY", "entry_eligible": True, "vetoes": []},
    ]
    return filter_rows, rs_rows, decisions


def test_build_funnel_counts_each_stage_and_flags_first_dead_stage():
    filter_rows, rs_rows, decisions = _board_rows()
    board = dd.build_board(filter_rows, rs_rows, decisions)

    funnel = dd.build_funnel(universe=154, board=board)

    assert [(s["단계"], s["건수"]) for s in funnel["stages"]] == [
        ("관찰 목록", 154),
        ("월10·주5 회복 통과", 3),
        ("RS 양수", 2),
        ("위치점수 평가", 1),
        ("매수 가능", 1),
    ]
    assert funnel["halt"] is None


def test_build_funnel_halt_is_first_zero_stage():
    filter_rows, rs_rows, _ = _board_rows()
    board = dd.build_board(filter_rows, rs_rows, [])

    funnel = dd.build_funnel(universe=154, board=board)

    assert funnel["halt"]["단계"] == "위치점수 평가"


def test_build_funnel_unknown_universe_is_none_not_zero():
    funnel = dd.build_funnel(universe=None, board=[])

    assert funnel["stages"][0]["건수"] is None
    assert funnel["halt"]["단계"] == "월10·주5 회복 통과"


def test_status_band_go_when_entry_eligible_exists():
    filter_rows, rs_rows, decisions = _board_rows()
    board = dd.build_board(filter_rows, rs_rows, decisions)
    funnel = dd.build_funnel(universe=154, board=board)

    band = dd.status_band(funnel, board, data_date="2026-10-02", today=date(2026, 10, 2), issues=[])

    assert band["level"] == "go"
    assert "1건" in band["verdict"]


def test_status_band_hold_when_no_entry_eligible():
    filter_rows, rs_rows, _ = _board_rows()
    board = dd.build_board(filter_rows, rs_rows, [])
    funnel = dd.build_funnel(universe=154, board=board)

    band = dd.status_band(funnel, board, data_date="2026-10-02", today=date(2026, 10, 2), issues=[])

    assert band["level"] == "hold"
    assert "0건" in band["verdict"]


def test_status_band_hold_when_market_data_is_stale():
    filter_rows, rs_rows, decisions = _board_rows()
    board = dd.build_board(filter_rows, rs_rows, decisions)
    funnel = dd.build_funnel(universe=154, board=board)

    # Wednesday with data only through the previous Friday.
    band = dd.status_band(funnel, board, data_date="2026-09-25", today=date(2026, 9, 30), issues=[])

    assert band["level"] == "hold"
    assert "최신" in band["verdict"]


def test_status_band_weekend_does_not_flag_friday_data_as_stale():
    band = dd.status_band(dd.build_funnel(universe=1, board=[]), [], data_date="2026-10-02",
                          today=date(2026, 10, 4), issues=[])

    assert "최신" not in band["verdict"]


def test_status_band_stop_when_inputs_unreadable():
    funnel = dd.build_funnel(universe=None, board=[])

    band = dd.status_band(funnel, [], data_date=None, today=date(2026, 10, 2),
                          issues=[{"source": "backtest_diagnostics.json", "error": "missing"}])

    assert band["level"] == "stop"
    assert "확인 불가" in band["verdict"]


def _db_with_bars(path):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE ohlcv_daily (provider TEXT, ticker TEXT, date TEXT, open REAL, high REAL, "
        "low REAL, close REAL, volume REAL, amount REAL, collected_at TEXT, run_id INTEGER)"
    )
    rows = []
    for i in range(70):
        day = (pd.Timestamp("2026-07-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        price = 100.0 + i
        rows.append(("kiwoom", "A", day, price, price + 2, price - 2, price + 1, 1000.0 + i, 0.0, "x", 1))
    rows.append(("kiwoom", "B", "2026-09-01", 1, 1, 1, 1, 1, 0, "x", 1))
    conn.executemany("INSERT INTO ohlcv_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def test_load_daily_frame_is_read_only_and_sorted(tmp_path):
    db = tmp_path / "m.db"
    _db_with_bars(db)

    frame = dd.load_daily_frame(db, "A", limit=60)

    assert len(frame) == 60
    assert frame["date"].is_monotonic_increasing
    assert set(frame.columns) >= {"date", "open", "high", "low", "close", "volume"}
    assert frame["close"].iloc[-1] == 170.0  # last of 70 bars: 100+69+1


def test_load_daily_frame_missing_db_returns_empty(tmp_path):
    frame = dd.load_daily_frame(tmp_path / "nope.db", "A")

    assert frame.empty


def test_with_moving_averages_uses_trailing_windows():
    frame = pd.DataFrame({"close": [float(i) for i in range(1, 71)]})

    out = dd.with_moving_averages(frame)

    assert out["sma5"].iloc[4] == pytest.approx(3.0)
    assert pd.isna(out["sma5"].iloc[3])
    assert out["sma60"].iloc[59] == pytest.approx(30.5)
    assert pd.isna(out["sma60"].iloc[58])


def test_latest_data_date_reads_max_daily_date(tmp_path):
    db = tmp_path / "m.db"
    _db_with_bars(db)

    assert dd.latest_data_date(db) == "2026-09-08"


def test_latest_data_date_none_for_missing_db(tmp_path):
    assert dd.latest_data_date(tmp_path / "nope.db") is None


def test_decision_for_returns_latest_evaluation_for_symbol():
    decisions = [
        {"symbol": "A", "evaluated_at": "2026-09-01 11:00:00", "location_score": 10},
        {"symbol": "A", "evaluated_at": "2026-09-05 11:00:00", "location_score": 70},
        {"symbol": "B", "evaluated_at": "2026-09-05 11:00:00", "location_score": 40},
    ]

    assert dd.decision_for("A", decisions)["location_score"] == 70
    assert dd.decision_for("Z", decisions) is None
