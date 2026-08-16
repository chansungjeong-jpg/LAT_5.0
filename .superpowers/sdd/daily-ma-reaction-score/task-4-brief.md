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

