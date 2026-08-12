# Daily MA Reaction Score — Remediation 2 보고서

- 기준 HEAD: `a2dba0e5cff270ec1286a415628395c6dc742059`
- 작업일: 2026-08-13
- 범위: `remediation-final-review.md`의 MAJOR M1, M2만 수정
- 결론: **수정 및 회귀 검증 완료**

## M1. 실제 evaluator의 SSOT 100점 계약 정렬

`evaluate_watchlist_position()`에서 기존 sector/trend/volume/pullback/distance/RR 100점에
일봉 반응을 더하고 clamp하던 산식을 제거했다. 최종 점수는 아래 SSOT 구성요소만 합산한다.

| 구성요소 | 최대 점수 | 실제 evaluator 입력 |
|---|---:|---|
| 거래량·거래대금 | 30 | 기준봉 거래량, 눌림 거래량 감소, 돌파 거래량 확인을 각 10점으로 반영 |
| 60분 EMA 위치 | 20 | `m60_trend_ok` |
| 일봉 SMA 대표반응 | 20 | `evaluate_daily_ma_reaction_gate()`의 실제 component |
| 주봉 추세 | 10 | 완료 일봉을 완료 주봉으로 집계한 EMA10/EMA20 추세 |
| 정규화 기울기 | 10 | 완료 60분봉 EMA60의 직전 대비 변화율 |
| 최근 5일 양봉 수 | 5 | `daily_bull_count_5` |
| 일봉 추세 지속성 | 5 | `daily_trend_ok` |
| 합계 | 100 | clamp 없이 구성요소 합계 |

이격도, 눌림 부재, RR, 일봉 반응 UNKNOWN/SMA20 이탈/SMA5 WATCH pressure는 점수에
섞지 않고 기존 veto/state gate로 유지했다. evaluator 결과에 `score_components`를 추가해
실제 100점 배분을 직접 검증할 수 있게 했다.

완전 통과 컨텍스트의 일봉 반응별 회귀 결과:

| 대표반응 | 최종 점수 |
|---|---:|
| `NONE / 0` | 80 |
| `SMA5_HOLD / +3` | 83 |
| `SMA5_RECOVERY / +6` | 86 |
| `SMA60_UPWARD_CROSS_STRONG_BULL / +20` | 100 |

## M2. 후속 REJECT ledger의 reaction/RR 근거 보존

`_location_ledger_evidence()`가 location 판정의 state, score, veto, unknown fields,
`daily_ma_reaction`, `rr_breakdown`을 한 번만 조립한다. location-filter REJECT,
`FIVE_MINUTE_REVERSAL_MISSING_OR_INVALIDATED` REJECT, BUY/`INVALID_STOP_OR_SIZE`가 이 helper를
공유한다. 기존 location-prefixed reaction/RR 키도 같은 실제 payload의 호환 alias로 보존했다.

값이 없을 때 새 값을 추정하지 않는다. location 결과가 가진 `None` 또는 실제 payload를 그대로
ledger `inputs_json`에 전달한다.

## TDD 증거

RED:

- evaluator 회귀: `NONE`, `SMA5_HOLD`, `SMA5_RECOVERY`가 각각 기대값 80/83/86 대신 모두
  100으로 실패했다.
- ledger 회귀: 5분 반전 부재 REJECT의 `inputs_json`에서 `daily_ma_reaction`이 `KeyError`로
  실패했다.
- 컨텍스트 회귀: 완료 주봉 추세와 60분 EMA 기울기 필드가 없어 `KeyError`로 실패했다.

GREEN:

- focused remediation tests: `6 passed`
- 관련 location/context/integration 회귀: `56 passed`
- 전체 테스트: `219 passed in 1.97s`

## 변경 파일

- `src/lat5/location_decision.py`
- `src/lat5/backtest.py`
- `tests/test_location_decision.py`
- `tests/test_location_context.py`
- `tests/test_location_gate_integration.py`
- `.superpowers/sdd/daily-ma-reaction-score/remediation2-report.md`

## 검증

| 명령 | 결과 |
|---|---|
| `python -m pytest -q` | `219 passed in 1.97s` |
| `python -m compileall -q src` | exit 0 |
| `git diff --check` | clean |
| `git diff --check a2dba0e` | clean |
| 변경 파일 금지영역 검사 | 주문·브로커·알림·스케줄러 관련 파일 0건 |

## 범위 확인

- 주문 경로 변경 없음
- 알림 경로 변경 없음
- 스케줄러 변경 없음
- 임의 reaction/RR 값 생성 없음
- 리뷰의 MAJOR 2건 외 기능 추가 없음
