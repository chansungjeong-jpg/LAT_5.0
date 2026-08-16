# RSI Observation-Only Refactor Report

## Contract

- Wilder RSI(14)는 `as_of` 이전 완료 일봉만 사용한다.
- 정상 시 공개 payload는 숫자 `rsi14`만 제공한다.
- 계산 불가 시 `rsi14=null`이며 `unknown_fields`에 `rsi14`를 남긴다.
- RSI는 점수, Hard Block, gate, `entry_eligible`, WATCH 판정에 사용하지 않는다.

## Changes

- `DailyMAReaction`에서 `rsi_state`, `rsi_bonus`, `rsi_reasons` 및 recovery,
  divergence, overbought, weakening 판정 코드를 제거했다.
- daily reaction 점수는 `min(20, base_score + quality_bonus)`로 복원했다.
- context/decision/CLI/backtest evidence는 `rsi14`만 전달하며, RSI UNKNOWN은
  daily-MA gate로 전달하지 않는다.
- SSOT와 일일업무보고서를 관찰 전용 계약으로 갱신했다.

## Verification

| Check | Result |
|---|---|
| `python -m pytest tests/test_daily_ma_reaction.py tests/test_location_context.py tests/test_location_decision.py tests/test_cli.py -q` | 120 passed |
| `python -m pytest -q` | 248 passed |
| `python -m compileall -q src` | exit 0 |
| `git diff --check f8e9c52` | clean |

## Scope

No broker order, notification, or scheduler code was changed. This report is
intentionally untracked and excluded from the requested commit, along with the
pre-existing `.superpowers` artifacts.
