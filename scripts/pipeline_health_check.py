"""Morning health check for the LAT5 daily pipeline scheduled task.

Runs BEFORE the 16:00 pipeline (intended trigger: 08:00 daily), so it
only ever reports on *yesterday's* run -- it never triggers or modifies
the pipeline itself. Read-only against the DB, log files, and the
Windows Task Scheduler state (`schtasks /Query`).

Usage: python scripts/pipeline_health_check.py
Output: reports/pipeline_health/<today>.md (+ prints verdict to stdout)
Exit code: 0 = PASS, 1 = WARN, 2 = FAIL (visible in the task's own
LastTaskResult as a secondary signal, in addition to the report file).
"""

from __future__ import annotations

import locale
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

# schtasks writes in the console's ANSI codepage (cp949 on Korean Windows),
# not UTF-8 -- decode with that, not the subprocess default, or Korean
# field values (state/result text) come back mangled and field-matching
# silently breaks.
_CONSOLE_ENCODING = locale.getpreferredencoding(False)

# The parent console/terminal running this script may itself be locked to
# a narrower codepage than the file we write (always UTF-8) -- never let a
# stdout print crash the whole check over a display-only character.
sys.stdout.reconfigure(encoding=sys.stdout.encoding or "utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "lat5_market.db"
LOG_DIR = ROOT / "reports" / "daily_pipeline"
DATA_HEALTH_PATH = ROOT / "reports" / "data_health_latest.md"
OUTPUT_DIR = ROOT / "reports" / "pipeline_health"
TASK_NAME = "LAT5_Monthly10_Weekly5_Recovery"


def last_weekday_before(day: date) -> date:
    """Most recent Mon-Fri strictly before `day`. Does not know about
    KRX holidays (Chuseok etc.) -- callers must treat a resulting WARN
    as "check manually", not "pipeline is broken", the same way the
    pipeline's own COMPLETE-with-zero-new-rows already does for holidays.
    """
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:  # Sat=5, Sun=6
        cursor -= timedelta(days=1)
    return cursor


@dataclass
class Finding:
    level: str  # "OK" | "WARN" | "FAIL"
    message: str


@dataclass
class HealthReport:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, message: str) -> None:
        self.findings.append(Finding(level, message))

    @property
    def verdict(self) -> str:
        if any(f.level == "FAIL" for f in self.findings):
            return "FAIL"
        if any(f.level == "WARN" for f in self.findings):
            return "WARN"
        return "PASS"


def check_scheduled_task(report: HealthReport) -> None:
    # `/FO LIST` field names are localized (Korean on this machine) and
    # mismatch this script's English key lookups, so the check silently
    # fell through to "OK" -- `/FO CSV` has locale-independent, documented
    # fixed column positions (Next Run Time=2, Last Run Time=5,
    # Last Result=6, Scheduled Task State=11), so parse by index instead.
    try:
        completed = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "CSV", "/V"],
            capture_output=True, text=True, timeout=30,
            encoding=_CONSOLE_ENCODING, errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.add("WARN", f"schtasks 조회 실패: {exc!r} — 태스크 상태 확인 불가.")
        return
    if completed.returncode != 0:
        report.add(
            "WARN",
            f"schtasks 조회 실패(exit={completed.returncode}): {completed.stderr.strip()[:200]}",
        )
        return

    import csv
    import io

    rows = list(csv.reader(io.StringIO(completed.stdout)))
    data_rows = [r for r in rows if len(r) > 11 and r != rows[0]]
    if not data_rows:
        report.add("WARN", f"schtasks CSV 출력 파싱 실패 — 태스크 '{TASK_NAME}' 상태 확인 불가.")
        return
    row = data_rows[0]
    next_run, last_run, last_result = row[2], row[5], row[6]
    scheduled_task_state = row[11]

    # "Enabled"/"사용" (localized) both start differently, so check for the
    # disabled value directly instead of an exact "enabled" string match.
    if "사용 안 함" in scheduled_task_state or scheduled_task_state.strip().lower() == "disabled":
        report.add("FAIL", f"태스크 '{TASK_NAME}' 상태={scheduled_task_state} (비활성).")

    if last_result and last_result.strip() not in ("0", ""):
        report.add(
            "FAIL",
            f"태스크 '{TASK_NAME}' 마지막 실행 결과 코드={last_result} (0이 아님 — 실패). "
            f"Last Run Time={last_run}, Next Run Time={next_run}.",
        )
    else:
        report.add("OK", f"태스크 마지막 실행 결과=0(성공). Last Run Time={last_run}.")


def check_pipeline_log(report: HealthReport, expected_day: date) -> None:
    log_path = LOG_DIR / f"{expected_day.isoformat()}.log"
    if not log_path.exists():
        report.add(
            "FAIL",
            f"어제({expected_day.isoformat()}, 평일) 파이프라인 로그가 없음 — "
            f"태스크가 아예 실행 안 됐을 가능성({log_path}).",
        )
        return
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "=== run result=COMPLETE ===" in text:
        report.add("OK", f"{expected_day.isoformat()} 로그: run result=COMPLETE.")
    elif "=== run result=BLOCKED" in text:
        blocked_line = next(
            (line for line in text.splitlines() if line.startswith("=== run result=BLOCKED")),
            "",
        )
        report.add("FAIL", f"{expected_day.isoformat()} 로그: {blocked_line}")
    else:
        report.add(
            "WARN",
            f"{expected_day.isoformat()} 로그는 있으나 완료/차단 마커가 없음 — 중간에 끊겼을 가능성.",
        )


def check_data_freshness(report: HealthReport, expected_day: date) -> None:
    if not DB_PATH.exists():
        report.add("FAIL", f"DB 파일 없음: {DB_PATH}")
        return
    with sqlite3.connect(str(DB_PATH)) as conn:
        cursor = conn.execute("SELECT MAX(date) FROM ohlcv_daily")
        row = cursor.fetchone()
    latest_date = row[0] if row else None
    if latest_date is None:
        report.add("FAIL", "ohlcv_daily에 데이터가 전혀 없음.")
        return
    if latest_date >= expected_day.isoformat():
        report.add("OK", f"ohlcv_daily 최신 날짜={latest_date} (평일 기준 최신).")
    else:
        report.add(
            "WARN",
            f"ohlcv_daily 최신 날짜={latest_date} < 기대 평일 {expected_day.isoformat()} — "
            "신규 캔들 없음. 휴장일이면 정상, 아니면 수집 실패.",
        )


def check_data_health_report(report: HealthReport) -> None:
    if not DATA_HEALTH_PATH.exists():
        report.add("WARN", f"{DATA_HEALTH_PATH} 없음.")
        return
    text = DATA_HEALTH_PATH.read_text(encoding="utf-8", errors="replace")
    first_lines = "\n".join(text.splitlines()[:5])
    if "Status: PASS" in first_lines:
        report.add("OK", "data_health_latest.md: PASS.")
    elif "Status:" in first_lines:
        status_line = next((line for line in text.splitlines() if line.startswith("**Status")), "")
        report.add("WARN", f"data_health_latest.md: {status_line}")
    else:
        report.add("WARN", "data_health_latest.md에서 Status 줄을 못 찾음.")


def run() -> HealthReport:
    today = date.today()
    expected_day = last_weekday_before(today)
    report = HealthReport()
    check_scheduled_task(report)
    check_pipeline_log(report, expected_day)
    check_data_freshness(report, expected_day)
    check_data_health_report(report)
    return report


def render_markdown(report: HealthReport, *, today: date) -> str:
    lines = [
        f"# LAT5 파이프라인 아침 점검 — {today.isoformat()}",
        "",
        f"**판정: {report.verdict}**",
        "",
    ]
    icon = {"OK": "OK", "WARN": "WARN", "FAIL": "FAIL"}
    for finding in report.findings:
        lines.append(f"- [{icon[finding.level]}] {finding.message}")
    lines.append("")
    lines.append(
        "이 점검은 08:00경 실행되어 **어제 실행분**만 본다. 오늘 16:00 파이프라인은 아직 돌기 전이므로 "
        "오늘자 신선도는 판단 대상이 아니다."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    today = date.today()
    report = run()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{today.isoformat()}.md"
    output_path.write_text(render_markdown(report, today=today), encoding="utf-8")
    print(f"verdict={report.verdict} report={output_path}")
    for finding in report.findings:
        print(f"[{finding.level}] {finding.message}")
    return {"PASS": 0, "WARN": 1, "FAIL": 2}[report.verdict]


if __name__ == "__main__":
    sys.exit(main())
