# Daily Moving-Average Reaction Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a completed-daily-bar SMA5/SMA20/SMA60 reaction score that identifies actionable entry locations while preserving volume priority and existing hard blocks.

**Architecture:** Keep detection pure and separate from orchestration. A new reaction module will calculate SMA values, ATR-normalized reactions, candle quality, golden-cross confirmation, and the representative reaction score. The existing location scorer will consume the result as a bounded 20-point component; existing distance, supply, and RR vetoes remain independent.

**Tech Stack:** Python 3.13, pandas, pytest, existing `lat5.data`, `lat5.location_score`, `lat5.location_decision`, and `lat5.backtest` modules.

## Global Constraints

- Use completed daily bars only; no lookahead from the current or future bar.
- Use simple moving averages SMA5, SMA20, and SMA60.
- Select one representative reaction; do not stack mutually exclusive base-reaction points.
- Reaction score is bounded to 20 points.
- Volume/trading value remains the largest existing score component at 30 points.
- Distance, overhead supply, missing required data, and RR below 1.5 remain Hard Blocks.
- A daily close below SMA5 is a -4 deduction and WATCH pressure, not an automatic rejection.
- A following-day SMA5 recovery is a +6 recovery reaction and is re-evaluated.
- Golden cross is a +2 quality bonus, not a standalone buy condition.
- Do not connect external notifications, broker orders, or schedulers.
- Existing ABC code remains legacy/comparison code until a separate approved removal.
- Every implementation task follows RED → verify failure → GREEN → verify pass.

---

### Task 1: Define the pure daily reaction data contract

**Files:**
- Create: `src/lat5/daily_ma_reaction.py`
- Test: `tests/test_daily_ma_reaction.py`

**Interfaces:**
- `DailyMAReactionInputs`: completed OHLCV daily frame and evaluation position.
- `DailyMAReaction`: representative reaction name, base score, quality bonus, total score, SMA values, status, reasons, and unknown fields.
- `score_daily_ma_reaction(daily: pd.DataFrame, as_of: pd.Timestamp) -> DailyMAReaction`.

- [ ] **Step 1: Write failing tests for required data and SMA calculation.**

```python
def test_reaction_requires_at_least_sixty_completed_daily_bars():
    short_frame = frame_with_bars(20)
    result = score_daily_reaction(short_frame, as_of=short_frame.index[-1])
    assert result.status == "UNKNOWN"
    assert "SMA60" in result.unknown_fields

def test_sma_values_use_only_rows_before_as_of():
    result = score_daily_reaction(frame, as_of=pd.Timestamp("2026-08-12"))
    assert result.sma5 == pytest.approx(frame.loc[:"2026-08-12", "close"].tail(5).mean())
```

- [ ] **Step 2: Run the focused tests and verify they fail because the module and function do not exist.**

Run: `python -m pytest tests/test_daily_ma_reaction.py -q`

- [ ] **Step 3: Implement the dataclasses, completed-bar filtering, and SMA5/SMA20/SMA60 calculation.**

Use `daily.loc[daily.index <= as_of]`, require `open/high/low/close/volume`, and return `UNKNOWN` with field names when SMA or ATR prerequisites are unavailable.

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run: `python -m pytest tests/test_daily_ma_reaction.py -q`

- [ ] **Step 5: Commit the isolated contract.**

```text
feat: add daily moving average reaction contract
```

### Task 2: Implement representative SMA reaction detection

**Files:**
- Modify: `src/lat5/daily_ma_reaction.py`
- Test: `tests/test_daily_ma_reaction.py`

**Interfaces:** `score_daily_reaction()` returns exactly one base reaction from the following priority order.

- [ ] **Step 1: Write failing tests for each reaction.**

```python
def test_sixty_sma_upward_cross_with_strong_bullish_bar_scores_ten():
    result = score_daily_reaction(sixty_cross_fixture(), as_of=last_day)
    assert result.reaction == "SMA60_UPWARD_CROSS_STRONG_BULL"
    assert result.base_score == 10

def test_twenty_sma_pullback_recovery_scores_eight():
    result = score_daily_reaction(twenty_pullback_fixture(), as_of=last_day)
    assert result.reaction == "SMA20_PULLBACK_RECOVERY"
    assert result.base_score == 8

def test_five_sma_break_then_next_day_recovery_scores_six():
    result = score_daily_reaction(five_recovery_fixture(), as_of=last_day)
    assert result.reaction == "SMA5_RECOVERY"
    assert result.base_score == 6

def test_five_sma_close_break_is_deduction_not_unknown_or_hard_reject():
    result = score_daily_reaction(five_break_fixture(), as_of=last_day)
    assert result.reaction == "SMA5_CLOSE_BREAK"
    assert result.base_score == -4

def test_multiple_reactions_use_only_highest_priority_reaction():
    result = score_daily_reaction(overlapping_fixture(), as_of=last_day)
    assert result.base_score == 10
```

- [ ] **Step 2: Run the tests and verify the expected reaction fields fail.**

Run: `python -m pytest tests/test_daily_ma_reaction.py -q`

- [ ] **Step 3: Implement the detection rules.**

Use close-to-SMA crossing for SMA60, low-to-SMA proximity plus bullish close for SMA20, and close-to-SMA5 transitions for SMA5. Use close-based breaks; an intraday low below SMA5 alone is not a break.

- [ ] **Step 4: Run the focused tests and verify all reaction tests pass.**

Run: `python -m pytest tests/test_daily_ma_reaction.py -q`

- [ ] **Step 5: Commit the reaction detector.**

```text
feat: detect daily moving average reactions
```

### Task 3: Add normalized candle quality and golden-cross bonus

**Files:**
- Modify: `src/lat5/daily_ma_reaction.py`
- Modify: `tests/test_daily_ma_reaction.py`

**Interfaces:** Quality bonuses are `strong_body`, `close_near_high`, `reaction_slope_up`, and `golden_cross`; total reaction score is capped at 20.

- [ ] **Step 1: Write failing tests.**

```python
def test_strong_body_uses_atr_and_recent_body_percentile():
    result = score_daily_reaction(strong_body_fixture(), as_of=last_day)
    assert "STRONG_BODY" in result.quality_reasons
    assert result.quality_bonus >= 3

def test_close_near_high_adds_two_points():
    result = score_daily_reaction(close_near_high_fixture(), as_of=last_day)
    assert "CLOSE_NEAR_HIGH" in result.quality_reasons

def test_sma20_crosses_above_sma60_adds_two_point_golden_cross_bonus():
    result = score_daily_reaction(golden_cross_fixture(), as_of=last_day)
    assert result.quality_components["golden_cross"] == 2

def test_reaction_total_is_capped_at_twenty():
    result = score_daily_reaction(all_quality_conditions_fixture(), as_of=last_day)
    assert result.total_score <= 20
```

- [ ] **Step 2: Run tests and verify they fail.**

Run: `python -m pytest tests/test_daily_ma_reaction.py -q`

- [ ] **Step 3: Implement ATR-normalized body strength, close position, SMA slope, and SMA20/SMA60 golden-cross detection.**

Use `close_position = (close-low)/(high-low)` and classify close-near-high at `>= 0.70`. Use the most recent 20 completed bodies for relative strength and store the method in the result.

- [ ] **Step 4: Run tests and verify they pass.**

Run: `python -m pytest tests/test_daily_ma_reaction.py -q`

- [ ] **Step 5: Commit quality scoring.**

```text
feat: add normalized candle and golden cross quality bonuses
```

### Task 4: Integrate the reaction score into the location scorer

**Files:**
- Modify: `src/lat5/location_score.py`
- Modify: `tests/test_location_score.py`

**Interfaces:** Add `daily_ma_reaction_score: int | None` and `daily_ma_reaction_state: str | None` to `LocationInputs`; expose a `daily_ma_reaction` component capped at 20.

The final 100-point allocation in this task is: volume/trading value 30, 60-minute location 20, daily reaction 20, weekly trend 10, normalized slopes 10, recent five-day bullish count 5, and daily trend persistence 5. Reduce the existing 60-minute and weekly components to 20 and 10 respectively; do not add points on top of the old 100-point total.

- [ ] **Step 1: Write failing integration tests.**

```python
def test_daily_ma_reaction_is_a_twenty_point_component():
    result = score_location(_strong_inputs(daily_ma_reaction_score=20))
    assert result.components["daily_ma_reaction"] == 20

def test_daily_ma_reaction_does_not_exceed_total_component_cap():
    result = score_location(_strong_inputs(daily_ma_reaction_score=99))
    assert result.components["daily_ma_reaction"] == 20

def test_sma5_break_can_make_watch_but_is_not_hard_reject_by_itself():
    result = score_location(_strong_inputs(daily_ma_reaction_score=-4, daily_ma_reaction_state="SMA5_CLOSE_BREAK"))
    assert "DAILY_MA_HARD_BLOCK" not in result.vetoes
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `python -m pytest tests/test_location_score.py -q`

- [ ] **Step 3: Implement bounded component integration.**

Preserve volume at 30 points, keep existing market/sector/leader/trend/RR/distance vetoes, and do not turn SMA5 break into a hard veto.

- [ ] **Step 4: Run focused and full tests.**

Run: `python -m pytest tests/test_location_score.py -q` then `python -m pytest -q`

- [ ] **Step 5: Commit integration.**

```text
feat: integrate daily moving average reaction score
```

### Task 5: Connect daily data context and remove duplicate golden-cross scoring

**Files:**
- Modify: `src/lat5/location_decision.py`
- Modify: `src/lat5/backtest.py`
- Modify: `tests/test_location_context.py`
- Modify: `tests/test_location_gate_integration.py`
- Modify: `tests/test_location_decision.py`

**Interfaces:** `build_context()` adds the daily reaction result and `evaluate_watchlist_position()` consumes it without adding a second standalone golden-cross component.

- [ ] **Step 1: Write failing context tests.**

```python
def test_build_context_contains_daily_ma_reaction_fields():
    ctx = build_context(
        daily=daily,
        daily_ema=daily_ema_context(daily),
        hourly=hourly,
        minutes=minutes,
        as_of=as_of,
        cfg=LocationScoreConfig(),
    )
    assert "daily_ma_reaction_score" in ctx
    assert "daily_ma_reaction_state" in ctx
    assert "daily_ma_reaction_reasons" in ctx
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `python -m pytest tests/test_location_context.py tests/test_location_gate_integration.py -q`

- [ ] **Step 3: Call `score_daily_reaction()` from `build_context()` with only daily rows before `as_of`.**

Copy only serializable result fields into context. Replace the current standalone `golden_cross_ok +3` path with the reaction result's embedded `+2` quality bonus.

- [ ] **Step 4: Update decision output and run tests.**

Expose representative reaction, base score, quality reasons, SMA values, and 5-day state in the decision details. Run `python -m pytest -q`.

- [ ] **Step 5: Commit context integration.**

```text
feat: connect daily moving average reaction to location context
```

### Task 6: Update SSOT, report fields, and verification artifacts

**Files:**
- Modify: `LAT_SIMPLE_v1_0_final_spec.md`
- Modify: `README.md` if the strategy contract summary requires it
- Modify: `reports/2026-08-13_daily_work.md`
- Test: existing CLI/report tests plus full suite

- [ ] **Step 1: Add the final score table and hard-block rules to SSOT.**

Document SMA5/SMA20/SMA60, representative reaction priority, 20-point cap, golden-cross +2 quality bonus, SMA5 deduction/recovery behavior, and no-lookahead requirements.

- [ ] **Step 2: Add report fields for the reaction breakdown.**

The report must show representative reaction, score, quality bonuses, SMA values, 5-day state, volume score, distance state, supply/RR breakdown, and final state.

- [ ] **Step 3: Run all verification commands.**

```text
python -m pytest -q
python -m compileall -q src
```

Expected: all tests pass and compilation succeeds.

- [ ] **Step 4: Record implementation status and remaining warnings in the daily work report.**

- [ ] **Step 5: Commit the documentation and verification artifacts.**

```text
docs: finalize daily moving average reaction score contract
```

## Verification Summary

The complete change is accepted only when the following are separately true:

1. Unit tests prove each SMA reaction and quality bonus.
2. Integration tests prove the score is capped at 20 and volume remains the largest component.
3. Context tests prove only completed daily bars are used.
4. Hard-block tests prove distance, supply, missing data, and RR behavior is unchanged.
5. Full pytest and compileall pass.
6. External notifications, broker orders, and scheduler state remain untouched.
