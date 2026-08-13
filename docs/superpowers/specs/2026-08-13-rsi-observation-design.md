# RSI(14) Observation-Only Design

## Goal

Keep Wilder RSI(14) as completed-daily-bar observation data while removing all
RSI-derived score, state, reason, gate, and WATCH behavior.

## Contract

- `score_daily_reaction(daily, as_of)` computes Wilder RSI(14) only from bars
  whose date is strictly before `as_of`; current-day and future bars are not
  read.
- The public daily-reaction payload exposes `rsi14` only. A finite value is a
  number; unavailable or invalid RSI is `null` and `unknown_fields` contains
  `rsi14`.
- RSI unavailability is fail-closed for the observation value: no substitute
  value or inferred state is emitted. It does not change the independently
  calculated MA reaction, score, vetoes, `entry_eligible`, or final state.
- Daily MA reaction scoring remains `min(20, base_score + quality_bonus)`.
  The existing 100-point score allocation is unchanged.

## Boundary

`daily_ma_reaction` owns RSI calculation and serialization. Context, decision,
CLI, reports, and ledger/backtest evidence pass through only `rsi14`; they do
not interpret it. Broker orders, notifications, and scheduler configuration
are out of scope.

## Validation

Tests retain Wilder numeric calculation, completed-bar/no-lookahead behavior,
and `null`/`unknown_fields` behavior. They remove RSI recovery, divergence,
overbought, weakening, score, and WATCH-policy expectations. Full pytest,
compileall, and whitespace-diff checks are required.
