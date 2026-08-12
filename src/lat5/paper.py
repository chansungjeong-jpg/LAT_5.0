from __future__ import annotations

import json
import sqlite3
from math import floor
from pathlib import Path
from typing import Any


def size_position(
    equity: float,
    entry: float,
    stop: float,
    risk_fraction: float = 0.005,
    max_exposure_fraction: float = 0.20,
) -> int:
    risk_per_share = entry - stop
    if equity <= 0 or entry <= 0 or risk_per_share <= 0:
        return 0
    risk_quantity = floor(equity * risk_fraction / risk_per_share)
    exposure_quantity = floor(equity * max_exposure_fraction / entry)
    return max(0, min(risk_quantity, exposure_quantity))


def paper_entry_fill(
    trigger: float,
    limit: float,
    next_open: float,
    bar_high: float,
    slippage_bps: float = 5.0,
) -> float | None:
    if min(trigger, limit, next_open, bar_high) <= 0 or limit < trigger:
        return None
    if next_open > limit or bar_high < trigger:
        return None
    observed = max(trigger, next_open)
    fill = observed * (1.0 + slippage_bps / 10_000.0)
    return fill if fill <= limit else None


def paper_exit_fill(
    stop: float,
    target: float,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    slippage_bps: float = 5.0,
) -> tuple[float, str] | None:
    sell_factor = 1.0 - slippage_bps / 10_000.0
    if bar_open <= stop:
        return bar_open * sell_factor, "STOP_GAP"
    if bar_low <= stop:
        return stop * sell_factor, "STOP"
    if bar_open >= target:
        return bar_open * sell_factor, "TARGET_GAP"
    if bar_high >= target:
        return target * sell_factor, "TARGET"
    return None


class PaperLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def __enter__(self) -> "PaperLedger":
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
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                sector TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                algorithm_version TEXT NOT NULL,
                inputs_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_decision_version
                ON decisions(strategy_id, algorithm_version, timestamp);

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY,
                decision_id INTEGER NOT NULL REFERENCES decisions(id),
                trigger_price REAL NOT NULL,
                limit_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                target_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                timestamp TEXT NOT NULL,
                price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                fill_type TEXT NOT NULL,
                fee REAL NOT NULL,
                tax REAL NOT NULL,
                slippage REAL NOT NULL
            );
            """
        )
        self.conn.commit()

    def record_decision(
        self,
        timestamp: str,
        ticker: str,
        sector: str,
        decision: str,
        reason: str,
        strategy_id: str,
        algorithm_version: str,
        inputs: dict[str, Any],
    ) -> int:
        cursor = self.conn.execute(
            """INSERT INTO decisions
               (timestamp, ticker, sector, decision, reason, strategy_id,
                algorithm_version, inputs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                timestamp,
                ticker,
                sector,
                decision,
                reason,
                strategy_id,
                algorithm_version,
                json.dumps(inputs, ensure_ascii=True, sort_keys=True),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def create_order(
        self,
        decision_id: int,
        trigger_price: float,
        limit_price: float,
        stop_price: float,
        target_price: float,
        quantity: int,
        created_at: str,
        expires_at: str,
    ) -> int:
        cursor = self.conn.execute(
            """INSERT INTO orders
               (decision_id, trigger_price, limit_price, stop_price, target_price,
                quantity, status, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)""",
            (
                decision_id,
                trigger_price,
                limit_price,
                stop_price,
                target_price,
                quantity,
                created_at,
                expires_at,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def record_fill(
        self,
        order_id: int,
        timestamp: str,
        price: float,
        quantity: int,
        fill_type: str,
        fee: float,
        tax: float,
        slippage: float,
    ) -> int:
        cursor = self.conn.execute(
            """INSERT INTO fills
               (order_id, timestamp, price, quantity, fill_type, fee, tax, slippage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_id, timestamp, price, quantity, fill_type, fee, tax, slippage),
        )
        if fill_type == "ENTRY":
            self.conn.execute("UPDATE orders SET status='FILLED' WHERE id=?", (order_id,))
        self.conn.commit()
        return int(cursor.lastrowid)

    def decision_count(self, strategy_id: str, algorithm_version: str) -> int:
        row = self.conn.execute(
            """SELECT COUNT(*) FROM decisions
               WHERE strategy_id=? AND algorithm_version=?""",
            (strategy_id, algorithm_version),
        ).fetchone()
        return int(row[0])
