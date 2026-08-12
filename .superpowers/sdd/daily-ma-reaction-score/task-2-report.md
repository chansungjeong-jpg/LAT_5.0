# Task 2 Report — Representative Daily SMA Reaction Detection

## 기준

- Base HEAD: `8a393fc` (`fix: reject duplicate daily bars`)
- Scope: `src/lat5/daily_ma_reaction.py`, `tests/test_daily_ma_reaction.py`

## 변경 내용

- `score_daily_reaction()`의 기존 공개 API와 Task 1의 완료 일봉/no-lookahead/fail-closed 입력 계약을 유지했습니다.
- 대표 base reaction을 다음 우선순위로 하나만 반환하도록 구현했습니다.
  1. `SMA60_UPWARD_CROSS_STRONG_BULL` / `+10`
  2. `SMA20_PULLBACK_RECOVERY` / `+8`
  3. `SMA5_RECOVERY` / `+6`
  4. `SMA5_CLOSE_BREAK` / `-4`
  5. `NONE` / `0`
- SMA60은 전일 종가 이하에서 최신 종가가 SMA60 위로 교차하고 최신 봉이 양봉인 경우를 감지합니다.
- SMA20은 최신 저가가 SMA20에서 `0.25 ATR` 이내이고 최신 종가가 SMA20 이상인 양봉인 경우를 감지합니다.
- SMA5는 종가 전이만 사용합니다. 저가가 SMA5 아래였지만 종가가 유지된 경우는 break로 분류하지 않습니다.
- 품질 보너스, golden-cross, scorer 통합, 외부 주문/알림/스케줄러는 구현하지 않았습니다.

## TDD 검증

- 각 대표 반응 테스트를 먼저 RED로 확인한 뒤 최소 구현하고 GREEN을 확인했습니다.
- focused: `python -m pytest tests/test_daily_ma_reaction.py -q` → `31 passed`
- 전체: `python -m pytest -q` → `179 passed`
- 컴파일: `python -m compileall -q src tests` → 성공
- whitespace: `git diff --check` → clean

## 잔여 범위

Task 3 이후 범위인 ATR 기반 candle quality bonus, golden-cross bonus, location scorer/context/report 연동은 다음 Task로 남겼습니다.

## Review follow-up — MINOR boundary coverage

- Added public-API regression tests for the SMA60 previous-close equality boundary and current-close equality rejection.
- Added SMA20 pullback tests for exact `0.25 ATR` acceptance and just-outside rejection.
- Added SMA5 tests for recovery at current-close equality, break at previous-close equality, and above/below same-side maintain returning `NONE`.
- Production implementation was not changed; only `tests/test_daily_ma_reaction.py` and this report were updated.
- Focused: `python -m pytest tests/test_daily_ma_reaction.py -q` → `39 passed`
- Full suite: `python -m pytest -q` → `187 passed`
- Compile: `python -m compileall -q src tests` → success
