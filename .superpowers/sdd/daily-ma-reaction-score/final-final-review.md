# Daily MA Reaction Score — 최종 전체 검증 리뷰

- 저장소: `C:\trading_system\LAT_5.0`
- 비교 범위: `8e6f47ad4a3cad366233bde04e29b0c96970c96c..e0e0273274bb2b6ff827672346afffa07dab0921`
- 검토일: 2026-08-13
- 검토 방식: 지정 문서 재검토, baseline→HEAD diff 정적 검토, 독립 계약 프로브, 전체 회귀/컴파일/diff 검증
- 최종 판정: **CHANGES**

## 결론

이전 리뷰의 두 핵심 remediation은 대부분 해결됐다. 실제 `evaluate_watchlist_position()`은
거래량/60분 위치/일봉 반응/주봉 추세/정규화 기울기/최근 5일 양봉/일봉 추세 지속성을
`30/20/20/10/10/5/5`로 합산하며, 기존 100점 위 가산과 사후 100점 clamp는 제거됐다.
UNKNOWN과 SMA20 종가 이탈은 BUY 계열을 차단하고, SMA5 종가 이탈은 WATCH 압력으로
남는다. location 평가 이후의 ledger REJECT 경로와 CLI/report도 전달받은 실제
`daily_ma_reaction`/`rr_breakdown` payload를 그대로 사용한다. 주문·알림·스케줄러 변경은 없다.

그러나 품질 보너스가 붙은 SMA5/SMA20 종가 이탈에서는 반응 함수가 계산한 실제
`total_score`를 evaluator가 소비하지 않는다. gate가 상태명만 보고 component를 다시
`-4/-8`로 고정해 SSOT의 `기본 점수 + 품질 보너스` 계약, 전달 payload, 실제
`score_components`가 서로 달라진다. 안전 차단 상태는 유지되지만 최종 점수 SSOT가 아직
완전히 일치하지 않으므로 승인할 수 없다.

## BLOCKER

없음.

UNKNOWN은 `DAILY_MA_REACTION_UNKNOWN`, SMA20 종가 이탈은 `DAILY_MA_HARD_BLOCK`으로
실제 evaluator와 location-filter backtest에서 BUY 계열을 차단한다.

## MAJOR

### M1. 이탈 반응의 품질 보너스가 실제 evaluator 점수에서 소실된다

근거:

- SSOT는 대표반응의 합계를 `min(20, 기본 점수 + 품질 보너스)`로 정의하고,
  `NONE`일 때만 품질 보너스를 0으로 제한한다
  (`LAT_SIMPLE_v1_0_final_spec.md:521-525`).
- 반응 함수도 모든 non-`NONE` 반응에 품질을 계산하고 실제 `total_score`를
  `min(20, base_score + quality_bonus)`로 만든다
  (`src/lat5/daily_ma_reaction.py:87-156`, `:320-332`).
- 그러나 공통 gate는 전달된 `score`를 사용하지 않고 `SMA20_CLOSE_BREAK`이면 `-8`,
  `SMA5_CLOSE_BREAK`이면 `-4`를 반환한다
  (`src/lat5/location_score.py:93-119`). 실제 evaluator는 이 값을 그대로 20점 구성요소에
  넣는다(`src/lat5/location_decision.py:380-396`).
- 독립 실제 데이터 프로브 결과:

| 항목 | 값 |
|---|---:|
| 대표반응 | `SMA5_CLOSE_BREAK` |
| 기본 점수 | -4 |
| 품질 보너스 | +5 |
| 반응 payload의 `total_score` | 1 |
| evaluator의 `daily_ma_reaction` component | -4 |
| 상태 | `WATCH` |

  재현된 품질 근거는 `CLOSE_NEAR_HIGH`, `REACTION_SLOPE_UP`이다. 즉 동일 판정의
  serialized reaction score는 1인데 실제 위치 총점에는 -4가 반영되어 5점 차이가 난다.
  SMA20 이탈도 같은 방식으로 품질 조정 점수를 버리지만 Hard Block 자체는 유지된다.
- 테스트는 이탈 상태에 입력 점수를 각각 `-4/-8`로 직접 넣고 같은 component를 기대하므로
  품질 보너스가 붙은 detector→gate 경계를 검증하지 않는다
  (`tests/test_location_score.py:96-120`, `tests/test_location_decision.py:320-340`).

영향:

- 최종 `location_score`와 `score_components.daily_ma_reaction`이 실제
  `daily_ma_reaction.score` 및 SSOT 산식과 달라진다.
- SMA5 이탈은 WATCH로 안전하게 제한되지만, 점수·랭킹·보고 근거가 실제 반응 payload보다
  낮아져 동일 후보의 점수 의미가 경로별로 달라진다.
- SMA20 이탈의 BUY 차단은 유지되므로 안전 BLOCKER로 분류하지는 않는다.

필요 변경:

- 이탈 여부는 현재처럼 veto/WATCH pressure로 판정하되, 20점 component에는 반응 함수가
  산출한 실제 `total_score`를 사용한다.
- 품질 보너스가 있는 `SMA5_CLOSE_BREAK`와 `SMA20_CLOSE_BREAK`에 대해
  detector→gate→`evaluate_watchlist_position()` end-to-end 회귀 테스트를 추가한다.

## 기준별 판정

| 검증 기준 | 판정 | 근거 |
|---|---|---|
| 실제 evaluator 배점 `30/20/20/10/10/5/5`, 최대 100 | **PASS** | `score_components`만 합산하며 최대값은 100이다(`location_decision.py:380-396`). 독립 프로브는 `NONE/HOLD/RECOVERY/STRONG = 80/83/86/100`을 재현했다. |
| 기존 점수 가산 및 사후 clamp 제거 | **PASS** | 기존 sector/trend/pullback/distance/RR 점수 가산문과 `min/max 100` clamp는 실제 evaluator에서 제거됐다. `LocationScoreWeights`는 남아 있으나 현재 산식에서는 사용되지 않는다. |
| UNKNOWN fail-closed | **PASS** | component 0, `DAILY_MA_REACTION_UNKNOWN`, `IGNORE`, 구체적 unknown field 전파가 유지된다. |
| SMA20 종가 이탈 Hard Block | **PASS (점수 M1 제외)** | `DAILY_MA_HARD_BLOCK`으로 `IGNORE`; 품질 조정 component만 M1과 불일치한다. |
| SMA5 종가 이탈 WATCH pressure | **PASS (점수 M1 제외)** | Hard Block이 아니며 `DAILY_MA_WATCH_PRESSURE`로 BUY 계열을 `WATCH`로 낮춘다. |
| SMA5 recovery/HOLD | **PASS** | 각각 +6/+3 대표반응과 실제 evaluator 구분이 코드·테스트·프로브에서 일치한다. |
| SMA60 strong body | **PASS** | 전일/당일 SMA60 상향 관통, 양봉, ATR14 및 최근 body p80 강한 몸통을 요구한다. |
| `NONE` quality 0 및 골든크로스 비독립 | **PASS** | `NONE`은 모든 품질 component 0으로 즉시 반환하며 evaluator에 별도 golden-cross 항목이 없다. |
| 대표반응 우선순위 | **PASS** | SMA60 → SMA20 recovery → SMA20 break → SMA5 recovery → HOLD → SMA5 break → NONE 순서로 단일 반응만 채택한다. |
| location 평가 이후 모든 ledger REJECT evidence 보존 | **PASS** | location-filter REJECT, 5분 반전 부재 REJECT, `INVALID_STOP_OR_SIZE`가 공통 `_location_ledger_evidence()`를 사용한다(`backtest.py:38-52`, `:918-950`, `:978-996`). location 평가 전 `MA60_PULLBACK_2_TO_6_MISSING`은 아직 reaction/RR을 계산하지 않은 선행 경로다. |
| CLI/report는 실제 전달 payload만 사용 | **PASS** | diagnostics가 가진 두 payload를 그대로 JSON 직렬화하며 누락 시 `null`로 남긴다. volume/supply 값을 추정 생성하지 않는다(`cli.py:77-118`, `backtest.py:905-916`). |
| 주문·알림·스케줄러 불변 | **PASS** | baseline→HEAD 변경 파일명 및 변경 라인 검사에서 broker/order/notifier/Telegram/Discord/scheduler/`.bat`/`.ps1` 변경 0건. 외부 전송·주문·스케줄러 실행 없음. |
| SSOT/코드/테스트 일치 | **CHANGES** | 정상 반응·상태·안전 veto는 일치하지만, 품질 보너스가 있는 이탈 반응의 실제 component가 M1처럼 불일치한다. |

## 독립 검증 결과

| 명령/검증 | 결과 |
|---|---|
| `python -m pytest -q` | **219 passed in 1.94s** |
| `python -m compileall -q src` | **exit 0** |
| `git diff --check 8e6f47a..e0e0273` | **clean** |
| `git diff --check` | **clean** |
| baseline/HEAD 확인 | `8e6f47ad...` / `e0e027327...`, 요청 범위와 일치 |
| 금지영역 파일명 및 변경 라인 검사 | **0건** |
| 실제 evaluator 반응 프로브 | `NONE/HOLD/RECOVERY/STRONG = 80/83/86/100`; UNKNOWN=`IGNORE`; SMA20 break=`IGNORE`; SMA5 break=`WATCH` |
| 품질 포함 이탈 경계 프로브 | **FAIL** — payload score 1, evaluator component -4 |

## 최종 결정

**CHANGES**

- BLOCKER: 0
- MAJOR: 1
- MINOR: 0

전체 테스트·컴파일·diff 검증은 통과했고 이전 remediation의 점수 재배분, fail-closed,
ledger evidence, CLI 직렬화, 운영 불변성은 확인됐다. 다만 M1 때문에 실제 100점 component와
전달 evidence가 동일한 SSOT를 표현하지 않는다. 이탈 반응의 품질 조정 점수를 실제 evaluator에
보존하고 해당 end-to-end 회귀 테스트를 추가한 뒤 승인해야 한다.
