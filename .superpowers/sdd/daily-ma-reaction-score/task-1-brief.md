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

