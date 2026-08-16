# Daily MA Reaction Score — 최종 승인 리뷰

- 저장소: `C:\trading_system\LAT_5.0`
- 기준선: `8e6f47ad4a3cad366233bde04e29b0c96970c96c`
- 검토 HEAD: `3714acf1e4f673f82f21ad98a2925f02951f80ef`
- 검토일: 2026-08-13
- 최종 판정: **CHANGES**
- 심각도: **BLOCKER 2 / MAJOR 0 / MINOR 0**

## 결론

최신 remediation은 일봉 반응 점수 SSOT 자체를 정렬했다. detector의
`total_score`와 실제 evaluator의 `score_components.daily_ma_reaction`은
SMA5/SMA20 break, `NONE`, recovery, strong-body/quality/cap 경로에서 모두 일치한다.
SMA5 break는 `WATCH`, SMA20 break와 `UNKNOWN`은 BUY 계열 차단으로 동작한다.
100점 구성은 `30/20/20/10/10/5/5`이며 최대 100점이다. location 평가 이후 생성되는
REJECT ledger에는 동일한 실제 reaction/RR evidence가 보존되고, CLI Markdown과
diagnostics JSON도 전달받은 payload를 직렬화한다. 주문·알림·스케줄러 변경은 없다.

그러나 기존 Hard Block과 필수 데이터 누락이 `WATCH_HIGH`에서 우회된다.
백테스트는 `BUY_READY`뿐 아니라 `WATCH_HIGH`도 진입 후보로 통과시키므로, veto 또는
필수 데이터 누락이 있어도 5분 반전 후 실제 paper BUY 경로까지 진행할 수 있다.
이는 SSOT의 신규 BUY 금지 및 fail-closed 계약을 깨므로 최종 승인할 수 없다.

## BLOCKER

### B1. `NO_PULLBACK`/`OVERHEATED` veto가 60~79점 `WATCH_HIGH`에서는 BUY 경로를 막지 못한다

근거:

- evaluator는 눌림 부재와 과열을 각각 `NO_PULLBACK`, `OVERHEATED`로 기록한다
  (`src/lat5/location_decision.py:326-345`).
- 그러나 두 veto의 상태 강등은 최초 상태가 `BUY_READY`일 때만 적용된다
  (`src/lat5/location_decision.py:406-428`). 최초 점수가 60~79면 상태는
  `WATCH_HIGH`로 남는다.
- 백테스트 location gate는 `BUY_READY`와 `WATCH_HIGH`를 모두 통과시킨다
  (`src/lat5/backtest.py:918-927`).
- SSOT는 5분 EMA20 이격도 +3% 초과 시 신규 BUY 금지를 명시한다
  (`LAT_SIMPLE_v1_0_final_spec.md:562-576`).

독립 프로브:

| 케이스 | 점수 | veto | evaluator 상태 | backtest 통과 여부 |
|---|---:|---|---|---|
| 눌림 없음 | 70 | `NO_PULLBACK` | `WATCH_HIGH` | **통과** |
| 5분 이격 과열 | 70 | `OVERHEATED` | `WATCH_HIGH` | **통과** |

영향:

- 이름상 veto와 SSOT의 BUY 금지가 실제 gate에서 무력화된다.
- 5분 반전이 뒤에서 성립하면 REJECT가 아니라 paper BUY/order ledger 경로로 진행할 수 있다.

필요 변경:

- `NO_PULLBACK` 또는 `OVERHEATED`가 있으면 초기 점수 구간과 무관하게 backtest가
  허용하지 않는 상태로 강등해야 한다.
- 70점 `WATCH_HIGH` + 각 veto가 거래를 만들지 않는 end-to-end 회귀 테스트가 필요하다.

### B2. 100점 필수 구성요소 누락이 fail-closed되지 않고 `WATCH_HIGH`로 통과한다

근거:

- SSOT는 필수 데이터 누락을 REJECT로 정의하고, 확인 불가는 BUY 금지라고 명시한다
  (`LAT_SIMPLE_v1_0_final_spec.md:499-503`, `:750-774`). 최종 BUY에는
  Weekly/Daily Trend와 60분 위치가 필수다(`:642-656`).
- 실제 evaluator는 `weekly_trend_ok`와 `m60_slope_pct` 누락을
  `unknown_fields`에만 기록하고 veto를 만들지 않는다
  (`src/lat5/location_decision.py:357-370`). `m60_trend_ok`와
  `daily_trend_ok` 누락은 unknown field에도 남지 않는다.
- 누락으로 점수만 낮아져도 60~79점이면 `WATCH_HIGH`이며, 백테스트는 이를 통과시킨다.

독립 프로브:

| 누락 필드 | 점수 | 상태 | unknown/veto | backtest 통과 여부 |
|---|---:|---|---|---|
| `weekly_trend_ok` | 70 | `WATCH_HIGH` | unknown만 기록, veto 없음 | **통과** |
| `m60_trend_ok` | 60 | `WATCH_HIGH` | unknown/veto 없음 | **통과** |
| `daily_trend_ok` | 75 | `WATCH_HIGH` | unknown/veto 없음 | **통과** |
| `m60_slope_pct` | 70 | `WATCH_HIGH` | unknown만 기록, veto 없음 | **통과** |

필요 변경:

- 공식 100점 구성에 필요한 입력과 최종 BUY 필수 조건을 명시적으로 검증하고,
  누락 시 backtest가 허용하지 않는 fail-closed 상태/veto를 반환해야 한다.
- 각 필드 누락이 BUY ledger/order 생성으로 이어지지 않는 통합 회귀 테스트가 필요하다.

## 기준별 판정

| 검토 기준 | 판정 | 근거 |
|---|---|---|
| evaluator component = `daily_ma_reaction.total_score` | **PASS** | detector→context→evaluator 프로브에서 strong 20=20, SMA20 recovery 16=16, SMA5 recovery 12=12, SMA5 break -4=-4, `NONE` 0=0. break는 전달 score를 재계산하지 않는다(`daily_ma_reaction.py:95-106`, `:320-332`; `location_score.py:93-119`). |
| SMA5 break WATCH | **PASS** | -4 component와 `DAILY_MA_WATCH_PRESSURE`가 `WATCH`로 강등한다. |
| SMA20 break/UNKNOWN BUY 차단 | **PASS** | 각각 `DAILY_MA_HARD_BLOCK`, `DAILY_MA_REACTION_UNKNOWN`으로 `IGNORE` 처리한다(`location_decision.py:415-426`). |
| recovery/HOLD/60 strong body 계약 | **PASS** | 대표반응 우선순위, +6/+3, SMA60 관통·양봉·strong-body 조건 및 quality가 코드·테스트·프로브에서 일치한다. |
| 100점 배분 `30/20/20/10/10/5/5` | **PASS** | 실제 evaluator의 `score_components` 합산이 정확히 100점 최대다(`location_decision.py:380-396`). |
| Hard Blocks / fail-closed | **CHANGES** | daily MA 전용 veto와 RR은 통과하지만, B1/B2의 `WATCH_HIGH` 우회가 존재한다. |
| 모든 post-location REJECT ledger evidence 보존 | **PASS** | location-filter REJECT, 5분 반전 부재 REJECT, `INVALID_STOP_OR_SIZE`가 공통 `_location_ledger_evidence()`를 사용한다(`backtest.py:38-52`, `:918-950`, `:978-996`). location 평가 전 REJECT는 아직 reaction/RR이 계산되지 않은 경로다. |
| CLI/report 실제 payload 출력 | **PASS** | Markdown은 전달된 reaction/RR 객체를 그대로 JSON 직렬화하고(`cli.py:77-118`, `:311-375`), diagnostics JSON은 전체 diagnostics를 기록한다(`:419-426`). 독립 렌더 프로브에서 reaction, quality, SMA, RR, supply method가 모두 확인됐다. |
| 주문·알림·스케줄러 불변 | **PASS** | baseline→HEAD 16개 변경 파일 중 broker/order/notifier/scheduler/`.bat`/`.ps1` 파일 0건. 실행 코드 diff에서 외부 주문·알림·스케줄러 호출 변경 0건. 관련 문자열 1건은 remediation 보고서의 “변경하지 않았다” 문장뿐이다. |

## 독립 검증

| 명령/검증 | 결과 |
|---|---|
| `python -m pytest -q` | **224 passed in 1.95s** |
| `python -m compileall -q src` | **exit 0** |
| `git diff --check 8e6f47a...3714acf` | **clean** |
| `git diff --check` | **clean** |
| baseline/HEAD 확인 | 요청 SHA와 정확히 일치 |
| detector→evaluator 점수 프로브 | 모든 지정 반응에서 **match=true** |
| Hard Block 경계 프로브 | **FAIL** — B1/B2 재현 |
| CLI 실제 payload 렌더 프로브 | reaction/quality/SMA/RR/supply method 모두 출력 |
| 금지 운영영역 변경 검사 | 실행 코드 변경 0건 |

## 최종 결정

**CHANGES**

점수 SSOT, 일봉 반응 상태 계약, ledger evidence, CLI 직렬화, 운영 불변성은 승인 가능하다.
하지만 B1/B2는 단순 보고 불일치가 아니라 BUY 금지 조건을 실제 backtest 진입 경로가
통과하는 fail-open 문제다. 두 BLOCKER를 고치고 `WATCH_HIGH` 경계의 end-to-end 회귀를
추가한 뒤 재승인해야 한다.
