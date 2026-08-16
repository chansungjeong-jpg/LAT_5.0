# RSI 구현 최종 리뷰

## 판정

**PASS**

- 기준: `89c1af7` → `f8e9c52`
- 차단 이슈: 없음
- 심각도별 발견: Critical 0 / High 0 / Medium 0 / Low 0
- 코드 수정: 없음

## 요구사항별 결과

| 검토 항목 | 결과 | 심각도 | 근거 |
|---|---|---|---|
| Wilder RSI(14) | PASS | 없음 | `src/lat5/daily_ma_reaction.py:66`에서 최초 14개 변화량의 단순 평균으로 seed한 뒤 Wilder 재귀 평활을 적용한다. 고전 기준 수열의 기대값 `70.46, 66.25, 66.48, 69.35, 66.29, 57.92`와 소수 둘째 자리까지 일치했다. 상승만 있는 구간은 100, 하락만 있는 구간은 0, gain/loss가 모두 0인 구간은 중립 50으로 명시 처리한다. |
| completed-bar / `as_of` / no-lookahead | PASS | 없음 | `src/lat5/daily_ma_reaction.py:252`에서 날짜 정규화 기준 `index < as_of`인 완료 일봉만 선택한다. 동일 일자·미래 봉은 SMA/ATR/RSI/반응 계산 전에 제외된다. 공개 API 회귀 테스트도 당일 극단값 삽입 전후 RSI 결과 불변을 확인한다. |
| fail-closed | PASS | 없음 | 비 DatetimeIndex, 정렬 오류, 중복 일자, 필수 OHLCV 누락·비유한 값, SMA60 또는 RSI 계산 부족은 `UNKNOWN`, 0점으로 끝난다. RSI 부족/invalid close는 `unknown_fields`에 `rsi14`를 남기며 evaluator가 `DAILY_MA_REACTION_UNKNOWN`으로 BUY 계열을 차단한다. |
| RSI 회복 보너스 중복 금지 | PASS | 없음 | `src/lat5/daily_ma_reaction.py:138`의 `if/elif`로 `<30 → >=30` +3을 우선하고, 그 경우 `<40 → >=40` +2를 중복 적용하지 않는다. 양수 일봉 반응에만 적용된다. |
| 최근 5봉 bullish divergence | PASS | 없음 | 현재 완료 5봉과 직전 완료 5봉을 분리해 `현재 price-low < 직전 price-low`이면서 `현재 RSI-low > 직전 RSI-low`일 때만 +2다. 양 구간 모두 완료봉에서만 계산되고 미래 봉은 참조하지 않는다. |
| OVERBOUGHT / WEAKENING | PASS | 없음 | RSI `>=70`은 `OVERBOUGHT`, 0점, `DAILY_MA_WATCH_PRESSURE`로 BUY_READY/WATCH_HIGH를 WATCH로 낮추며 Hard Block은 추가하지 않는다. RSI `<50`이고 직전 완료봉보다 하락하면 `WEAKENING_BELOW_50`, 0점이다. |
| daily reaction 20 cap / 100점 배분 | PASS | 없음 | `src/lat5/daily_ma_reaction.py:425`에서 합계를 20으로 cap한다. evaluator 구성은 거래량 30 + 60분 위치 20 + 일봉 반응 20 + 주봉 10 + 기울기 10 + 최근 5일 5 + 일봉 지속성 5 = 100으로 유지된다. |
| UNKNOWN / `entry_eligible` / Hard Blocks 회귀 | PASS | 없음 | UNKNOWN과 SMA20 종가 이탈은 기존 IGNORE/Hard Block 경로를 유지한다. OVERBOUGHT는 WATCH pressure만 추가되고 최종 `entry_eligible`은 기존 정의인 `state == BUY_READY and not vetoes`를 그대로 사용한다. 전체 회귀 테스트가 통과했다. |
| context / CLI / report / ledger 직렬화 | PASS | 없음 | `build_context()`가 `rsi14`, `rsi_state`, `rsi_bonus`, `rsi_reasons`를 payload에 넣고, 결정 결과가 같은 dict를 보존한다. CLI는 payload를 JSON으로 직접 렌더링하며, backtest diagnostics와 `_location_ledger_evidence()`도 필터링 없이 전달한다. |
| 주문 / 알림 / 스케줄러 불변 | PASS | 없음 | baseline→HEAD의 런타임 변경 파일은 `src/lat5/daily_ma_reaction.py`, `src/lat5/location_decision.py`뿐이다. broker/order/notification/scheduler 경로 변경이나 실행은 없었다. |

## 독립 검증

| 명령 | 결과 |
|---|---|
| `python -m pytest -q` | `250 passed in 2.30s` |
| `python -m compileall -q src` | exit 0 |
| `git diff --check 89c1af7..HEAD` | clean, exit 0 |
| `git diff --check` | clean, exit 0 |
| 고전 Wilder RSI 기준 수열 독립 대조 | 기대값 6개와 소수 둘째 자리 일치, 최대 반올림 오차 0.0 |

## 리뷰 결론

요청된 RSI 확인 계약은 baseline 대비 정확히 구현됐고, 점수 상한·100점 배분·UNKNOWN 및 Hard Block 안전성·직렬화·운영 경계를 회귀시키지 않았다. 병합 전 필수 변경사항은 없다.
