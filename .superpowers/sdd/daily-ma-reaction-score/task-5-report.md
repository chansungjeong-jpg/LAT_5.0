# Task 5 Report — Daily Reaction Location Context

## Scope

- Base HEAD: `3b0e573`
- Implemented only Task 5 context, decision, and backtest wiring.
- No broker order, notification, or scheduler code changed.
- No Task 6 SSOT or daily-report documentation work was performed.

## Delivered contract

- `build_context()` filters to daily rows strictly before `as_of`, then calls
  `score_daily_reaction()`.
- Context stores JSON-serializable reaction fields:
  `daily_ma_reaction_score`, `daily_ma_reaction_state`,
  `daily_ma_reaction_reasons`, and a detailed `daily_ma_reaction` mapping.
- The detailed mapping includes representative reaction, base score, quality
  bonus/reasons/components, SMA5/SMA20/SMA60, status/unknown fields, and a
  five-day state.
- Missing or malformed daily data remains fail-closed: score `0`, state
  `UNKNOWN`, with the scorer's precise unknown reason preserved.
- `evaluate_watchlist_position()` returns the same reaction detail mapping.
  The hourly pullback backtest records that mapping when the location gate
  filters a candidate.
- No standalone golden-cross score was introduced. The only golden-cross
  contribution remains the reaction scorer's embedded `+2` quality component.

## TDD evidence

1. Baseline: `python -m pytest -q` → `202 passed`.
2. RED: `python -m pytest tests/test_location_context.py tests/test_location_gate_integration.py -q`
   → `2 failed, 17 passed`; both failures were the absent
   `daily_ma_reaction_score` context key.
3. GREEN: context, gate, decision, and location-score focused tests →
   `44 passed`.

## Final verification requested

- `python -m pytest -q`
- `python -m compileall -q src`
- `git diff --check`

## Commit

Planned message: `feat: wire daily reaction into location context`
