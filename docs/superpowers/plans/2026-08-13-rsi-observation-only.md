# RSI Observation Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve RSI(14) as a no-lookahead daily observation while removing all automatic RSI decisions.

**Architecture:** `daily_ma_reaction` calculates and exposes only `rsi14`; it never classifies RSI or adds it to the MA-reaction score. `location_decision`, CLI, reports, and persisted decision evidence forward the numeric/null field without interpreting it.

**Tech Stack:** Python 3.13, pandas, pytest.

## Global Constraints

- Use Wilder RSI(14) from completed daily bars strictly before `as_of`.
- Valid RSI is a finite number; invalid/unavailable RSI is `null` with `rsi14` in `unknown_fields`.
- RSI must not affect score, vetoes, `entry_eligible`, Hard Blocks, WATCH state, order paths, alerts, or scheduler configuration.
- Preserve daily-reaction 20-point cap and existing 100-point allocation.
- Do not modify or stage pre-existing untracked `.superpowers` artifacts.

---

### Task 1: Remove RSI interpretation from the domain model

**Files:**
- Modify: `src/lat5/daily_ma_reaction.py`
- Test: `tests/test_daily_ma_reaction.py`

**Interfaces:**
- Consumes: completed OHLCV `DataFrame` and `as_of` timestamp.
- Produces: `DailyMAReaction.rsi14: float | None` and existing MA reaction fields.

- [ ] **Step 1: Write the observation-contract tests**

```python
assert result.rsi14 == expected_wilder_value
assert "rsi_state" not in DailyMAReaction.__dataclass_fields__
assert result.total_score == result.base_score + result.quality_bonus
```

- [ ] **Step 2: Run the focused test module**

Run: `python -m pytest tests/test_daily_ma_reaction.py -q`
Expected: PASS after the observation-only contract is implemented.

### Task 2: Remove policy and serialization consumers

**Files:**
- Modify: `src/lat5/location_decision.py`
- Test: `tests/test_location_context.py`, `tests/test_location_decision.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `DailyMAReaction.rsi14`.
- Produces: payloads that contain only `rsi14` as RSI evidence.

- [ ] **Step 1: Write the consumer-contract tests**

```python
assert set(rsi_keys) == {"rsi14"}
assert "DAILY_MA_WATCH_PRESSURE" not in result["vetoes"]
assert result["entry_eligible"] is True
```

- [ ] **Step 2: Run focused consumer tests**

Run: `python -m pytest tests/test_location_context.py tests/test_location_decision.py tests/test_cli.py -q`
Expected: PASS after removal of RSI interpretation.

### Task 3: Align SSOT, daily worklog, and validation report

**Files:**
- Modify: `SSOT_CORE.md`, `reports/2026-08-13_daily_work.md`
- Create: `.superpowers/sdd/daily-ma-reaction-score/rsi-observation-report.md`

**Interfaces:**
- Consumes: approved observation-only contract.
- Produces: repository documentation and an uncommitted requested report with the same contract.

- [ ] **Step 1: Replace RSI scoring/policy prose**

```markdown
Wilder RSI(14)는 관찰용 수치다. RSI 기반 자동판정, 가점/감점, gate, WATCH 정책은 없다.
```

- [ ] **Step 2: Verify no retired public field name remains in updated docs**

Run: `rg -n "rsi_state|rsi_bonus|rsi_reasons|RSI_OVERBOUGHT|RSI_WEAKENING" SSOT_CORE.md reports/2026-08-13_daily_work.md`
Expected: no matches.

### Task 4: Verify and commit the scoped change

**Files:**
- Verify: affected source, tests, SSOT, report, and Git index.

- [ ] **Step 1: Run all tests and compilation**

Run: `python -m pytest -q` and `python -m compileall -q src`
Expected: all tests pass and compileall exits 0.

- [ ] **Step 2: Check whitespace and staged scope**

Run: `git diff --check f8e9c52..HEAD` and `git diff --cached --check`
Expected: clean; pre-existing `.superpowers` files remain unstaged.

- [ ] **Step 3: Commit tracked implementation artifacts**

```bash
git add src/lat5/daily_ma_reaction.py src/lat5/location_decision.py tests SSOT_CORE.md reports/2026-08-13_daily_work.md docs/superpowers/specs/2026-08-13-rsi-observation-design.md docs/superpowers/plans/2026-08-13-rsi-observation-only.md
git commit -m "refactor: keep rsi as observation only"
```
