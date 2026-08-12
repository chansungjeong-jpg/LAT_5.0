from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class WatchItem:
    ticker: str
    name: str
    sector: str


_EXCLUDED_SECTOR_TERMS = ("display", "game", "content", "디스플레이", "게임", "콘텐츠")


def parse_watchlist(path: str | Path) -> list[WatchItem]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    in_core = False
    sector: str | None = None
    items: list[WatchItem] = []
    seen: set[tuple[str, str]] = set()

    for line in lines:
        if line.startswith("## 3.") or line.strip() == "## 3. Core Watchlist":
            in_core = True
            continue
        if in_core and line.startswith("## "):
            break
        if not in_core:
            continue
        if line.startswith("### "):
            sector = re.sub(r"^\d+(?:\.\d+)*\s*", "", line[4:].strip())
            continue
        if not sector or not line.startswith("|"):
            continue
        columns = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(columns) < 3 or not re.fullmatch(r"\d{6}", columns[2]):
            continue
        if any(term in sector.lower() for term in _EXCLUDED_SECTOR_TERMS):
            continue
        key = (columns[2], sector)
        if key not in seen:
            items.append(WatchItem(columns[2], columns[1], sector))
            seen.add(key)
    return items


class KiwoomDataStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        uri = f"file:{self.path.as_posix()}?mode=ro"
        self.conn = sqlite3.connect(uri, uri=True)
        tables = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.daily_table = "ohlcv_daily" if "ohlcv_daily" in tables else "ohlcv"
        self.lat_schema = self.daily_table == "ohlcv_daily"

    def _columns(self, table: str) -> set[str]:
        return {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def __enter__(self) -> "KiwoomDataStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.conn.close()

    def load_daily(self, ticker: str) -> pd.DataFrame:
        provider_filter = " AND provider='kiwoom'" if self.lat_schema else ""
        frame = pd.read_sql_query(
            f"""SELECT date, open, high, low, close, volume, amount
                FROM {self.daily_table}
                WHERE ticker=?{provider_filter} ORDER BY date""",
            self.conn,
            params=(ticker,),
        )
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        return frame.dropna(subset=["date"]).set_index("date").sort_index()

    def load_minutes(self, ticker: str, interval: str = "5") -> pd.DataFrame:
        columns = self._columns("ohlcv_minute")
        amount_select = ", amount" if "amount" in columns else ""
        provider_filter = " AND provider='kiwoom'" if "provider" in columns else ""
        frame = pd.read_sql_query(
            f"""SELECT datetime, open, high, low, close, volume{amount_select}
                FROM ohlcv_minute
                WHERE ticker=? AND interval=? AND datetime<>''{provider_filter}
                ORDER BY datetime""",
            self.conn,
            params=(ticker, interval),
        )
        if frame.empty:
            return frame
        frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
        frame = frame.dropna(subset=["datetime"]).set_index("datetime").sort_index()
        if "amount" not in frame:
            frame["amount"] = frame["close"].astype(float) * frame["volume"].astype(float)
        return frame

    def load_foreign_flow(self, ticker: str) -> pd.DataFrame:
        columns = self._columns("investor_flow")
        value_column = (
            "foreign_net_thousand AS foreign_net"
            if "foreign_net_thousand" in columns
            else "foreign_net"
        )
        provider_filter = " AND provider='kiwoom'" if "provider" in columns else ""
        frame = pd.read_sql_query(
            f"""SELECT date, {value_column} FROM investor_flow
                WHERE ticker=?{provider_filter} ORDER BY date""",
            self.conn,
            params=(ticker,),
        )
        if frame.empty:
            return frame
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        return frame.dropna(subset=["date"]).set_index("date").sort_index()


def aggregate_60m(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return bars.copy()
    work = bars.copy().sort_index()
    minute_of_day = work.index.hour * 60 + work.index.minute
    valid = (minute_of_day >= 9 * 60) & (minute_of_day <= 15 * 60 + 30)
    work = work.loc[valid]
    minute_of_day = minute_of_day[valid]
    block = ((minute_of_day - 9 * 60) // 60).astype(int)
    work["_block"] = work.index.normalize() + pd.to_timedelta(9 + block, unit="h")
    return work.groupby("_block", sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
    ).rename_axis("datetime")


def aggregate_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily bars into Friday-labelled weekly bars."""
    if daily.empty:
        return daily.copy()
    work = daily.copy().sort_index()
    aggregation = {
        "open": ("open", "first"),
        "high": ("high", "max"),
        "low": ("low", "min"),
        "close": ("close", "last"),
        "volume": ("volume", "sum"),
    }
    if "amount" in work.columns:
        aggregation["amount"] = ("amount", "sum")
    return work.resample("W-FRI", label="right", closed="right").agg(**aggregation).dropna(
        subset=["open", "high", "low", "close"]
    )


def daily_ema_context(daily: pd.DataFrame) -> pd.DataFrame:
    close = daily["close"].astype(float).sort_index()
    return pd.DataFrame(
        {
            "ema10": close.ewm(span=10, adjust=False, min_periods=10).mean().shift(1),
            "ema20": close.ewm(span=20, adjust=False, min_periods=20).mean().shift(1),
        }
    )
