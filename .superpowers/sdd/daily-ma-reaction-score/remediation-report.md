# Daily MA Reaction Score — CHANGES Remediation Report

- 저장소: `C:\trading_system\LAT_5.0`
- 브랜치: `agent/daily-ma-reaction-score`
- 기준 HEAD: `8e6f47ad4a3cad366233bde04e29b0c96970c96c`
- 작성일: 2026-08-13
- 대상 리뷰: `.superpowers/sdd/daily-ma-reaction-score/final-review.md`

## 결론

최종 리뷰의 B1/B2, M1/M2/M3, N1 remediation을 실제 evaluator, backtest,
CLI Markdown 경로에 구현했다. 일봉 반응은 더 이상 반환 payload에만 머물지 않고
실제 `location_score`와 BUY 계열 gate를 변경한다. 일봉 필수 데이터 UNKNOWN과
SMA20 종가 이탈은 fail-closed이며, SMA5 종가 이탈은 감점과 WATCH 압력으로
보존된다.

## 리뷰 항목별 조치

| 리뷰 | 조치 | 회귀 증거 |
|---|---|---|
| B1 실제 gate 미연결 | `evaluate_watchlist_position()`이 공통 daily reaction gate를 호출하고 실제 점수·상태에 반영 | hold/recovery/strong 반응 점수 변화 및 strong의 BUY_READY 승격 테스트 |
| B2 UNKNOWN fail-open | `DAILY_MA_REACTION_UNKNOWN` veto와 `daily_ma_reaction.<field>` unknown 전파 | evaluator와 실제 backtest location filter의 UNKNOWN 차단 테스트 |
| M1 enum 누락 | `SMA5_HOLD +3`, `SMA20_CLOSE_BREAK -8` 추가 | 순수 반응 scorer 테스트 |
| M2 감점/NONE bonus | SMA5 이탈 -4 + WATCH, SMA20 이탈 -8 + Hard Block, `NONE` quality 0 | 순수 scorer와 두 location 경로 테스트 |
| M3 보고 가시성 | diagnostics/BUY ledger가 실제 `daily_ma_reaction`, `rr_breakdown`을 보존하고 Markdown이 전달값을 직렬화 | CLI serializer 및 backtest diagnostics 테스트 |
| N1 Git 모순 | 일일 보고서를 현재 브랜치와 기준 HEAD에 맞게 재작성 | `reports/2026-08-13_daily_work.md` |

## 설계 보존 사항

- 기존 watchlist, sector, trend, volume, pullback, 거리, 매물대 proxy, RR 판단은
  유지하고 daily reaction을 추가 gate 입력으로 적용했다.
- `SMA5_CLOSE_BREAK`는 Hard Block이 아니다.
- `SMA20_CLOSE_BREAK`와 daily reaction `UNKNOWN`은 BUY 계열을 차단한다.
- 점수는 0~100 범위를 유지한다. 양의 반응은 전달된 총점을 최대 20점까지 더하고,
  SMA5/SMA20 이탈은 각각 -4/-8로 반영한다.
- 보고서는 전달받은 실제 payload만 출력한다. 누락된 `volume_score`,
  `distance_state`, Volume Profile 값을 생성하지 않는다.

## 변경 파일

- `src/lat5/daily_ma_reaction.py`
- `src/lat5/location_score.py`
- `src/lat5/location_decision.py`
- `src/lat5/backtest.py`
- `src/lat5/cli.py`
- `tests/test_daily_ma_reaction.py`
- `tests/test_location_score.py`
- `tests/test_location_context.py`
- `tests/test_location_decision.py`
- `tests/test_location_gate_integration.py`
- `tests/test_cli.py`
- `LAT_SIMPLE_v1_0_final_spec.md`
- `reports/2026-08-13_daily_work.md`

## 커밋

1. `5c1739e fix: complete daily reaction states and quality`
2. `11fdfab fix: enforce daily reaction in location gates`
3. 최종 보고/직렬화 커밋: `fix: close daily reaction gate and reporting gaps`

## 검증

| 명령 | 결과 |
|---|---|
| `python -m pytest -q` | 215 passed |
| `python -m compileall -q src` | exit 0 |
| `git diff --check 8e6f47a..HEAD` 및 `git diff --check` | clean |

## 운영 경계와 잔여 WARN

- 주문, 실주문, 알림, 스케줄러는 변경하거나 실행하지 않았다.
- CLI의 `--location-filter` 기본값은 기존처럼 off다. 명시적으로 활성화된 경로에서
  신규 fail-closed gate가 적용된다.
- hourly-pullback diagnostics가 제공하지 않는 `volume_score`와
  `distance_state`는 Markdown에 표시하지 않는다.
