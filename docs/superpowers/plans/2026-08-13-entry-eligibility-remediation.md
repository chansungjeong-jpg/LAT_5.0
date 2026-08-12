# Entry Eligibility Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve WATCH observation states while making every backtest entry depend on an explicit fail-closed `entry_eligible` contract.

**Architecture:** `evaluate_watchlist_position()` remains the policy owner for score, state, veto, unknown-field, and entry-eligibility decisions. The backtest consumes only `entry_eligible is True`, records it in diagnostics and ledger evidence, and never reinterprets `WATCH_HIGH` as executable.

**Tech Stack:** Python 3, pytest, pandas, SQLite paper ledger.

## Global Constraints

- Preserve the official 100-point allocation `30/20/20/10/10/5/5` and all daily-reaction and RR evidence.
- Preserve `WATCH_HIGH` as an observation state but never allow it to enter.
- Fail closed on `NO_PULLBACK`, `OVERHEATED`, and missing or `UNKNOWN` weekly, 60-minute, or daily required context.
- Do not change order, notification, or scheduler code.
- Finish with full pytest, compileall, diff checks, remediation report, and commit `fix: fail closed on entry prerequisites`.

---

### Task 1: Specify evaluator entry eligibility

**Files:**
- Modify: `tests/test_location_decision.py`
- Modify: `src/lat5/location_decision.py`

**Interfaces:**
- Consumes: existing context dict and `LocationScoreConfig`.
- Produces: evaluator result key `entry_eligible: bool`, required-context unknown fields, and `ENTRY_PREREQUISITE_UNKNOWN` veto.

- [x] **Step 1: Write failing evaluator tests**

Add literal assertions showing score-70 `NO_PULLBACK` and `OVERHEATED` remain observable but are not entry eligible, and each required context field missing or `UNKNOWN` preserves its field name and veto while blocking entry.

- [x] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/test_location_decision.py -q`

Expected: failures because `entry_eligible` and the required-context veto do not exist.

- [x] **Step 3: Implement the minimum evaluator contract**

Validate `weekly_trend_ok`, `m60_trend_ok`, `m60_slope_pct`, and `daily_trend_ok`; deduplicate `unknown_fields` and `vetoes`; return `entry_eligible` only when state is `BUY_READY` and no entry veto exists.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_location_decision.py -q`

Expected: all evaluator tests pass.

### Task 2: Enforce entry eligibility in backtest and ledger

**Files:**
- Modify: `tests/test_location_gate_integration.py`
- Modify: `src/lat5/backtest.py`

**Interfaces:**
- Consumes: evaluator result `entry_eligible`.
- Produces: no trade or BUY ledger when false or absent; REJECT evidence and diagnostics preserve eligibility, vetoes, and unknown fields.

- [x] **Step 1: Write failing integration tests**

Exercise real backtest control flow for score-70 `NO_PULLBACK`, score-70 `OVERHEATED`, and missing weekly, 60-minute, and daily required contexts. Assert no trade, no BUY decision, and a location-filter REJECT containing `entry_eligible=false`.

- [x] **Step 2: Run focused tests and verify RED**

Run: `python -m pytest tests/test_location_gate_integration.py -q`

Expected: failures because `WATCH_HIGH` still enters and eligibility is not recorded.

- [x] **Step 3: Implement the minimum backtest contract**

Replace the state allow-list with `location.get("entry_eligible") is True`; add the field to location diagnostics and `_location_ledger_evidence()`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_location_gate_integration.py -q`

Expected: all integration tests pass.

### Task 3: Verify, report, and commit

**Files:**
- Create: `.superpowers/sdd/daily-ma-reaction-score/remediation4-report.md`

**Interfaces:**
- Consumes: final code, tests, and git diff.
- Produces: verification evidence and one scoped commit.

- [x] **Step 1: Run complete verification**

Run `python -m pytest -q`, `python -m compileall -q src`, `git diff --check`, and scoped diff inspections proving no order, notifier, or scheduler file changed.

- [x] **Step 2: Write the remediation report**

Record root cause, design, touched files, RED/GREEN evidence, complete verification results, and prohibited-scope confirmation.

- [x] **Step 3: Re-run final verification and commit**

Stage only remediation files and commit with `fix: fail closed on entry prerequisites`.
