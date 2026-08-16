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

