"""Read-only data layer for the LAT 5.0 Streamlit cockpit.

Everything here only reads saved artifacts and the market DB (opened with
``mode=ro``). Nothing is collected, ordered or notified. A missing or
unreadable input is reported as an issue -- never silently treated as
"passed" or as zero.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from lat5.candidate_board import CandidateRow, build_candidate_board, latest_decision_by_symbol
from lat5.data import aggregate_60m, parse_watchlist

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


# ---------------------------------------------------------------------------
# History from the dated daily reports (recovery filter / RS), day-over-day
# change, sector summary, and per-symbol timelines. Reports are written live
# by the daily pipeline, so each one only reflects data available that day.
# ---------------------------------------------------------------------------

_TICKER = re.compile(r"\d{6}")


def _cells(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


def parse_filter_report(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 7 or not _TICKER.fullmatch(cells[0]):
            continue
        ratio = cells[6].replace("배", "").strip()
        try:
            volume_ratio = float(ratio)
        except ValueError:
            volume_ratio = None
        rows.append({"ticker": cells[0], "name": cells[1], "sector": cells[2],
                     "provisional": cells[3] == "잠정", "volume_ratio": volume_ratio})
    return rows


def _percent(cell: str) -> float | None:
    cleaned = cell.replace("%p", "").replace("%", "").replace("+", "").strip()
    try:
        return float(cleaned) / 100.0
    except ValueError:
        return None


def parse_rs_report(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = _cells(line)
        if len(cells) < 6 or not cells[0].isdigit() or not _TICKER.fullmatch(cells[1]):
            continue
        rows.append({"rank": int(cells[0]), "ticker": cells[1], "name": cells[2],
                     "stock_return": _percent(cells[3]), "rs": _percent(cells[5])})
    return rows


@dataclass
class History:
    filter_by_date: dict[str, list[dict]] = field(default_factory=dict)
    rs_by_date: dict[str, list[dict]] = field(default_factory=dict)


def _load_dated(folder: Path, parser) -> dict[str, list[dict]]:
    if not folder.exists():
        return {}
    out: dict[str, list[dict]] = {}
    for path in sorted(folder.glob("*.md")):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
            continue
        try:
            out[path.stem] = parser(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return out


def load_history(root: Path) -> History:
    reports = Path(root) / "reports"
    return History(
        filter_by_date=_load_dated(reports / "monthly_weekly_filter", parse_filter_report),
        rs_by_date=_load_dated(reports / "relative_strength", parse_rs_report),
    )


def daily_change(history: History) -> dict | None:
    dates = sorted(history.filter_by_date)
    if len(dates) < 2:
        return None
    prev_date, date_ = dates[-2], dates[-1]
    prev = {r["ticker"]: r for r in history.filter_by_date[prev_date]}
    cur = {r["ticker"]: r for r in history.filter_by_date[date_]}
    movers: list[dict] = []
    rs_dates = sorted(history.rs_by_date)
    rs_prev_date = rs_date = None
    if len(rs_dates) >= 2:
        rs_prev_date, rs_date = rs_dates[-2], rs_dates[-1]
        before = {r["ticker"]: r for r in history.rs_by_date[rs_prev_date]}
        for row in history.rs_by_date[rs_date]:
            old = before.get(row["ticker"])
            if old is None or old["rank"] == row["rank"]:
                continue
            movers.append({"ticker": row["ticker"], "name": row["name"], "prev_rank": old["rank"],
                           "rank": row["rank"], "delta": old["rank"] - row["rank"], "rs": row["rs"]})
        movers.sort(key=lambda m: (-m["delta"], m["rank"]))
    return {
        "date": date_, "prev_date": prev_date,
        "new": [cur[t] for t in cur if t not in prev],
        "exited": [prev[t] for t in prev if t not in cur],
        "confirmed": [cur[t] for t in cur if t in prev and prev[t]["provisional"] and not cur[t]["provisional"]],
        "rs_date": rs_date, "rs_prev_date": rs_prev_date, "rs_movers": movers,
    }


def universe_by_sector(watchlist_path: Path | str) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        items = parse_watchlist(watchlist_path)
    except OSError:
        return counts
    for item in items:
        counts[item.sector] = counts.get(item.sector, 0) + 1
    return counts


def sector_summary(board: list[CandidateRow], universe: dict[str, int]) -> list[dict]:
    sectors = set(universe) | {r.sector or "미분류" for r in board}
    rows = []
    for sector in sectors:
        members = [r for r in board if (r.sector or "미분류") == sector]
        rs_values = [r.rs for r in members if r.rs is not None]
        total = universe.get(sector)
        rows.append({
            "sector": sector, "passed": len(members), "universe": total,
            "pass_rate": (len(members) / total) if total else None,
            "avg_rs": (sum(rs_values) / len(rs_values)) if rs_values else None,
        })
    rows.sort(key=lambda r: (-r["passed"], r["sector"]))
    return rows


def count_series(history: History) -> pd.DataFrame:
    dates = sorted(history.filter_by_date)
    return pd.DataFrame({
        "date": dates,
        "passed": [len(history.filter_by_date[d]) for d in dates],
        "provisional": [sum(1 for r in history.filter_by_date[d] if r.get("provisional")) for d in dates],
    })


def ticker_history(history: History, ticker: str) -> pd.DataFrame:
    dates = sorted(set(history.filter_by_date) | set(history.rs_by_date))
    rows = []
    for day in dates:
        rs_row = next((r for r in history.rs_by_date.get(day, []) if r["ticker"] == ticker), None)
        passed_row = next((r for r in history.filter_by_date.get(day, []) if r["ticker"] == ticker), None)
        rows.append({
            "date": day,
            "rank": rs_row["rank"] if rs_row else float("nan"),
            "rs": rs_row["rs"] if rs_row else None,
            "passed": passed_row is not None,
            "provisional": bool(passed_row and passed_row.get("provisional")),
            "in_filter_report": day in history.filter_by_date,
        })
    return pd.DataFrame(rows, columns=["date", "rank", "rs", "passed", "provisional", "in_filter_report"])


def location_timeline(symbol: str, decisions: list[dict]) -> pd.DataFrame:
    rows = [d for d in decisions if str(d.get("symbol")) == str(symbol)]
    frame = pd.DataFrame(
        [{"evaluated_at": pd.to_datetime(d.get("evaluated_at"), errors="coerce"),
          "location_score": d.get("location_score"), "final_state": d.get("final_state")} for d in rows],
        columns=["evaluated_at", "location_score", "final_state"])
    return frame.sort_values("evaluated_at").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Intraday bars (regular session 09:00-15:30 only, same window the 60-minute
# location score uses) and EMAs.
# ---------------------------------------------------------------------------

_MINUTE_COLUMNS = ["datetime", "open", "high", "low", "close", "volume", "amount"]


def _read_minutes(db_path: Path | str, ticker: str, interval: str, limit: int) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame(columns=_MINUTE_COLUMNS)
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            frame = pd.read_sql_query(
                "SELECT datetime, open, high, low, close, volume, amount FROM ohlcv_minute "
                "WHERE ticker=? AND interval=? AND provider='kiwoom' AND datetime<>'' "
                "ORDER BY datetime DESC LIMIT ?",
                conn, params=(str(ticker), str(interval), int(limit)))
        finally:
            conn.close()
    except (sqlite3.Error, pd.errors.DatabaseError):
        return pd.DataFrame(columns=_MINUTE_COLUMNS)
    return frame.sort_values("datetime").reset_index(drop=True)


def load_minute_frame(db_path: Path | str, ticker: str, interval: str = "5", limit: int = 1000) -> pd.DataFrame:
    frame = _read_minutes(db_path, ticker, interval, limit)
    if frame.empty:
        return frame
    stamps = pd.to_datetime(frame["datetime"], errors="coerce")
    minute_of_day = stamps.dt.hour * 60 + stamps.dt.minute
    regular = (minute_of_day >= 9 * 60) & (minute_of_day <= 15 * 60 + 30)
    return frame.loc[regular.fillna(False)].reset_index(drop=True)


def load_hourly_frame(db_path: Path | str, ticker: str, limit_5m: int = 3600) -> pd.DataFrame:
    frame = _read_minutes(db_path, ticker, "5", limit_5m)
    if frame.empty:
        return frame
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    hourly = aggregate_60m(frame.dropna(subset=["datetime"]).set_index("datetime"))
    hourly = hourly.reset_index()
    hourly["datetime"] = hourly["datetime"].dt.strftime("%Y-%m-%d %H:%M")
    return hourly


def with_emas(frame: pd.DataFrame, spans: tuple[int, ...]) -> pd.DataFrame:
    out = frame.copy()
    for span in spans:
        out[f"ema{span}"] = out["close"].astype(float).ewm(span=span, adjust=False, min_periods=span).mean()
    return out
