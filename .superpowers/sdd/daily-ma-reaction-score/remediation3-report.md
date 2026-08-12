# Daily MA Reaction Score Remediation 3 보고서

- 기준 HEAD: `e0e0273274bb2b6ff827672346afffa07dab0921`
- 수정 대상: `final-final-review.md`의 MAJOR M1
- 결론: `daily_ma_reaction.total_score`를 evaluator의 일봉 반응 점수 SSOT로 통일했다.

## 설계 결정

| 질문 | 결정 |
|---|---|
| 최종 일봉 반응 점수의 소유자는 누구인가? | 순수 반응 함수의 `total_score` 하나다. |
| SMA5/SMA20 종가 이탈에서 품질 보너스를 허용하는가? | 허용하지 않는다. 품질 보너스와 근거를 0/빈 값으로 반환한다. |
| `NONE`은 품질 보너스를 받을 수 있는가? | 받을 수 없다. 기존 fail-closed 동작을 회귀 테스트로 유지한다. |
| WATCH pressure와 hard veto는 어떻게 처리하는가? | 상태 의미는 그대로 유지하고 점수만 재계산하지 않는다. |

SSOT 문서도 `NONE`, `SMA5_CLOSE_BREAK`, `SMA20_CLOSE_BREAK`의 품질 보너스를 0으로
명시해 이탈 감점이 캔들 품질이나 골든크로스로 상쇄되지 않도록 정리했다.

## 원인과 수정

### 원인

`score_daily_ma_reaction()`은 모든 non-`NONE` 반응에 품질 보너스를 계산했지만,
`evaluate_daily_ma_reaction_gate()`는 전달된 `score`를 무시하고 break 상태를 다시
`-4/-8`로 만들었다. 품질이 붙는 실제 입력에서 다음 불일치를 재현했다.

| 반응 | base | 기존 quality | 기존 payload | 기존 evaluator component |
|---|---:|---:|---:|---:|
| `SMA5_CLOSE_BREAK` | -4 | +5 | 1 | -4 |
| `SMA20_CLOSE_BREAK` | -8 | +2 | -6 | -8 |

### 수정

- `src/lat5/daily_ma_reaction.py`
  - `NONE`, `SMA5_CLOSE_BREAK`, `SMA20_CLOSE_BREAK`의 품질 보너스·근거를 0/빈 값으로 제한했다.
  - break의 `total_score`는 SSOT 기본 감점인 -4/-8을 그대로 보존한다.
- `src/lat5/location_score.py`
  - SMA5/SMA20 break 분기에서 고정 -4/-8 재할당을 제거했다.
  - 전달받은 `score`를 component로 사용하면서 `DAILY_MA_WATCH_PRESSURE`와
    `DAILY_MA_HARD_BLOCK` veto는 그대로 유지했다.
- `LAT_SIMPLE_v1_0_final_spec.md`
  - break와 `NONE`의 품질 보너스 0 계약을 명시했다.

## TDD 회귀 증거

구현 전에 회귀 테스트를 추가하고 다음 실패를 확인했다.

- 집중 RED: `5 failed, 2 passed`
  - SMA5 break quality `5 != 0`
  - SMA20 break quality `2 != 0`
  - gate가 전달 score `-3/-7` 대신 `-4/-8` 재할당
  - detector→context→evaluator의 break payload/component 불일치

최소 구현 후 집중 테스트는 `10 passed`, 관련 세 모듈 전체는 `90 passed`였다.

최종 end-to-end 회귀 결과:

| 케이스 | payload score | evaluator component | 최종 상태 |
|---|---:|---:|---|
| SMA5 break | -4 | -4 | `WATCH` |
| SMA20 break | -8 | -8 | `IGNORE` |
| SMA5 recovery | 12 | 12 | `BUY_READY` |
| UNKNOWN | 0 | 0 | `IGNORE` |

## 최종 검증

| 검증 | 결과 |
|---|---|
| `python -m pytest -q` | `224 passed in 1.92s` |
| `python -m compileall -q src` | exit 0 |
| `git diff --check` | clean |
| 주문·브로커·알림·스케줄러 관련 변경 파일 | 0건 |

기존 미추적 리뷰/진행 자료는 수정하거나 커밋 범위에 포함하지 않았다.
