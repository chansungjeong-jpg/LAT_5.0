# RSI Confirmation Report

## Scope

- Repository: `C:\trading_system\LAT_5.0`
- Branch: `agent/daily-ma-reaction-score`
- Implementation commit: `f8e9c52 feat: add rsi confirmation to daily reaction`
- Design/plan commit: `dd5838c docs: define rsi reaction confirmation`

## Delivered contract

- `daily_ma_reaction` now calculates Wilder RSI(14) only from completed daily bars before `as_of`.
- Serialized evidence: `rsi14`, `rsi_state`, `rsi_bonus`, `rsi_reasons`.
- Recovery: <30 to >=30 gives +3; <40 to >=40 gives +2; the stronger +3 wins when both apply.
- Bullish divergence compares the latest completed 5-bar low/RSI-low window with the preceding completed 5-bar window and adds +2.
- `OVERBOUGHT` at RSI >=70 earns no bonus and applies existing `DAILY_MA_WATCH_PRESSURE`; it is not a Hard Block.
- RSI <50 and below the prior completed RSI is `WEAKENING_BELOW_50` with 0 bonus.
- RSI insufficiency or invalid close data preserves fail-closed `UNKNOWN` and includes `rsi14` in `unknown_fields`.
- Reaction total remains capped at 20. The 100-point allocation and volume's 30-point maximum are unchanged.

## Evidence paths

- `build_context()` serializes the fields into `daily_ma_reaction`.
- `evaluate_watchlist_position()` retains existing entry-eligibility and Hard Block behavior while adding only overbought WATCH pressure.
- CLI Markdown, backtest diagnostics, and ledger evidence already relay the full decision payload; CLI regression asserts the RSI fields.

## Verification

| Command | Result |
|---|---|
| `python -m pytest tests/test_daily_ma_reaction.py tests/test_location_context.py tests/test_location_decision.py tests/test_cli.py tests/test_location_gate_integration.py -q` | 134 passed |
| `python -m pytest -q` | 250 passed |
| `python -m compileall -q src` | exit 0 |
| `git diff --check` | clean |

## Boundaries

No broker orders, alerts, notification sends, or scheduler behavior were changed or executed.
