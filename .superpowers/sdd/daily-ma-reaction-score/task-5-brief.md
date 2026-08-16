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

