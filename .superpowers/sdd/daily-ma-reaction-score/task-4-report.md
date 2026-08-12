# Task 4 Report — Daily MA Reaction Location-Score Integration

## Result: PASS

## Scope

- Modified: `src/lat5/location_score.py`
- Modified: `tests/test_location_score.py`
- Excluded: Task 5 context wiring

## Final 100-Point Allocation

| Component | Maximum points |
| --- | ---: |
| Volume / trading value | 30 |
| 60-minute location | 20 |
| Daily MA reaction | 20 |
| Weekly trend | 10 |
| Normalized slopes | 10 |
| Recent five-day bullish count | 5 |
| Daily trend persistence | 5 |
| Total | 100 |

## Contract Changes

- `LocationInputs` now accepts `daily_ma_reaction_score: int | None` and
  `daily_ma_reaction_state: str | None`.
- `daily_ma_reaction` is bounded to the inclusive range 0 through 20.
- A missing score, missing state, or `UNKNOWN` state contributes 0 points only;
  it does not add an unknown field or force the overall decision to `REJECT`.
- Negative reaction scores, including `SMA5_CLOSE_BREAK`, are clamped to 0 and
  are not hard vetoes. A marginal candidate can therefore be `WATCH` rather
  than rejected solely for that reaction.
- The legacy standalone `golden_cross` location component has been removed.
  `golden_cross_ok` remains an accepted input for compatibility, but has no
  independent location-score effect.

## TDD Evidence

1. Added the integration tests before the new `LocationInputs` fields existed.
2. Focused RED run failed with `TypeError: unexpected keyword argument
   'daily_ma_reaction_score'` for all 9 focused tests.
3. Added the smallest integration implementation and observed the focused suite
   pass.
4. Added an explicit `None` regression. A temporary mutation that returned 20
   for `None` made that test fail with `assert 20 == 0`; restoring fail-closed
   handling returned the focused suite to green.

## Verification

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_location_score.py -q` | 10 passed |
| `python -m pytest -q` | 202 passed |
| `python -m compileall -q src tests` | exit 0 |
| `git diff --check` | clean |
