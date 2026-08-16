# Task 2 Review — Representative Daily SMA Reaction Detection

## 결론

**APPROVE WITH MINOR.** BLOCKER와 MAJOR는 없으며, `8a393fc..001563a`의 코드 변경은 Task 2 계약과 일치한다. 대표 반응은 우선순위대로 정확히 하나만 반환하고, Task 1의 completed-bar / no-lookahead / fail-closed 입력 계약도 회귀하지 않았다.

## 검토 범위와 증거

- 비교 범위: `8a393fc (fix: reject duplicate daily bars)` → `001563a (feat: detect representative daily ma reactions)`
- diff 파일: `.superpowers/sdd/daily-ma-reaction-score/review-8a393fc..001563a.diff`
- 커밋 변경 파일은 `src/lat5/daily_ma_reaction.py`, `tests/test_daily_ma_reaction.py`, Task 2 보고서뿐이다. location scorer/context, 주문, 알림, scheduler, Task 3 quality/golden-cross 변경은 없다.

| 확인 항목 | 판정 | 근거 |
|---|---|---|
| 대표 반응 우선순위·점수 | PASS | 구현 순서가 SMA60 strong bull `+10` → SMA20 pullback recovery `+8` → SMA5 recovery `+6` → SMA5 close break `-4` → `NONE 0`이며 각 분기는 즉시 `return`한다 (`daily_ma_reaction.py:173-253`). 따라서 base points가 누적되지 않는다. |
| SMA60 cross 경계 | PASS | 전일 `close <= SMA60`, 당일 `close > SMA60`, 당일 `close > open`을 모두 요구한다 (`173-177`). 전일 SMA60 동일값은 교차 전 상태로 허용하고, 당일 SMA60 동일값/도지는 strong-bull로 과대 분류하지 않는다. |
| SMA20 pullback recovery 경계 | PASS | 당일 저가가 SMA20과 `0.25 * ATR14` 이내이고, 종가 `>= SMA20` 및 양봉이어야 한다 (`191-199`). 거리 한계는 `<=`로 포함되고, ATR이 없거나 0이면 해당 positive reaction으로 분류하지 않는다. |
| SMA5 recovery / maintain / break | PASS | recovery는 `previous_close < previous_SMA5` 및 `current_close >= current_SMA5`, break는 `previous_close >= previous_SMA5` 및 `current_close < current_SMA5`다 (`213-241`). 같은 편에서 유지되면 `NONE`; 저가만 5일선 아래이고 종가가 유지되면 break가 아니다. |
| low-only 5일선 이탈 | PASS | break 판정에는 `low`를 사용하지 않고 종가 전이만 사용한다. 제공 테스트와 별도 경계 실행 모두 `NONE / 0`을 반환했다. |
| completed-bar / no-lookahead | PASS | 입력은 `index.normalize() < as_of.normalize()`인 일봉만 잘라 검증·SMA·ATR·반응 계산에 사용한다 (`79-98`, `130-170`). 진행 중/미래 일봉은 반응에도 유입되지 않는다. |
| Task 1 contract 회귀 | PASS | required OHLCV, 비유한값, index/일자 중복, 부족 SMA는 detection 전에 기존 `UNKNOWN` fail-closed 경로로 반환한다 (`121-164`). public alias와 dataclass도 유지된다. |

## 독립 검증

| 명령 | 결과 |
|---|---|
| `python -m pytest tests/test_daily_ma_reaction.py -q` | `31 passed in 0.50s` |
| `python -m pytest -q` | `179 passed in 1.67s` |

추가로 공개 API를 사용하는 read-only 인라인 경계 실행에서 다음을 확인했다.

- 5일선 `동일 -> 하향`: `SMA5_CLOSE_BREAK / -4`
- 5일선 `하향 -> 동일`: `SMA5_RECOVERY / +6` (상위 반응이 없도록 구성)
- 5일선 상단 유지: `NONE / 0`
- 저가만 5일선 하회, 종가 유지: `NONE / 0`
- 60일선 상향 교차 양봉: `SMA60_UPWARD_CROSS_STRONG_BULL / +10`

## Findings

### BLOCKER

없음.

### MAJOR

없음.

### MINOR

1. **경계 조건의 자동 회귀 테스트가 부족하다.** `tests/test_daily_ma_reaction.py:37-126`은 각 대표 반응의 일반 사례와 low-only 사례를 확인하지만, 다음 계약 경계를 명시적으로 고정하지 않는다: SMA60의 전일/당일 SMA 동일값, SMA20의 정확히 `0.25 ATR` 거리, SMA5의 `previous == SMA5 -> below`, `previous < SMA5 -> current == SMA5`, 그리고 same-side maintain. 현재 구현은 이 조건을 의도대로 처리하며 위 read-only 실행으로도 확인했으므로 배포 차단 사유는 아니다. 다만 이후 threshold 또는 비교연산자 변경 시 전략 점수가 조용히 바뀌지 않도록 다음 Task에서 테스트로 고정해야 한다.

## 최종 판정

Task 2는 범위를 벗어난 변경 없이 representative base reaction detector를 구현했다. MINOR 테스트 보강을 후속으로 남기고 승인 가능하다.
