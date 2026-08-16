# Daily MA Reaction Score — 최종 전체 브랜치 리뷰

- 저장소: `C:\trading_system\LAT_5.0`
- 브랜치: `agent/daily-ma-reaction-score`
- 비교 범위: `655b1b0...8e6f47a`
- 검토일: 2026-08-13
- 최종 판정: **CHANGES**

## 요약

룩어헤드 방지, 입력 검증, 구현된 네 반응의 대표 우선순위, 강한 몸통/종가 위치/기울기/골든크로스 품질 계산, 20점 상한 자체는 잘 구현되어 있다. 전체 테스트와 컴파일, whitespace 검증도 통과했고 주문·알림·스케줄러 범위는 변하지 않았다.

그러나 승인 설계의 핵심인 일봉 반응 점수가 실제 위치 gate와 백테스트 판정에 연결되지 않았다. 새 `score_location()`은 테스트 외 호출이 없고, 실제 백테스트가 호출하는 `evaluate_watchlist_position()`은 일봉 반응을 점수나 veto에 사용하지 않고 반환 payload에만 복사한다. 필수 일봉 반응 데이터가 `UNKNOWN`이어도 BUY가 가능해 fail-closed Hard Block 계약도 깨진다. 따라서 기능의 end-to-end 완료로 승인할 수 없다.

## BLOCKER

### B1. 새 100점 scorer와 일봉 반응이 실제 gate/backtest 판정에 연결되지 않았다

근거:

- `src/lat5/location_score.py:81-158`의 `score_location()`은 `src/`에서 호출되지 않고 `tests/test_location_score.py`에서만 호출된다.
- 실제 백테스트는 `src/lat5/backtest.py:875-900`에서 `build_context()` 후 `evaluate_watchlist_position()`을 호출한다.
- `src/lat5/location_decision.py:197-379`의 실제 evaluator는 `daily_ma_reaction_score`와 `daily_ma_reaction_state`를 점수 계산에 사용하지 않는다. 이 값은 최종 반환의 `daily_ma_reaction` payload에만 포함된다.
- 독립 계약 프로브에서 같은 완전통과 context에 다음 세 값을 넣어도 결과가 모두 동일했다.

| 반응 입력 | 실제 결과 |
|---|---|
| `UNKNOWN / 0` | `100 / BUY_READY` |
| `SMA60_UPWARD_CROSS_STRONG_BULL / 20` | `100 / BUY_READY` |
| `SMA5_CLOSE_BREAK / -4` | `100 / BUY_READY` |

영향:

- 새 반응은 실제 후보 통과/차단, 거래 수, 손익, PF에 아무 영향이 없다.
- 계획의 “`evaluate_watchlist_position()` consumes it” 계약(`docs/superpowers/plans/2026-08-13-daily-ma-reaction-score.md:216-225`)과 승인 설계의 동일기간 백테스트 비교 요구(`docs/superpowers/specs/2026-08-13-daily-ma-reaction-score-design.md:143-150`)를 달성하지 못했다.
- `--location-filter`도 기본값이 꺼져 있어(`tests/test_cli.py:48-59`, `src/lat5/cli.py:368-370`) 기본 CLI 백테스트에는 context 계산조차 적용되지 않는다.

필요 변경:

- 하나의 SSOT 100점 scorer를 실제 evaluator/gate/backtest 경로에서 호출한다.
- 반응 점수 `0/+20/-4` 및 `UNKNOWN`이 실제 state/score/veto를 바꾸는 end-to-end 테스트를 추가한다.
- 기존 위치 점수와 새 점수의 동일기간 비교 산출물을 남긴다.

### B2. 필수 일봉 이평선 데이터 누락이 fail-closed Hard Block이 아니다

근거:

- 승인 설계는 필수 가격·거래량·이평선 데이터 누락을 Hard Block으로 규정한다(`docs/superpowers/specs/2026-08-13-daily-ma-reaction-score-design.md:115-124`). 구현 계획도 missing required data Hard Block 보존을 요구한다(`docs/superpowers/plans/2026-08-13-daily-ma-reaction-score.md:18`).
- `src/lat5/location_score.py:75-78`은 반응 score/state가 없거나 `UNKNOWN`이면 단순히 0점으로 바꾸며, required/unknown/veto에 넣지 않는다.
- `tests/test_location_score.py:71-89`는 오히려 `UNKNOWN` 또는 `None`이어도 최종 `BUY`가 되는 동작을 고정한다.
- 독립 프로브 결과도 `score_location(UNKNOWN/0) -> 80 / BUY`, unknown fields와 veto 모두 빈 값이었다.
- 실제 evaluator는 B1처럼 반응 상태를 읽지 않으므로 `UNKNOWN`이 `BUY_READY`를 막지 못한다.

영향:

- SMA60/ATR/필수 OHLCV가 부족하거나 잘못된 후보도 다른 점수만 높으면 BUY 계열 상태가 될 수 있다.
- 순수 반응 함수는 `UNKNOWN`을 올바르게 산출하지만 orchestration 단계에서 안전 정보가 소실된다.

필요 변경:

- 반응에 필요한 필수 데이터의 `UNKNOWN`을 명시적 unknown/veto로 전파하고 BUY 계열 상태를 차단한다.
- malformed/insufficient daily data가 실제 gate와 백테스트에서 fail closed 되는 회귀 테스트를 추가한다.

## MAJOR

### M1. 승인된 대표 반응 두 개가 누락됐고 SSOT가 구현에 맞춰 축소됐다

승인 설계에는 `5일선 위 종가 유지 +3`과 `20일선 종가 이탈 -8`이 포함된다(`docs/superpowers/specs/2026-08-13-daily-ma-reaction-score-design.md:27-39`). 현재 구현은 다음 다섯 상태만 가진다(`src/lat5/daily_ma_reaction.py:263-289`).

- `SMA60_UPWARD_CROSS_STRONG_BULL`
- `SMA20_PULLBACK_RECOVERY`
- `SMA5_RECOVERY`
- `SMA5_CLOSE_BREAK`
- `NONE`

`SMA5_HOLD`와 `SMA20_CLOSE_BREAK`가 없고 독립 테스트도 없다. `five_day_state` 역시 회복/이탈 외에는 항상 `NONE`이다(`src/lat5/location_decision.py:105-109`). 공식 SSOT도 승인 설계가 아니라 축소된 enum을 기록한다(`LAT_SIMPLE_v1_0_final_spec.md:505-517`). Task 6 보고서와 일일 보고서는 미구현을 알고도 다음 승인 대상으로 돌렸다(`.superpowers/sdd/daily-ma-reaction-score/task-6-report.md:58-60`, `reports/2026-08-13_daily_work.md:38-40`). 이번 리뷰 범위가 “승인 설계 전체 달성”이므로 부분 완료다.

### M2. 감점/WATCH와 “골든크로스 비독립 신호” 계약이 점수 계산에서 깨진다

- 승인 계약은 SMA5 종가 이탈을 `-4` 감점 및 WATCH 압력으로 규정한다(`docs/superpowers/plans/2026-08-13-daily-ma-reaction-score.md:19`). 그러나 `src/lat5/location_score.py:75-78`이 모든 음수를 0으로 clamp한다. 실제 evaluator는 반응을 무시하므로 감점과 WATCH 압력이 모두 사라진다.
- `_quality_bonus()`는 대표 반응이 `NONE`이어도 strong body, close-near-high, golden cross를 계산한다(`src/lat5/daily_ma_reaction.py:89-138`). 독립 프로브에서 `reaction=NONE`, `base_score=0`, `golden_cross=2`, `total_score=2`가 재현됐다. 이는 “골든크로스는 단독 매수 신호가 아니라 반응 품질 보너스” 계약(`docs/superpowers/specs/2026-08-13-daily-ma-reaction-score-design.md:19`)과 맞지 않는다.
- 테스트는 골든크로스가 기존 standalone location component가 아닌지만 확인하고, 대표 반응이 없을 때 품질점수가 0인지 검증하지 않는다.

필요 변경:

- 음수 반응의 의미를 100점 scorer에서 실제 감점 또는 명시적 WATCH pressure로 보존한다.
- 품질 보너스는 유효한 대표 반응에만 붙도록 계약을 명확히 하고 `NONE + golden cross` 회귀 테스트를 추가한다.

### M3. CLI Markdown/report 직렬화 경고는 실제 사용자 가시성 결손이다

계획은 대표 반응, 점수, 품질, SMA, 5일 상태, volume, distance, supply/RR, final state를 보고서에 표시하도록 요구한다(`docs/superpowers/plans/2026-08-13-daily-ma-reaction-score.md:276`). SSOT도 이를 최소 후보 출력으로 명시한다(`LAT_SIMPLE_v1_0_final_spec.md:771-816`).

실제 영향:

- `src/lat5/cli.py:267-329`의 기본 hourly-pullback Markdown renderer는 per-candidate location payload를 받지 않는다.
- 독립 렌더 프로브에 `daily_ma_reaction`을 diagnostics로 넣어도 Markdown에는 reaction, SMA, `volume_score`, `distance_state`, `rr_breakdown` 어느 것도 출력되지 않았다.
- `src/lat5/cli.py:371-399`의 diagnostics JSON도 summary/aggregate diagnostics만 기록하고 후보별 location payload를 전달하지 않는다.
- 백테스트 ledger는 location에 의해 필터된 REJECT에만 reaction payload를 기록한다(`src/lat5/backtest.py:886-899`). gate를 통과한 BUY/후속 REJECT decision 입력(`src/lat5/backtest.py:946-963`)에는 reaction evidence가 없다.

따라서 Task 6의 “범용 CLI가 payload를 받지 않는다”는 문구는 무해한 직렬화 경고가 아니라, 표준 CLI 보고서로는 새 기능의 판정 근거를 감사할 수 없다는 기능 미완료다. CLI 테스트도 기존 제목/조건 문자열만 검사하며 신규 payload 계약을 검증하지 않는다(`tests/test_cli.py:62-165`).

## MINOR

### N1. 일일 보고서가 현재 저장소 상태와 내부적으로 모순된다

`reports/2026-08-13_daily_work.md:83`은 현재 경로가 Git 저장소가 아니고 `.git`도 없다고 기록하지만, 실제로는 `agent/daily-ma-reaction-score` 브랜치의 Git 저장소이며 HEAD는 `8e6f47a`다. 같은 문서의 “추가 예정” 및 “기본 Backtest/CLI 경로에 연결” 항목(`:67`, `:78`)도 상단의 완료 서술과 충돌한다. 운영 handoff 문서로 사용하려면 현재 상태에 맞게 정리해야 한다.

## 통과 항목

- **No lookahead:** `as_of`와 같은 달력 날짜 및 미래 일봉을 제외하며, 중복 날짜/비정렬/비수치/비유한 OHLCV를 `UNKNOWN`으로 fail closed 한다(`src/lat5/daily_ma_reaction.py:157-237`). 관련 경계 테스트가 있다.
- **대표 우선순위:** 현재 구현된 네 반응 사이에서는 하나만 선택하며 SMA60 → SMA20 → SMA5 recovery → SMA5 break 순서가 유지된다.
- **품질 계산:** strong body는 bullish + ATR14 비율 + 최근 20 body p80을 요구하고, close-near-high 0.70, 반응 SMA 기울기, 골든크로스 +2 및 총점 20 cap을 검증한다.
- **Volume priority:** 순수 100점 scorer의 최대 배점은 volume 30, m60/daily reaction 각 20으로 volume이 가장 크다(`src/lat5/location_score.py:120-135`). 기존 실제 evaluator의 volume 관련 경로는 이번 branch에서 변경되지 않았다.
- **기존 Hard Block 회귀:** 기존 distance/supply proxy/RR 판정 코드는 branch에서 변경되지 않았다. 다만 신규 daily reaction `UNKNOWN`의 Hard Block 누락은 B2로 차단한다.
- **운영 범위:** 변경된 production 파일은 `daily_ma_reaction.py`, `location_score.py`, `location_decision.py`, `backtest.py`뿐이다. broker order, live order, notification, Telegram/Discord, scheduler, `.bat`/`.ps1` 경로 변경은 없다. 외부 전송이나 스케줄러 실행도 수행하지 않았다.
- **API alias:** 계획상 `score_daily_ma_reaction()`과 기존 작업에서 사용한 `score_daily_reaction()`은 동일 함수 alias로 제공되어 이름 호환성은 유지된다.

## 독립 검증 결과

| 명령 | 결과 |
|---|---|
| `python -m pytest -q` | **204 passed in 1.81s** |
| `python -m compileall -q src` | **exit 0** |
| `git diff --check 655b1b0...8e6f47a` | **clean** |

추가 read-only 계약 프로브:

- actual evaluator reaction sensitivity: **FAIL** — `UNKNOWN/0`, `SMA60/+20`, `SMA5_BREAK/-4` 모두 `100 / BUY_READY`
- pure 100-point scorer UNKNOWN handling: **FAIL** — `UNKNOWN/0 -> 80 / BUY`, unknown/veto 없음
- golden-cross isolation: **FAIL** — `NONE + golden_cross -> total_score 2`
- CLI Markdown payload visibility: **FAIL** — 신규 reaction/SMA/volume/distance/RR 필드 미출력

## 최종 결정

**CHANGES**

- BLOCKER: 2
- MAJOR: 3
- MINOR: 1

테스트와 컴파일은 통과했지만 승인 설계의 실제 소비 경로, fail-closed Hard Block, 전체 반응 enum, 감점 의미, 보고 가시성이 완성되지 않았다. B1/B2를 해결하고 M1-M3에 대한 end-to-end 회귀 테스트와 CLI/ledger 증거를 추가한 뒤 재리뷰가 필요하다.
