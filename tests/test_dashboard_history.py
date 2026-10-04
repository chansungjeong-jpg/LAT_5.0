import pandas as pd
import pytest

from lat5 import dashboard_data as dd

FILTER_MD = """# 월봉 SMA10·주봉 SMA5 회복 필터 — 2026-10-02

대상 종목: 154개
통과 종목: 2개

| 코드 | 종목 | 섹터 | 상태 | 주봉 회복 | 월봉 회복 | 거래량비율(7일평균대비) |
|---|---|---|---|---|---|---:|
| 000990 | DB하이텍 | 반도체 | 잠정 | 2026-09-04 → 2026-09-11 | 2026-08-31 → 2026-09-30 | 0.54배 |
| 240810 | 원익IPS | 반도체 장비·소부장 | 확정 | 2026-09-11 → 2026-09-18 | 2026-07-31 → 2026-08-31 | - |
"""

FILTER_EMPTY_MD = """# x

| 코드 | 종목 | 섹터 | 상태 | 주봉 회복 | 월봉 회복 | 거래량비율(7일평균대비) |
|---|---|---|---|---|---|---:|
| - | 해당 없음 | - | - | - | - | - |
"""

RS_MD = """# 상대강도(RS) 스캔 — 2026-10-02

기준: 20거래일 수익률. 시장 대리값 = Watchlist 154종목 동일가중 평균수익률(15.78%). **진짜 KOSPI/KOSDAQ 지수 아님**

| 순위 | 코드 | 종목 | 종목 수익률 | 시장(대리) 수익률 | RS |
|---:|---|---|---:|---:|---:|
| 1 | 043260 | 성호전자 | 89.38% | 15.78% | +73.60%p |
| 2 | 000990 | DB하이텍 | -3.00% | 15.78% | -18.78%p |
"""


def test_parse_filter_report_reads_rows_and_provisional_flag():
    rows = dd.parse_filter_report(FILTER_MD)

    assert [r["ticker"] for r in rows] == ["000990", "240810"]
    assert rows[0]["provisional"] is True and rows[1]["provisional"] is False
    assert rows[0]["volume_ratio"] == pytest.approx(0.54)
    assert rows[1]["volume_ratio"] is None
    assert rows[1]["sector"] == "반도체 장비·소부장"


def test_parse_filter_report_ignores_placeholder_row():
    assert dd.parse_filter_report(FILTER_EMPTY_MD) == []


def test_parse_rs_report_converts_percent_to_ratio():
    rows = dd.parse_rs_report(RS_MD)

    assert rows[0]["rank"] == 1 and rows[0]["ticker"] == "043260" and rows[0]["name"] == "성호전자"
    assert rows[0]["stock_return"] == pytest.approx(0.8938)
    assert rows[0]["rs"] == pytest.approx(0.736)
    assert rows[1]["rs"] == pytest.approx(-0.1878)


def test_load_history_reads_dated_reports_sorted(tmp_path):
    for sub, name, text in (("monthly_weekly_filter", "2026-10-02.md", FILTER_MD),
                            ("monthly_weekly_filter", "2026-10-01.md", FILTER_EMPTY_MD),
                            ("relative_strength", "2026-10-02.md", RS_MD)):
        folder = tmp_path / "reports" / sub
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    (tmp_path / "reports" / "monthly_weekly_filter" / "notes.md").write_text("x", encoding="utf-8")

    history = dd.load_history(tmp_path)

    assert list(history.filter_by_date) == ["2026-10-01", "2026-10-02"]
    assert history.filter_by_date["2026-10-01"] == []
    assert len(history.filter_by_date["2026-10-02"]) == 2
    assert list(history.rs_by_date) == ["2026-10-02"]


def test_load_history_missing_dirs_is_empty(tmp_path):
    history = dd.load_history(tmp_path)

    assert history.filter_by_date == {} and history.rs_by_date == {}


def _hist(filter_days, rs_days):
    return dd.History(filter_by_date=filter_days, rs_by_date=rs_days)


def test_daily_change_reports_new_exited_and_confirmed():
    prev = [{"ticker": "A", "name": "AA", "provisional": True},
            {"ticker": "B", "name": "BB", "provisional": False}]
    cur = [{"ticker": "A", "name": "AA", "provisional": False},
           {"ticker": "C", "name": "CC", "provisional": True}]
    history = _hist({"2026-10-01": prev, "2026-10-02": cur}, {})

    change = dd.daily_change(history)

    assert change["date"] == "2026-10-02" and change["prev_date"] == "2026-10-01"
    assert [r["ticker"] for r in change["new"]] == ["C"]
    assert [r["ticker"] for r in change["exited"]] == ["B"]
    assert [r["ticker"] for r in change["confirmed"]] == ["A"]


def test_daily_change_rs_movers_sorted_by_rank_improvement():
    rs_prev = [{"rank": 1, "ticker": "A", "name": "AA", "rs": 0.5},
               {"rank": 2, "ticker": "B", "name": "BB", "rs": 0.4},
               {"rank": 3, "ticker": "C", "name": "CC", "rs": 0.3}]
    rs_cur = [{"rank": 1, "ticker": "C", "name": "CC", "rs": 0.6},
              {"rank": 2, "ticker": "A", "name": "AA", "rs": 0.5},
              {"rank": 3, "ticker": "B", "name": "BB", "rs": 0.1}]
    history = _hist({"2026-10-01": [], "2026-10-02": []},
                    {"2026-10-01": rs_prev, "2026-10-02": rs_cur})

    change = dd.daily_change(history)

    movers = change["rs_movers"]
    assert movers[0]["ticker"] == "C" and movers[0]["delta"] == 2  # 3rd -> 1st
    assert movers[-1]["ticker"] == "B" and movers[-1]["delta"] == -1


def test_daily_change_none_when_fewer_than_two_report_dates():
    assert dd.daily_change(_hist({"2026-10-02": []}, {})) is None


def test_sector_summary_counts_pass_rate_and_average_rs():
    board = dd.build_board(
        [{"ticker": "A", "name": "AA", "sector": "반도체", "provisional": False, "volume_ratio": 1.0},
         {"ticker": "B", "name": "BB", "sector": "반도체", "provisional": False, "volume_ratio": 1.0},
         {"ticker": "C", "name": "CC", "sector": "건설", "provisional": False, "volume_ratio": 1.0}],
        [{"ticker": "A", "rs": 0.10, "stock_return": 0.1}, {"ticker": "B", "rs": 0.30, "stock_return": 0.3}],
        [])

    rows = dd.sector_summary(board, {"반도체": 10, "건설": 4, "은행": 5})

    by_sector = {r["sector"]: r for r in rows}
    assert by_sector["반도체"]["passed"] == 2 and by_sector["반도체"]["universe"] == 10
    assert by_sector["반도체"]["pass_rate"] == pytest.approx(0.2)
    assert by_sector["반도체"]["avg_rs"] == pytest.approx(0.20)
    assert by_sector["건설"]["avg_rs"] is None  # no RS measured -> not 0
    assert by_sector["은행"]["passed"] == 0
    assert rows[0]["sector"] == "반도체"  # most passed first


def test_count_series_per_report_date():
    history = _hist({"2026-10-01": [{"ticker": "A"}],
                     "2026-10-02": [{"ticker": "A"}, {"ticker": "B"}]}, {})

    series = dd.count_series(history)

    assert list(series["date"]) == ["2026-10-01", "2026-10-02"]
    assert list(series["passed"]) == [1, 2]


def test_ticker_history_has_rank_and_pass_flag_per_date():
    history = _hist(
        {"2026-10-01": [], "2026-10-02": [{"ticker": "A", "provisional": True}]},
        {"2026-10-01": [{"rank": 5, "ticker": "A", "rs": 0.1}],
         "2026-10-02": [{"rank": 3, "ticker": "A", "rs": 0.2}]})

    frame = dd.ticker_history(history, "A")

    assert list(frame["date"]) == ["2026-10-01", "2026-10-02"]
    assert list(frame["rank"]) == [5, 3]
    assert list(frame["passed"]) == [False, True]


def test_ticker_history_missing_ticker_has_no_rank():
    history = _hist({"2026-10-01": []}, {"2026-10-01": [{"rank": 1, "ticker": "A", "rs": 0.1}]})

    frame = dd.ticker_history(history, "Z")

    assert pd.isna(frame["rank"].iloc[0])
    assert bool(frame["passed"].iloc[0]) is False


def test_location_timeline_orders_decisions_for_symbol():
    decisions = [
        {"symbol": "A", "evaluated_at": "2026-09-05 11:00:00", "location_score": 70, "final_state": "WATCH"},
        {"symbol": "A", "evaluated_at": "2026-09-01 11:00:00", "location_score": 10, "final_state": "IGNORE"},
        {"symbol": "B", "evaluated_at": "2026-09-02 11:00:00", "location_score": 40, "final_state": "IGNORE"},
    ]

    frame = dd.location_timeline("A", decisions)

    assert list(frame["location_score"]) == [10, 70]
    assert dd.location_timeline("Z", decisions).empty
