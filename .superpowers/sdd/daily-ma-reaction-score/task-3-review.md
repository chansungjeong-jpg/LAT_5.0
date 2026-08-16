# Task 3 Review — Daily MA Reaction Quality Bonuses

## 판정: MAJOR

## 검토 범위

- 비교 범위: `d5d102a..fcaa4d2` (`fcaa4d2` 단일 커밋)
- 브리프: `.superpowers/sdd/daily-ma-reaction-score/task-3-brief.md`
- 구현/회귀: `src/lat5/daily_ma_reaction.py`, `tests/test_daily_ma_reaction.py`, Task 2 final review

## 발견 사항

### MAJOR — `SMA60_UPWARD_CROSS_STRONG_BULL`이 strong-body 조건 없이 +10을 부여함

- `src/lat5/daily_ma_reaction.py:251-257`은 전일/당일 SMA60 관통과 단순 양봉만으로
  `SMA60_UPWARD_CROSS_STRONG_BULL`, 기본점수 `+10`을 선택한다.
- 새 `strong_body` 계산(`:101-106`)은 ATR14 대비 몸통 `>= 0.8`, 최근 20개 완료 몸통의
  p80 이상, 양봉을 정확히 계산하지만, `:135`의 품질 보너스에만 반영한다.
- 설계의 60일선 상향 관통 정의는 이 strong-body 조건을 필수로 둔다. 따라서 작은 양봉의
  관통도 `STRONG_BULL` +10을 받아, 이후 Task 4에서 위치점수에 연결되면 과대평가된다.
- 독립 재현: body/ATR이 0.8 미만이고 p80 미달인 데이터에서 결과는
  `reaction=SMA60_UPWARD_CROSS_STRONG_BULL`, `base_score=10`,
  `strong_body_component=0`, `total_score=17`이었다.
- 필요한 수정 방향: 60일선 `STRONG_BULL` 반응의 성립 조건에 동일한 strong-body 판정을
  포함하고, 이 경계(ATR, p80 각각 미달)를 public API 테스트로 고정한다.

## 요구사항별 확인

| 항목 | 결과 | 근거 |
|---|---|---|
| `strong_body` ATR/최근 20개 p80 | 부분 충족 | 계산과 결과 메타데이터는 있으나, strong-bull 반응의 필수조건으로 적용되지 않는다. |
| `close_near_high` | PASS | `(close-low)/(high-low) >= 0.70` 및 0.70 경계 회귀가 있다. |
| reaction slope | PASS | 선택된 SMA5/20/60의 전일 대비 상승을 +3으로 계산한다. |
| golden cross | PASS | 전일 `SMA20 <= SMA60`, 당일 `SMA20 > SMA60`의 +2 구현과 엄격한 당일 경계 테스트가 있다. |
| reaction score cap 20 | PASS | `min(20, base_score + quality_bonus)`로 상한을 강제한다. |
| no-lookahead | PASS | `as_of` 날짜보다 이른 완료 봉만 `validated`로 전달하며, 모든 신규 품질 계산은 그 프레임만 사용한다. Task 2의 미래 당일 제외 회귀도 유지된다. |
| Task 2 회귀 | PASS | Task 2의 대표 반응 우선순위, SMA 경계, 완료 봉 필터, fail-closed 검증이 focused suite에서 함께 통과했다. |

## 독립 검증

| 명령 | 결과 |
|---|---|
| `python -m pytest tests/test_daily_ma_reaction.py -q` | 47 passed (0.57s) |
| `python -m pytest -q` | 195 passed (1.79s) |
| `python -m compileall -q src tests` | exit 0 |
| `git diff --check d5d102a...fcaa4d2` | clean |

## 최종 결정

**MAJOR** — 나머지 Task 3 품질 보너스, 20점 상한, no-lookahead 및 Task 2 회귀는 확인되었지만,
`STRONG_BULL` +10의 필수 strong-body 판정이 빠져 있어 점수 계약을 충족하지 못한다.
