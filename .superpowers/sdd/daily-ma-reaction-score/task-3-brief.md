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

