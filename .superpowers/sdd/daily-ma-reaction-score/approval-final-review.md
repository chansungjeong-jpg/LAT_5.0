# Daily MA Reaction Score — 최종 승인 재리뷰

- 저장소: `C:\trading_system\LAT_5.0`
- 기준선: `8e6f47ad4a3cad366233bde04e29b0c96970c96c`
- 검토 HEAD: `89c1af7e07010e8ac0668d37043566d3b329b11b`
- 이전 승인 리뷰 HEAD: `3714acf1e4f673f82f21ad98a2925f02951f80ef`
- 검토일: 2026-08-13
- 최종 판정: **PASS**
- 심각도: **BLOCKER 0 / MAJOR 0 / MINOR 0**

## 결론

이전 `approval-review.md`의 BLOCKER 2건은 모두 해결됐다.

평가기 결과에 `entry_eligible`이 명시됐고, `WATCH_HIGH`는 관찰 상태로 유지되지만
백테스트 진입 상태로 해석되지 않는다. 백테스트는 이제 상태 allow-list 대신
`location.get("entry_eligible") is True`인 경우만 진입 경로로 전달한다. 따라서
70점 `WATCH_HIGH`의 `NO_PULLBACK` 및 `OVERHEATED`는 실제 trade와 BUY ledger를 만들지
않는다.

또한 `weekly_trend_ok`, `m60_trend_ok`, `m60_slope_pct`, `daily_trend_ok`의 누락,
`None`, `UNKNOWN`은 필드명을 `unknown_fields`에 보존하고
`ENTRY_PREREQUISITE_UNKNOWN` veto와 `entry_eligible=false`로 fail-closed된다.
필드가 없는 레거시·불완전 evaluator payload도 백테스트에서 통과하지 못한다.

반응 점수 SSOT, 100점 배분, 반응 상태/품질, 기존 Hard Block, ledger evidence,
CLI/report payload 및 주문·알림·스케줄러 불변성에서도 승인 차단 문제를 발견하지 못했다.

## 이전 BLOCKER 재검증

### B1. `WATCH_HIGH`의 `NO_PULLBACK`/`OVERHEATED` 진입 우회 — **RESOLVED**

- evaluator는 `NO_PULLBACK`과 `OVERHEATED`를 veto로 유지하고 최종
  `entry_eligible = state == "BUY_READY" and not vetoes`로 계산한다
  (`src/lat5/location_decision.py:351-370`, `:427-456`).
- 백테스트는 `WATCH_HIGH`를 포함한 상태 allow-list를 제거하고
  `entry_eligible is True`만 통과시킨다(`src/lat5/backtest.py:912-927`).
- score 70 `NO_PULLBACK`/`OVERHEATED` evaluator 테스트는 상태가
  `WATCH_HIGH`여도 `entry_eligible=false`임을 확인한다
  (`tests/test_location_decision.py:312-331`).
- 실제 runner 통합 테스트는 두 경우 모두 trade 0건, BUY decision 0건,
  `LOCATION_FILTERED` REJECT 및 `location_entry_eligible=false`를 확인한다
  (`tests/test_location_gate_integration.py:316-434`).

### B2. 필수 weekly/m60/daily 컨텍스트 누락의 fail-open — **RESOLVED**

- 필수 필드는 `weekly_trend_ok`, `m60_trend_ok`, `m60_slope_pct`,
  `daily_trend_ok`로 한 곳에 선언됐다(`src/lat5/location_decision.py:14-25`).
- 누락, `None`, 대소문자·공백을 정규화한 `UNKNOWN`은
  `unknown_fields`와 `ENTRY_PREREQUISITE_UNKNOWN`에 보존된다
  (`src/lat5/location_decision.py:308-315`).
- evaluator 단위 테스트는 네 필드 각각의 missing/`UNKNOWN` 8개 조합이 모두
  `entry_eligible=false`인지 검증한다(`tests/test_location_decision.py:381-408`).
- runner 통합 테스트는 각 필드 누락이 trade 및 BUY ledger를 만들지 않고
  REJECT evidence에 veto와 원인 필드를 남기는지 검증한다
  (`tests/test_location_gate_integration.py:316-434`).

## 기준별 판정

| 검토 기준 | 판정 | 근거 |
|---|---|---|
| `entry_eligible` 명시 및 fail-closed 소비 | **PASS** | evaluator의 모든 반환 경로가 불리언을 제공하고, runner는 명시적 `True`만 통과시킨다(`location_decision.py:262-287`, `:454-478`; `backtest.py:920-927`). |
| `WATCH_HIGH`/`NO_PULLBACK`/`OVERHEATED` 실제 진입 차단 | **PASS** | evaluator 경계 테스트와 SQLite ledger를 포함한 runner 통합 테스트에서 trade/BUY 0건이 확인됐다. |
| weekly/m60/daily missing·`UNKNOWN` fail-closed | **PASS** | 네 필드의 단위 테스트 8개 조합과 missing runner 통합 경로가 모두 통과했다. |
| 반응 score SSOT | **PASS** | detector `total_score`가 evaluator의 `daily_ma_reaction` component로 직접 사용되며, break 음수 점수도 재계산 없이 유지된다(`daily_ma_reaction.py:320-342`; `location_score.py:93-119`; `location_decision.py:294-306`, `:401-417`). |
| 100점 배분 | **PASS** | `volume/m60_location/daily_ma_reaction/weekly_trend/slope/recent_5d_bullish/daily_trend_persistence = 30/20/20/10/10/5/5`, 최대 100점이다(`location_decision.py:401-417`). |
| break/recovery/HOLD/NONE 및 quality | **PASS** | SMA20 break -8 hard block, SMA5 break -4 WATCH 압력, recovery +6, HOLD +3, NONE 0과 quality 3/2/3/2, break/NONE quality 0, 20점 cap이 코드와 테스트에서 일치한다(`daily_ma_reaction.py:87-156`, `:264-342`). |
| Hard Blocks | **PASS** | SMA20 break/UNKNOWN, RR 미달, 과열, 눌림 부재, 필수 컨텍스트 미확인이 신규 진입을 차단한다. SMA5 break는 SSOT대로 WATCH 압력이다. |
| 모든 post-location REJECT ledger evidence | **PASS** | location-filter, 5분 반전 부재, `INVALID_STOP_OR_SIZE` REJECT가 공통 evidence를 사용하며 eligibility/veto/unknown/reaction/RR을 보존한다(`backtest.py:38-53`, `:920-950`, `:981-996`). |
| CLI/report payload | **PASS** | Markdown은 전달받은 reaction/quality/SMA 및 RR/supply payload를 JSON 직렬화하고, diagnostics JSON은 eligibility/veto/unknown을 포함한 전체 diagnostics를 기록한다(`cli.py:77-118`, `:311-375`, `:419-426`). |
| 주문·알림·스케줄러 불변 | **PASS** | `8e6f47a...89c1af7` 변경 파일에서 broker/order/notifier/scheduler/`.bat`/`.ps1` 파일 0건, 실행 코드의 관련 호출 추가 0건이다. |

## 독립 검증

| 명령/검증 | 결과 |
|---|---|
| `git rev-parse HEAD` | `89c1af7e07010e8ac0668d37043566d3b329b11b` — 요청 SHA 일치 |
| `python -m pytest -q` | **242 passed in 2.16s** |
| BLOCKER 경계 focused pytest 17건 | **17 passed in 0.65s** |
| `python -m compileall -q src` | **exit 0** |
| `git diff --check 8e6f47a...89c1af7` | **clean** |
| `git diff --check` | **clean** |
| 금지 운영영역 변경 검사 | 변경 파일 **0건**, 관련 실행 호출 추가 **0건** |

## 최종 결정

**PASS**

이전 두 BLOCKER의 fail-open 경로가 evaluator 계약, runner 소비 조건, diagnostics,
SQLite ledger evidence 및 회귀 테스트까지 일관되게 닫혔다. 승인 차단 잔여 이슈는 없다.
본 리뷰에서는 제품 코드·테스트·설정은 수정하지 않았고 이 승인 보고서만 생성했다.
