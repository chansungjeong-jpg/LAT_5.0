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
