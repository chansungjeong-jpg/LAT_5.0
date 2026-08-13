# RSI Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Wilder RSI(14) confirmation to the completed-daily-bar reaction quality without changing the 100-point location-score allocation.

**Architecture:** `daily_ma_reaction` remains the single calculation and serialization owner. `location_decision` only turns the serialized overbought state into the existing WATCH-pressure policy, while CLI and backtest continue to render/pass through the same decision evidence.

**Tech Stack:** Python 3, pandas, pytest.

## Global Constraints

- Use only completed daily bars strictly before `as_of`; fail closed on insufficient/invalid RSI.
- Cap `daily_ma_reaction` at 20 and preserve volume's 30-point maximum.
- Do not alter orders, notifications, or scheduler code.
- Do not stage existing untracked `.superpowers` artifacts; create only the requested RSI report there.

---

### Task 1: RSI reaction contract

**Files:** Modify `src/lat5/daily_ma_reaction.py`; test `tests/test_daily_ma_reaction.py`.

- [ ] Write one failing public-score test per behavior: oversold recovery priority, divergence, overbought, weakening, UNKNOWN, and no-lookahead.
- [ ] Implement Wilder RSI, safe state/bonus calculation, and 20-point quality cap.
- [ ] Run the focused test module after each RED→GREEN slice.

### Task 2: Context and policy propagation

**Files:** Modify `src/lat5/location_decision.py`; test `tests/test_location_context.py` and `tests/test_location_decision.py`.

- [ ] Add a failing context serialization test for four RSI fields.
- [ ] Add a failing evaluator test proving overbought forces WATCH without becoming a Hard Block or changing entry eligibility rules.
- [ ] Add only the serializer and policy bridge required for the tests, then run focused tests.

### Task 3: Report and documentation evidence

**Files:** Modify `tests/test_cli.py`, `LAT_SIMPLE_v1_0_final_spec.md`, `reports/2026-08-13_daily_work.md`; create `.superpowers/sdd/daily-ma-reaction-score/rsi-report.md`.

- [ ] Add a failing CLI report test for serialized RSI evidence.
- [ ] Keep the report as a direct rendering of supplied decision payload, then pass the test.
- [ ] Update the SSOT and daily work report with the finalized contract and fresh verification evidence.

### Task 4: Final verification and commits

- [ ] Run `python -m pytest -q`, `python -m compileall -q src`, and `git diff --check`.
- [ ] Inspect staged paths to exclude pre-existing untracked `.superpowers` artifacts and leave the requested `rsi-report.md` uncommitted.
- [ ] Commit the documentation/design checkpoint first, then commit implementation with the exact final message `feat: add rsi confirmation to daily reaction`.
