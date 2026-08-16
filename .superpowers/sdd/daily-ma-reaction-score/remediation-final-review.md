# Daily MA Reaction Score — 최종 remediation 리뷰

- 저장소: `C:\trading_system\LAT_5.0`
- 비교 범위: `8e6f47a...a2dba0e`
- 검토일: 2026-08-13
- 최종 판정: **CHANGES**

## 결론

UNKNOWN과 `SMA20_CLOSE_BREAK`의 BUY 계열 차단, `SMA5_CLOSE_BREAK`의 -4점/WATCH 압력,
누락 반응 추가, `NONE` 품질 보너스 제거, diagnostics와 CLI Markdown 직렬화는 실제
경로에 구현됐다. 전체 테스트·컴파일·whitespace 검증도 통과했고 주문·알림·스케줄러
변경이나 기존 Hard Block/volume priority 회귀는 발견되지 않았다.

그러나 승인된 100점 SSOT는 실제 `evaluate_watchlist_position()`에 아직 통합되지 않았다.
현재 구현은 기존 100점에 일봉 반응을 추가한 뒤 100점으로 clamp하므로, 완전통과 후보에서는
`NONE/0`부터 `SMA60/+20`까지 같은 `100 / BUY_READY`가 된다. 또한 location gate를 통과한 뒤
5분 반전 부재로 REJECT되는 ledger 경로는 이미 계산된 reaction/RR payload를 버린다. 따라서
remediation을 최종 승인할 수 없다.

## BLOCKER

없음. UNKNOWN과 SMA20 종가 이탈은 실제 evaluator 및 location-filter backtest에서 fail-closed로
BUY 계열을 차단한다.

## MAJOR

### M1. 실제 evaluator가 SSOT 100점 배분을 사용하지 않고 기존 100점 위에 반응점수를 더한다

근거:

- SSOT는 거래량 30, 60분 위치 20, 일봉 반응 20 등 합계 100점으로 규정한다
  (`LAT_SIMPLE_v1_0_final_spec.md:475-484`). 구현 계획도 기존 100점 위에 가산하지 말라고
  명시한다(`docs/superpowers/plans/2026-08-13-daily-ma-reaction-score.md:178-204`).
- 순수 `score_location()`은 이 배분을 구현하지만, 실제 evaluator는 이를 호출하지 않는다.
  `evaluate_watchlist_position()`의 기존 가중치 합계가 이미 100점이다
  (`src/lat5/location_decision.py:13-20`, `:225-339`).
- remediation은 그 점수에 `daily_reaction_gate.component`를 더한 뒤 0~100으로 clamp한다
  (`src/lat5/location_decision.py:341`). 이는 100점 내 20점 재배분이 아니라 최대 120점 산식을
  사후 절단한 것이다.
- 독립 프로브의 완전통과 context 결과는 다음과 같았다.

| 반응 | 실제 evaluator 결과 |
|---|---|
| `NONE / 0` | `100 / BUY_READY` |
| `SMA5_HOLD / +3` | `100 / BUY_READY` |
| `SMA5_RECOVERY / +6` | `100 / BUY_READY` |
| `SMA60_UPWARD_CROSS_STRONG_BULL / +20` | `100 / BUY_READY` |

- 추가된 테스트도 기존 점수 92에 반응점수를 더하는 동작을 정답으로 고정한다
  (`tests/test_location_decision.py:264-293`). 따라서 테스트와 현재 코드는 일치하지만 SSOT와는
  일치하지 않는다.

영향:

- 기본 점수가 높은 후보에서는 일봉 반응의 강도가 순위와 점수를 전혀 구분하지 못한다.
- 실제 gate와 순수 SSOT scorer가 서로 다른 점수 체계를 유지해 동일 후보의 점수 의미가
  호출 경로에 따라 달라진다.

필요 변경:

- 실제 evaluator가 SSOT의 100점 배분을 소비하도록 하나의 점수 계약으로 통합한다.
- 완전통과 조건에서도 `NONE`, HOLD, recovery, strong reaction이 SSOT 배점대로 구분되고 총점이
  100을 넘지 않는 end-to-end 테스트를 추가한다.

### M2. location gate 통과 후 후속 REJECT ledger에서 reaction/RR 증거가 소실된다

근거:

- backtest는 location 판정 직후 reaction/RR을 보유하고 diagnostics에 저장한다
  (`src/lat5/backtest.py:876-900`). location-filter REJECT ledger에도 두 payload를 기록한다
  (`:901-918`).
- 하지만 gate 통과 후 5분 반전이 없으면 ledger 입력은 `pullback_low`와 `ma60`만 기록한다
  (`src/lat5/backtest.py:931-938`). reaction/RR을 추가하는 코드는 5분 진입이 확인된 뒤의
  BUY/INVALID_STOP 경로에만 있다(`:967-995`).
- 독립 프로브에서 이 경로의 `inputs_json` 키는 `['ma60', 'pullback_low']`뿐이었고,
  `daily_ma_reaction`과 `rr_breakdown`은 모두 없었다.
- 새 통합 테스트는 BUY ledger의 payload만 확인한다
  (`tests/test_location_gate_integration.py:161-170`). 후속 REJECT 보존 회귀 테스트는 없다.

영향:

- diagnostics/Markdown에는 위치 판정 근거가 남지만, 개별 ledger REJECT만 조회하면 당시 gate가
  받은 일봉 반응과 RR을 재구성할 수 없다.
- 기존 최종 리뷰 M3의 “BUY/후속 REJECT decision 입력 증거” 요구가 부분 완료 상태다.

필요 변경:

- location 판정 이후 생성되는 모든 ledger decision에 동일한 실제 reaction/RR payload를 전달한다.
- `FIVE_MINUTE_REVERSAL_MISSING_OR_INVALIDATED` 경로의 ledger 회귀 테스트를 추가한다.

## 검토 기준별 판정

| 기준 | 판정 | 근거 |
|---|---|---|
| 실제 evaluator/backtest gate가 daily reaction 사용 | **PASS (M1 제외)** | 공통 gate 호출 및 점수·veto 반영(`location_decision.py:247-371`), backtest location filter 호출(`backtest.py:876-919`) |
| UNKNOWN/SMA20 break BUY 계열 차단 | **PASS** | 각각 `DAILY_MA_REACTION_UNKNOWN`, `DAILY_MA_HARD_BLOCK`으로 `IGNORE`; 실제 backtest UNKNOWN 차단 테스트 존재 |
| `SMA5_HOLD +3` | **PASS** | detector `daily_ma_reaction.py:310-312`, 단위·evaluator 테스트 존재 |
| SMA5 break -4/WATCH, recovery | **PASS** | -4와 WATCH pressure(`location_score.py:115-116`, `location_decision.py:344-371`), recovery +6(`daily_ma_reaction.py:307-309`) |
| SMA20 break -8 | **PASS** | detector -8 및 Hard Block(`daily_ma_reaction.py:303-306`, `location_score.py:113-114`) |
| SMA60 cross strong body | **PASS** | 전일/당일 SMA60 관통, 양봉, strong body를 모두 요구(`daily_ma_reaction.py:281-289`) |
| `NONE` quality bonus 없음 | **PASS** | `NONE` 즉시 0 반환(`daily_ma_reaction.py:95-106`) 및 회귀 테스트 존재 |
| CLI Markdown/diagnostics payload 직렬화 | **PASS** | 전달된 `daily_ma_reaction`/`rr_breakdown`을 JSON 직렬화하며 누락 값을 생성하지 않음(`cli.py:77-118`, `backtest.py:888-899`) |
| ledger payload 보존 | **CHANGES** | BUY와 location-filter REJECT는 통과하지만 후속 5분 반전 부재 REJECT에서 소실(M2) |
| SSOT/코드/테스트 일치 | **CHANGES** | 실제 evaluator의 100점 산식이 SSOT와 불일치(M1) |
| 주문/알림/스케줄러 불변 | **PASS** | 변경 파일에 broker/order/notifier/scheduler/Telegram/Discord/`.bat`/`.ps1` 경로 없음; 외부 실행 없음 |
| 기존 Hard Block/volume priority 회귀 없음 | **PASS** | 기존 NO_PULLBACK/OVERHEATED/RR 판정은 유지되고 전체 회귀 통과; 실제 evaluator의 volume 25는 daily reaction 20보다 큼 |

## 독립 검증 결과

| 명령 | 결과 |
|---|---|
| `python -m pytest -q` | **215 passed in 1.87s** |
| `python -m compileall -q src` | **exit 0** |
| `git diff --check` | **clean** |
| `git diff --check 8e6f47a...HEAD` | **clean** |

## 최종 결정

**CHANGES**

- BLOCKER: 0
- MAJOR: 2
- MINOR: 0

fail-closed 안전 차단과 핵심 반응 규칙은 remediation됐지만, 실제 점수 SSOT 통합과 모든 ledger
결정의 증거 보존이 끝나지 않았다. M1과 M2를 해결한 뒤 재검토가 필요하다.
