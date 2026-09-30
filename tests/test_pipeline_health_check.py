import sqlite3
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import pipeline_health_check as hc


def test_last_weekday_before_skips_weekend():
    # Monday 2026-09-14 -> previous weekday is Friday 2026-09-11.
    assert hc.last_weekday_before(date(2026, 9, 14)) == date(2026, 9, 11)


def test_last_weekday_before_regular_weekday():
    # Thursday -> Wednesday.
    assert hc.last_weekday_before(date(2026, 9, 17)) == date(2026, 9, 16)


def test_health_report_verdict_is_worst_of_findings():
    report = hc.HealthReport()
    report.add("OK", "fine")
    report.add("WARN", "hmm")
    assert report.verdict == "WARN"
    report.add("FAIL", "broken")
    assert report.verdict == "FAIL"


def test_health_report_verdict_pass_when_all_ok():
    report = hc.HealthReport()
    report.add("OK", "fine")
    assert report.verdict == "PASS"


def test_check_pipeline_log_fails_when_log_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "LOG_DIR", tmp_path)
    report = hc.HealthReport()
    hc.check_pipeline_log(report, date(2026, 9, 29))
    assert report.verdict == "FAIL"
    assert "2026-09-29" in report.findings[0].message


def test_check_pipeline_log_ok_when_complete_marker_present(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "LOG_DIR", tmp_path)
    (tmp_path / "2026-09-28.log").write_text(
        "=== run started_at=x ===\n...\n=== run result=COMPLETE ===\n", encoding="utf-8"
    )
    report = hc.HealthReport()
    hc.check_pipeline_log(report, date(2026, 9, 28))
    assert report.verdict == "PASS"


def test_check_pipeline_log_fails_when_blocked_marker_present(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "LOG_DIR", tmp_path)
    (tmp_path / "2026-09-28.log").write_text(
        "=== run started_at=x ===\n=== run result=BLOCKED command_exit=1 ===\n", encoding="utf-8"
    )
    report = hc.HealthReport()
    hc.check_pipeline_log(report, date(2026, 9, 28))
    assert report.verdict == "FAIL"
    assert "BLOCKED" in report.findings[0].message


def test_check_pipeline_log_warns_when_neither_marker_present(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "LOG_DIR", tmp_path)
    (tmp_path / "2026-09-28.log").write_text("=== run started_at=x ===\npartial output\n", encoding="utf-8")
    report = hc.HealthReport()
    hc.check_pipeline_log(report, date(2026, 9, 28))
    assert report.verdict == "WARN"


def _make_db(path: Path, dates: list[str]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE ohlcv_daily (date TEXT)")
    conn.executemany("INSERT INTO ohlcv_daily (date) VALUES (?)", [(d,) for d in dates])
    conn.commit()
    conn.close()


def test_check_data_freshness_ok_when_latest_covers_expected_day(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    _make_db(db_path, ["2026-09-27", "2026-09-28"])
    monkeypatch.setattr(hc, "DB_PATH", db_path)
    report = hc.HealthReport()
    hc.check_data_freshness(report, date(2026, 9, 28))
    assert report.verdict == "PASS"


def test_check_data_freshness_warns_when_stale(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    _make_db(db_path, ["2026-09-27"])
    monkeypatch.setattr(hc, "DB_PATH", db_path)
    report = hc.HealthReport()
    hc.check_data_freshness(report, date(2026, 9, 29))
    assert report.verdict == "WARN"


def test_check_data_freshness_fails_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "DB_PATH", tmp_path / "does_not_exist.sqlite")
    report = hc.HealthReport()
    hc.check_data_freshness(report, date(2026, 9, 28))
    assert report.verdict == "FAIL"


def test_check_data_health_report_ok_on_pass_status(tmp_path, monkeypatch):
    path = tmp_path / "data_health_latest.md"
    path.write_text("# LAT 5.0 Data Health\n\n**Status: PASS**\n", encoding="utf-8")
    monkeypatch.setattr(hc, "DATA_HEALTH_PATH", path)
    report = hc.HealthReport()
    hc.check_data_health_report(report)
    assert report.verdict == "PASS"


def test_check_data_health_report_warns_on_non_pass_status(tmp_path, monkeypatch):
    path = tmp_path / "data_health_latest.md"
    path.write_text("# LAT 5.0 Data Health\n\n**Status: WARN**\n", encoding="utf-8")
    monkeypatch.setattr(hc, "DATA_HEALTH_PATH", path)
    report = hc.HealthReport()
    hc.check_data_health_report(report)
    assert report.verdict == "WARN"


def test_check_data_health_report_warns_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "DATA_HEALTH_PATH", tmp_path / "missing.md")
    report = hc.HealthReport()
    hc.check_data_health_report(report)
    assert report.verdict == "WARN"


def test_render_markdown_includes_verdict_and_findings():
    report = hc.HealthReport()
    report.add("OK", "all good")
    text = hc.render_markdown(report, today=date(2026, 9, 30))
    assert "판정: PASS" in text
    assert "all good" in text
    assert "2026-09-30" in text
