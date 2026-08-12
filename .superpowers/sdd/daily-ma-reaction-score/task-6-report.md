# Task 6 Report — Daily MA Reaction Contract and Verification

## Scope

- Base HEAD: `d91d69d`
- Completed only Task 6: SSOT, daily work record, verification evidence, and
  this report.
- `README.md` was reviewed and left unchanged because it already links the
  official SSOT and no new command or user-facing entry point was added.
- No production Python, broker order, notification, or scheduler code changed.

## SSOT contract finalized

- The final location-score allocation remains 100 points: volume/trading value
  30, 60-minute location 20, daily SMA reaction 20, weekly trend 10, daily
  trend persistence 5, normalized slope 10, and recent five-day bullish count
  5.
- Daily reaction reads completed daily bars only and selects one base reaction
  by priority: `SMA60_UPWARD_CROSS_STRONG_BULL` (+10),
  `SMA20_PULLBACK_RECOVERY` (+8), `SMA5_RECOVERY` (+6),
  `SMA5_CLOSE_BREAK` (-4), or `NONE` (0).
- Quality contributions are strong body +3, close near high +2, reaction-SMA
  slope +3, and SMA20/SMA60 golden cross +2. Total reaction score is capped at
  20; golden cross has no second standalone location-score component.
- SMA5 close break remains a deduction and WATCH pressure, not a Hard Block.
  A following completed-bar recovery is scored as `SMA5_RECOVERY` (+6).
- The evaluator fails closed to `UNKNOWN`/0 for missing required OHLCV, SMA,
  ATR, or invalid daily-index inputs, and never reads the `as_of` daily bar or
  a future bar.
- Distance, supply proxy, and RR retain their independent hard-block behavior.

## Reporting-field truth table

| Required field | Current source | Truthful status |
|---|---|---|
| Representative reaction, base score, quality, SMA5/20/60, 5-day state | `daily_ma_reaction` | Serialized by the location-decision payload |
| Volume score | `score_location().components["volume"]` | Available in the pure location scorer; not separately serialized by `evaluate_watchlist_position()` |
| Distance state | raw 5-minute/daily gap and vetoes | No dedicated serialized field; do not infer or invent one in reports |
| Supply / RR | `rr_breakdown`, `supply_zone_method` | Serialized only when price, stop, and target are available; current supply is a documented swing-high proxy |
| Final state | `state` | Serialized by the location-decision payload |

The generic CLI technical-baseline Markdown renderer does not receive a
location-decision payload. It therefore must not print placeholder SMA, volume,
distance, supply, or RR values.

## Verification evidence

| Command | Result |
|---|---|
| `python -m pytest tests/test_cli.py -q` | 7 passed |
| `python -m pytest tests/test_daily_ma_reaction.py tests/test_location_score.py tests/test_location_context.py tests/test_location_decision.py tests/test_location_gate_integration.py -q` | 93 passed |
| `python -m pytest -q` | 204 passed |
| `python -m compileall -q src` | exit 0 |
| `git diff --check` | clean after all Task 6 artifacts |

## Remaining warnings

1. The current runtime does not implement `SMA5_HOLD` or
   `SMA20_CLOSE_BREAK`; this report does not claim those reactions exist.
2. A future report-rendering task must explicitly wire the complete
   location-decision payload before the required fields can appear in generic
   CLI Markdown output.
3. No real Volume Profile value exists. Only `swing_high_proxy_v1` is valid
   when its source inputs are available.

## Commit

Required commit message: `docs: finalize daily ma reaction contract`
