# LAT 5.0 Paper And Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paper-only LAT engine with deterministic strategy rules, an auditable SQLite ledger, and a historical technical-baseline backtest against the existing Kiwoom database.

**Architecture:** Keep pure strategy calculations separate from Kiwoom/SQLite adapters. Feed the same decision objects to paper execution and historical replay so entry, stop, target, and outcome semantics cannot drift.

**Tech Stack:** Python 3.13, pandas 2.3, SQLite, pytest 9.

## Global Constraints

- Core Watchlist only; display and game/content excluded.
- No live orders.
- Missing required data remains UNKNOWN and fails closed.
- No look-ahead: only completed bars and prior known daily values.
- Existing `short/trading_data.db` is opened read-only and never modified.

---

### Task 1: Strategy Core

**Files:**
- Create: `pyproject.toml`
- Create: `src/lat5/models.py`
- Create: `src/lat5/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Produces: score functions returning `MetricScore(points, max_points, known)` and `classify_sector(...)`.

- [ ] Write tests for all score boundaries, daily trend states, and missing-value score bounds.
- [ ] Run `pytest tests/test_scoring.py -v` and verify missing-module failure.
- [ ] Implement the minimum immutable models and score functions.
- [ ] Re-run the focused tests and verify pass.

### Task 2: Channel And ABC Trigger

**Files:**
- Create: `src/lat5/patterns.py`
- Test: `tests/test_patterns.py`

**Interfaces:**
- Consumes: OHLCV DataFrames with a sorted `datetime` index.
- Produces: `Channel`, `Anchor`, and `ABCSetup` immutable values or explicit unknown reasons.

- [ ] Write tests for confirmed pivots, rising-channel position, Anchor qualification, valid higher-low ABC, and 36-bar expiry.
- [ ] Run `pytest tests/test_patterns.py -v` and verify missing-module failure.
- [ ] Implement pure pattern functions without future-bar access at decision time.
- [ ] Re-run focused tests and verify pass.

### Task 3: Paper Ledger And Execution

**Files:**
- Create: `src/lat5/paper.py`
- Test: `tests/test_paper.py`

**Interfaces:**
- Produces: `PaperLedger`, `PaperOrder`, `PaperFill`, and position-sizing behavior.

- [ ] Write tests for schema creation, decision persistence, risk sizing, no-chase fills, stop-first gap exits, and version isolation.
- [ ] Run `pytest tests/test_paper.py -v` and verify missing-module failure.
- [ ] Implement SQLite tables and deterministic paper-fill rules.
- [ ] Re-run focused tests and verify pass.

### Task 4: Read-Only Data Adapter And Backtest

**Files:**
- Create: `src/lat5/data.py`
- Create: `src/lat5/backtest.py`
- Create: `src/lat5/cli.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `short/trading_data.db`, Core Watchlist markdown, date range, and strategy version.
- Produces: paper SQLite database, trades CSV, and Markdown summary.

- [ ] Write tests for Watchlist parsing, read-only loading, 5-to-60-minute aggregation, point-in-time EMA lookup, and summary metrics.
- [ ] Run `pytest tests/test_backtest.py -v` and verify missing-module failure.
- [ ] Implement adapter, chronological replay, costs, and CLI.
- [ ] Re-run focused tests and verify pass.

### Task 5: Verification And Real-Data Run

**Files:**
- Create: `reports/backtest_technical_baseline.md`
- Create: `artifacts/lat5_paper.db`
- Create: `artifacts/backtest_trades.csv`

**Interfaces:**
- Consumes: all earlier modules.
- Produces: reproducible test and backtest evidence.

- [ ] Run `pytest -q` and require zero failures.
- [ ] Run `python -m lat5.cli backtest --source-db C:\trading_system\short\trading_data.db --watchlist LAT_SIMPLE_v1.0_Watchlist.md --output-dir artifacts`.
- [ ] Record date range, universe coverage, signals, trades, win rate, PF, expectancy, MDD, and missing-data gates in the Markdown report.
- [ ] Re-run `pytest -q` after report generation and inspect artifact row counts.
