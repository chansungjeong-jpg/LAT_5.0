from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from lat5.kiwoom_client import ApiPage
from lat5.leader_score import MarketLeader
from lat5.us_market_flow import CompanyFlowDecision, MarketGateDecision, USMarketObservation
from lat5.us_featured import USFeaturedStock
from lat5.us_mapping import mappings_for


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


class CollectorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def __enter__(self) -> "CollectorStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS collection_runs (
                run_id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                watchlist_count INTEGER NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                token_cache_time TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS collection_errors (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                ticker TEXT NOT NULL,
                api_id TEXT NOT NULL,
                error_code TEXT NOT NULL,
                message TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS raw_api_responses (
                id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                ticker TEXT NOT NULL,
                api_id TEXT NOT NULL,
                page_no INTEGER NOT NULL,
                collected_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ohlcv_daily (
                provider TEXT NOT NULL,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                amount REAL NOT NULL,
                collected_at TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, ticker, date)
            );
            CREATE TABLE IF NOT EXISTS ohlcv_minute (
                provider TEXT NOT NULL,
                ticker TEXT NOT NULL,
                datetime TEXT NOT NULL,
                interval TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                amount REAL NOT NULL,
                collected_at TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, ticker, datetime, interval)
            );
            CREATE TABLE IF NOT EXISTS execution_strength (
                provider TEXT NOT NULL,
                ticker TEXT NOT NULL,
                datetime TEXT NOT NULL,
                strength REAL NOT NULL,
                collected_at TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, ticker, datetime)
            );
            CREATE TABLE IF NOT EXISTS investor_flow (
                provider TEXT NOT NULL,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                foreign_net_thousand REAL NOT NULL,
                collected_at TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, ticker, date)
            );
            CREATE TABLE IF NOT EXISTS leader_observations (
                provider TEXT NOT NULL,
                market TEXT NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT NOT NULL,
                sector TEXT,
                as_of TEXT NOT NULL,
                trading_value REAL NOT NULL,
                rise_rate REAL NOT NULL,
                trading_value_rank INTEGER NOT NULL,
                rise_rate_rank INTEGER NOT NULL,
                leader_score REAL NOT NULL,
                collected_at TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, market, ticker, as_of)
            );
            CREATE TABLE IF NOT EXISTS us_market_observations (
                provider TEXT NOT NULL,
                symbol TEXT NOT NULL,
                as_of TEXT NOT NULL,
                previous_close REAL NOT NULL,
                close REAL NOT NULL,
                collected_on TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, symbol, as_of)
            );
            CREATE TABLE IF NOT EXISTS us_market_gates (
                provider TEXT NOT NULL,
                as_of TEXT NOT NULL,
                state TEXT NOT NULL,
                flow TEXT NOT NULL,
                us10y_symbol TEXT NOT NULL,
                positive_indices INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, as_of)
            );
            CREATE TABLE IF NOT EXISTS us_company_flows (
                provider TEXT NOT NULL,
                as_of TEXT NOT NULL,
                flow TEXT NOT NULL,
                direction TEXT NOT NULL,
                mean_change_pct REAL NOT NULL,
                symbols_json TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, as_of, flow)
            );
            CREATE TABLE IF NOT EXISTS us_featured_stocks (
                provider TEXT NOT NULL,
                as_of TEXT NOT NULL,
                symbol TEXT NOT NULL,
                flow TEXT NOT NULL,
                change_pct REAL NOT NULL,
                volume_ratio REAL NOT NULL,
                trading_value REAL NOT NULL,
                featured_score REAL NOT NULL,
                reason TEXT NOT NULL,
                kr_tickers_json TEXT NOT NULL,
                run_id INTEGER NOT NULL REFERENCES collection_runs(run_id),
                PRIMARY KEY(provider, as_of, symbol)
            );
            """
        )
        self.conn.commit()

    def start_run(self, watchlist_count: int, token_cache_time: datetime) -> int:
        cursor = self.conn.execute(
            """INSERT INTO collection_runs
               (started_at, status, watchlist_count, token_cache_time)
               VALUES (?, 'RUNNING', ?, ?)""",
            (_now_iso(), watchlist_count, token_cache_time.isoformat()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, success_count: int, error_count: int) -> None:
        self.conn.execute(
            """UPDATE collection_runs
               SET finished_at=?, status=?, success_count=?, error_count=?
               WHERE run_id=?""",
            (_now_iso(), status, success_count, error_count, run_id),
        )
        self.conn.commit()

    def run_status(self, run_id: int) -> str:
        row = self.conn.execute(
            "SELECT status FROM collection_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return str(row[0])

    def record_error(
        self, run_id: int, ticker: str, api_id: str, error_code: str, message: str
    ) -> None:
        self.conn.execute(
            """INSERT INTO collection_errors
               (run_id, ticker, api_id, error_code, message, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, ticker, api_id, error_code, message, _now_iso()),
        )
        self.conn.commit()

    def save_raw_page(self, run_id: int, ticker: str, page: ApiPage) -> None:
        self.conn.execute(
            """INSERT INTO raw_api_responses
               (run_id, ticker, api_id, page_no, collected_at, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                ticker,
                page.api_id,
                page.page_no,
                _now_iso(),
                json.dumps(page.payload, ensure_ascii=True, sort_keys=True),
            ),
        )
        self.conn.commit()

    def save_daily(
        self, run_id: int, rows: Iterable[dict], provider: str = "kiwoom"
    ) -> int:
        collected_at = _now_iso()
        values = [
            (
                provider,
                row["ticker"],
                row["date"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
                row["amount"],
                collected_at,
                run_id,
            )
            for row in rows
        ]
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO ohlcv_daily
               (provider,ticker,date,open,high,low,close,volume,amount,collected_at,run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,ticker,date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume, amount=excluded.amount,
                 collected_at=excluded.collected_at, run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)

    def save_minutes(
        self, run_id: int, rows: Iterable[dict], provider: str = "kiwoom"
    ) -> int:
        collected_at = _now_iso()
        values = [
            (
                provider, row["ticker"], row["datetime"], row["interval"],
                row["open"], row["high"], row["low"], row["close"],
                row["volume"], row["amount"], collected_at, run_id,
            )
            for row in rows
        ]
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO ohlcv_minute
               (provider,ticker,datetime,interval,open,high,low,close,volume,amount,collected_at,run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,ticker,datetime,interval) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, volume=excluded.volume, amount=excluded.amount,
                 collected_at=excluded.collected_at, run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)

    def save_strength(
        self, run_id: int, rows: Iterable[dict], provider: str = "kiwoom"
    ) -> int:
        collected_at = _now_iso()
        values = [
            (provider, row["ticker"], row["datetime"], row["strength"], collected_at, run_id)
            for row in rows
        ]
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO execution_strength
               (provider,ticker,datetime,strength,collected_at,run_id)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(provider,ticker,datetime) DO UPDATE SET
                 strength=excluded.strength, collected_at=excluded.collected_at,
                 run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)

    def save_foreign_flow(
        self, run_id: int, rows: Iterable[dict], provider: str = "kiwoom"
    ) -> int:
        collected_at = _now_iso()
        values = [
            (
                provider, row["ticker"], row["date"],
                row["foreign_net_thousand"], collected_at, run_id,
            )
            for row in rows
        ]
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO investor_flow
               (provider,ticker,date,foreign_net_thousand,collected_at,run_id)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(provider,ticker,date) DO UPDATE SET
                 foreign_net_thousand=excluded.foreign_net_thousand,
                 collected_at=excluded.collected_at, run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)

    def save_leader_observations(
        self,
        run_id: int,
        as_of: str,
        leaders: Iterable[MarketLeader],
        provider: str = "kiwoom",
    ) -> int:
        collected_at = _now_iso()
        values = [
            (
                provider, leader.market, leader.ticker, leader.name, leader.sector,
                as_of, leader.trading_value, leader.rise_rate,
                leader.trading_value_rank, leader.rise_rate_rank, leader.leader_score,
                collected_at, run_id,
            )
            for leader in leaders
        ]
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO leader_observations
               (provider,market,ticker,name,sector,as_of,trading_value,rise_rate,
                trading_value_rank,rise_rate_rank,leader_score,collected_at,run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,market,ticker,as_of) DO UPDATE SET
                 name=excluded.name, sector=excluded.sector,
                 trading_value=excluded.trading_value, rise_rate=excluded.rise_rate,
                 trading_value_rank=excluded.trading_value_rank,
                 rise_rate_rank=excluded.rise_rate_rank, leader_score=excluded.leader_score,
                 collected_at=excluded.collected_at, run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)

    def save_us_observations(
        self,
        run_id: int,
        observations: Iterable[USMarketObservation],
        provider: str = "yfinance",
    ) -> int:
        values = [
            (provider, item.symbol, item.as_of.isoformat(), item.previous_close,
             item.close, item.collected_on.isoformat(), run_id)
            for item in observations
        ]
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO us_market_observations
               (provider,symbol,as_of,previous_close,close,collected_on,run_id)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(provider,symbol,as_of) DO UPDATE SET
                 previous_close=excluded.previous_close, close=excluded.close,
                 collected_on=excluded.collected_on, run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)

    def save_us_market_gate(
        self, run_id: int, as_of, decision: MarketGateDecision, provider: str = "yfinance"
    ) -> None:
        self.conn.execute(
            """INSERT INTO us_market_gates
               (provider,as_of,state,flow,us10y_symbol,positive_indices,reasons_json,run_id)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,as_of) DO UPDATE SET
                 state=excluded.state, flow=excluded.flow,
                 us10y_symbol=excluded.us10y_symbol,
                 positive_indices=excluded.positive_indices,
                 reasons_json=excluded.reasons_json, run_id=excluded.run_id""",
            (provider, as_of.isoformat(), decision.state, decision.flow,
             decision.us10y_symbol, decision.positive_indices,
             json.dumps(decision.reasons), run_id),
        )
        self.conn.commit()

    def save_us_company_flows(
        self, run_id: int, as_of, flows: Iterable[CompanyFlowDecision], provider: str = "yfinance"
    ) -> int:
        values = [
            (provider, as_of.isoformat(), item.flow, item.direction,
             item.mean_change_pct, json.dumps(item.symbols), run_id)
            for item in flows
        ]
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO us_company_flows
               (provider,as_of,flow,direction,mean_change_pct,symbols_json,run_id)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(provider,as_of,flow) DO UPDATE SET
                 direction=excluded.direction, mean_change_pct=excluded.mean_change_pct,
                 symbols_json=excluded.symbols_json, run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)

    def save_us_featured_stocks(
        self,
        run_id: int,
        as_of,
        stocks: Iterable[USFeaturedStock],
        provider: str = "yfinance",
    ) -> int:
        values = []
        for stock in stocks:
            mapping = mappings_for(stock.symbol)
            if mapping is None:
                raise ValueError(f"unmapped featured symbol: {stock.symbol}")
            values.append(
                (
                    provider, as_of.isoformat(), stock.symbol, stock.flow,
                    stock.change_pct, stock.volume_ratio, stock.trading_value,
                    stock.featured_score, stock.reason,
                    json.dumps(mapping.kr_tickers), run_id,
                )
            )
        if not values:
            return 0
        self.conn.executemany(
            """INSERT INTO us_featured_stocks
               (provider,as_of,symbol,flow,change_pct,volume_ratio,trading_value,
                featured_score,reason,kr_tickers_json,run_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,as_of,symbol) DO UPDATE SET
                 flow=excluded.flow, change_pct=excluded.change_pct,
                 volume_ratio=excluded.volume_ratio, trading_value=excluded.trading_value,
                 featured_score=excluded.featured_score, reason=excluded.reason,
                 kr_tickers_json=excluded.kr_tickers_json, run_id=excluded.run_id""",
            values,
        )
        self.conn.commit()
        return len(values)
