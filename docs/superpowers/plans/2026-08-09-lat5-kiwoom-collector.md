# LAT 5.0 Kiwoom Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect all 154 Core Watchlist symbols through four read-only Kiwoom REST APIs into a provider-aware LAT SQLite database without modifying `short` state.

**Architecture:** A non-refreshing token provider feeds a rate-limited HTTP client. API parsers and an idempotent LAT store remain independent, while an orchestrator records every run, raw page, parsed row, and failure before producing a data-health report.

**Tech Stack:** Python 3.13, requests, SQLite, pandas, pytest 9.

## Global Constraints

- Read `C:\trading_system\short\kiwoom_token_cache.json`; never write it.
- Never call `/oauth2/token`, account APIs, or order APIs.
- Write only under `C:\trading_system\LAT_5.0`.
- Preserve raw API pages before parsing.
- Missing or mismatched fields remain unknown; never insert fabricated zero rows.
- Stop the entire run on token errors; continue other APIs on non-token parser errors.

---

### Task 1: Read-Only Token Provider

**Files:**
- Create: `src/lat5/token_provider.py`
- Test: `tests/test_token_provider.py`

**Interfaces:**
- Produces: `TokenSnapshot(token: str, cached_at: datetime, source: Path)` and `read_shared_token(path, max_age_hours=12, now=None)`.
- Raises: `TokenMissing`, `TokenStale`, or `TokenInvalid` without mutating the cache.

- [x] Write tests that hash the cache before and after a successful read, reject missing token keys, and reject a 12-hour-old timestamp.
- [x] Run `pytest tests/test_token_provider.py -v`; verify failure because `lat5.token_provider` is absent.
- [x] Implement JSON validation, timezone-safe age calculation, and typed exceptions.
- [x] Re-run the focused test and require all cases to pass.

### Task 2: Kiwoom HTTP Client

**Files:**
- Create: `src/lat5/kiwoom_client.py`
- Test: `tests/test_kiwoom_client.py`

**Interfaces:**
- Consumes: `TokenSnapshot`, injected `requests.Session`, delay, and maximum pages.
- Produces: `ApiPage(api_id, page_no, payload, cont_yn, next_key)` from `post_pages(api_id, path, body)`.
- Raises: `KiwoomTokenError` on 8005 and `KiwoomApiError` on other business errors.

- [x] Test Bearer/api-id headers, continuation header propagation, maximum-page enforcement, 429 retry, and no retry on 8005 with fake sessions.
- [x] Run `pytest tests/test_kiwoom_client.py -v`; verify the missing-module failure.
- [x] Implement the client with a 0.35-second minimum interval and at most three network/429/5xx attempts.
- [x] Re-run the focused test and require all cases to pass.

### Task 3: Provider-Aware Collector Store

**Files:**
- Create: `src/lat5/collector_store.py`
- Test: `tests/test_collector_store.py`

**Interfaces:**
- Produces: `CollectorStore(path)` with run lifecycle, raw-page, parsed-row, error, and coverage methods.
- Tables: `collection_runs`, `collection_errors`, `raw_api_responses`, `ohlcv_daily`, `ohlcv_minute`, `execution_strength`, `investor_flow`.

- [x] Test schema keys include provider, raw pages append, parsed rows upsert idempotently, and run states transition from RUNNING to COMPLETE/PARTIAL/BLOCKED.
- [x] Run `pytest tests/test_collector_store.py -v`; verify the missing-module failure.
- [x] Implement parameterized SQL and transaction-scoped writes.
- [x] Re-run the focused test and require all cases to pass.

### Task 4: API Parsers And Symbol Collection

**Files:**
- Create: `src/lat5/collector.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Produces: `parse_daily`, `parse_minutes`, `parse_strength`, `parse_foreign_flow`, `collect_symbol`, and `collect_watchlist`.
- Request contracts: `ka10081 /api/dostk/chart`, `ka10080 /api/dostk/chart`, `ka10046 /api/dostk/mrkcond`, `ka10059 /api/dostk/stkinfo`.

- [x] Test parsers with redacted response fixtures, including signed/comma numbers and a `ka10046` schema mismatch.
- [x] Test one-symbol orchestration writes raw pages before parsed rows and records non-token errors while continuing remaining APIs.
- [x] Run `pytest tests/test_collector.py -v`; verify the missing-module failure.
- [x] Implement exact request bodies and fail-closed parsers; keep the execution-strength key contract explicit.
- [x] Re-run the focused test and require all cases to pass.

### Task 5: Data Health And CLI

**Files:**
- Create: `src/lat5/data_health.py`
- Modify: `src/lat5/cli.py`
- Test: `tests/test_collector_cli.py`

**Interfaces:**
- Produces commands `lat5 collect`, `lat5 collect --probe`, and `lat5 data-health`.
- Produces: `reports/data_health_latest.md` and `artifacts/data_health_latest.json`.

- [x] Test CLI argument parsing, probe limiting to `005930`, all-symbol deduplication, report thresholds, and BLOCKED exit codes.
- [x] Run `pytest tests/test_collector_cli.py -v`; verify missing command behavior.
- [x] Implement CLI wiring and deterministic Markdown/JSON health reports.
- [x] Re-run the focused test and require all cases to pass.

### Task 6: Verification And Live Read-Only Collection

**Files:**
- Create: `data/lat5_market.db` through the collector.
- Create: `reports/data_health_latest.md` through the health command.

**Interfaces:**
- Consumes: approved shared token cache and Core Watchlist.
- Produces: read-only market-data evidence; never orders.

- [x] Record SHA-256, size, and modified time for the `short` token cache and `short/trading_data.db`.
- [x] Run `pytest -q` and `python -m compileall -q src`; require zero failures.
- [x] Run a `005930` probe for all four APIs and inspect raw response keys, status, and LAT DB rows. Result: `BLOCKED` at `ka10081` with 8005 before any raw page.
- [x] Recheck the two `short` files; require identical hashes, sizes, and modified times.
- [ ] If the probe is not BLOCKED, run all 154 symbols and generate data health. Blocked by the approved no-refresh rule after Kiwoom returned 8005.
- [x] Re-run the existing technical baseline against eligible LAT OHLCV data only when its schema coverage is sufficient; otherwise leave the prior backtest intact and report the exact gate. LAT coverage is 0%, so the prior 154-symbol technical baseline remains authoritative.
