"""Read-only data layer for the LAT 5.0 Streamlit cockpit.

Everything here only reads saved artifacts and the market DB (opened with
``mode=ro``). Nothing is collected, ordered or notified. A missing or
unreadable input is reported as an issue -- never silently treated as
"passed" or as zero.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from lat5.candidate_board import CandidateRow, build_candidate_board, latest_decision_by_symbol

DIAGNOSTICS_FILE = "backtest_diagnostics.json"
FILTER_FILE = "monthly_weekly_filter.json"
RS_FILE = "relative_strength.json"

STAGE_UNIVERSE = "관찰 목록"
STAGE_RECOVERY = "월10·주5 회복 통과"
STAGE_RS = "RS 양수"
STAGE_LOCATION = "위치점수 평가"
STAGE_ELIGIBLE = "매수 가능"


@dataclass
class Payloads:
    diagnostics: dict | None
    filter_payload: dict | None
    rs_payload: dict | None
    issues: list[dict] = field(default_factory=list)

    @property
    def location_decisions(self) -> list[dict]:
        return list((self.diagnostics or {}).get("location_decisions") or [])

    @property
    def universe(self) -> int | None:
        value = (self.diagnostics or {}).get("universe_symbols")
        return int(value) if value is not None else None


def _read_json(path: Path, issues: list[dict]) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        issues.append({"source": path.name, "error": "파일 없음"})
    except (OSError, ValueError) as exc:
        issues.append({"source": path.name, "error": f"읽기 실패: {exc.__class__.__name__}"})
    return None


def load_payloads(root: Path) -> Payloads:
    scoring = Path(root) / "artifacts" / "latest_scoring"
    issues: list[dict] = []
    raw = _read_json(scoring / DIAGNOSTICS_FILE, issues)
    diagnostics = raw.get("diagnostics") if isinstance(raw, dict) else None
    if raw is not None and diagnostics is None:
        issues.append({"source": DIAGNOSTICS_FILE, "error": "diagnostics 키 없음"})
    filter_payload = _read_json(scoring / FILTER_FILE, issues)
    rs_payload = _read_json(scoring / RS_FILE, issues)
    return Payloads(diagnostics, filter_payload, rs_payload, issues)


def build_board(
    filter_rows: list[dict], rs_rows: list[dict], decisions: list[dict]
) -> list[CandidateRow]:
    return build_candidate_board(
        filter_rows=filter_rows, rs_rows=rs_rows, location_decisions=decisions
    )


def decision_for(symbol: str, decisions: list[dict]) -> dict | None:
    return latest_decision_by_symbol(decisions).get(str(symbol))


def build_funnel(*, universe: int | None, board: list[CandidateRow]) -> dict:
    """Stage counts of the selection chain. A zero stage is where the chain
    dies; an unknown universe is ``None`` (not 0, not passed)."""
    stages = [
        {"단계": STAGE_UNIVERSE, "건수": universe},
        {"단계": STAGE_RECOVERY, "건수": len(board)},
        {"단계": STAGE_RS, "건수": sum(1 for r in board if r.rs is not None and r.rs > 0)},
        {"단계": STAGE_LOCATION, "건수": sum(1 for r in board if r.location_score is not None)},
        {"단계": STAGE_ELIGIBLE, "건수": sum(1 for r in board if r.entry_eligible is True)},
    ]
    halt = next((s for s in stages[1:] if s["건수"] == 0), None)
    return {"stages": stages, "halt": halt}


def _expected_data_date(today: date, now_time=None) -> date:
    """Newest weekday whose daily bar should already be collected. The
    pipeline collects at 16:00 (~35 min), so before 16:40 today's bar is not
    expected yet. KRX holidays are unknown here -- callers phrase a stale
    result as "확인 필요", not as a failure."""
    cursor = today
    after_close = now_time is not None and now_time >= datetime.strptime("16:40", "%H:%M").time()
    if not after_close or cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def status_band(
    funnel: dict,
    board: list[CandidateRow],
    *,
    data_date: str | None,
    today: date,
    issues: list[dict],
    now_time=None,
) -> dict:
    eligible = sum(1 for r in board if r.entry_eligible is True)
    if issues or funnel["stages"][0]["건수"] is None:
        sources = ", ".join(str(i.get("source")) for i in issues) or "입력 파일"
        return {
            "level": "stop",
            "verdict": "🔴 판단 불가 · 산출물을 읽지 못함 (확인 불가)",
            "why": f"{sources} 를 읽지 못했으며 통과로 간주하지 않음",
        }
    expected = _expected_data_date(today, now_time)
    if data_date is None or data_date < expected.isoformat():
        shown = data_date or "없음"
        return {
            "level": "hold",
            "verdict": "🟡 신규 판단 불가 · 시장 데이터가 최신 거래일이 아님",
            "why": f"DB 최신 일봉 {shown} < 기대 {expected.isoformat()} · 휴장일이면 정상, 아니면 수집 확인 필요",
        }
    halt = funnel["halt"]
    if eligible > 0:
        return {
            "level": "go",
            "verdict": f"🟢 매수 가능 {eligible}건 · 관찰용 판정",
            "why": "위치점수·손익비 조건 충족 기록 · 주문/알림 실행 없음 · 사용자 판단 필요",
        }
    if halt:
        why = f"체인이 「{halt['단계']}」에서 0건 · 오류가 아니라 조건 미충족"
    else:
        why = "위치점수 평가 종목은 있으나 차단 사유 존재 · 오류 아님"
    return {"level": "hold", "verdict": "🟡 매수 가능 0건 · 60분 셋업 대기", "why": why}


def load_daily_frame(db_path: Path | str, ticker: str, limit: int = 160) -> pd.DataFrame:
    """Last ``limit`` daily bars, oldest first. Empty frame if unreadable."""
    path = Path(db_path)
    columns = ["date", "open", "high", "low", "close", "volume"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            frame = pd.read_sql_query(
                "SELECT date, open, high, low, close, volume FROM ohlcv_daily "
                "WHERE ticker=? ORDER BY date DESC LIMIT ?",
                conn,
                params=(str(ticker), int(limit)),
            )
        finally:
            conn.close()
    except sqlite3.Error:
        return pd.DataFrame(columns=columns)
    return frame.sort_values("date").reset_index(drop=True)


def latest_data_date(db_path: Path | str) -> str | None:
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT MAX(date) FROM ohlcv_daily").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def with_moving_averages(frame: pd.DataFrame, windows: tuple[int, ...] = (5, 20, 60)) -> pd.DataFrame:
    out = frame.copy()
    for window in windows:
        out[f"sma{window}"] = out["close"].astype(float).rolling(window, min_periods=window).mean()
    return out
