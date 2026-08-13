# LAT 5.0 일일 업무 — 2026-08-13

## 최종 리뷰 CHANGES remediation

- 작업 저장소: `C:\trading_system\LAT_5.0`
- 브랜치: `agent/daily-ma-reaction-score`
- remediation 시작 기준 HEAD: `8e6f47ad4a3cad366233bde04e29b0c96970c96c`
- 이 보고서 작성 직전 HEAD: `11fdfab` (`fix: enforce daily reaction in location gates`)
- Git 상태: 정상 Git 저장소이며 `.git`이 존재한다. 기존 문서의 “Git 저장소가
  아니어서 커밋할 수 없다”는 기록은 사실과 달라 삭제했다.

### 구현 결과

1. 일봉 대표반응 계약을 승인 설계에 맞게 완성했다.
   - `SMA5_HOLD +3`, `SMA20_CLOSE_BREAK -8`을 추가했다.
   - `NONE`에는 캔들 품질·골든크로스 보너스를 부여하지 않는다.
   - `five_day_state`는 대표반응의 축약값이 아니라 실제 SMA5 유지·이탈·회복
     상태를 기록한다.
2. 실제 운영 evaluator와 backtest gate를 fail-closed로 수정했다.
   - 양의 일봉 반응 점수는 `evaluate_watchlist_position()`의 실제
     `location_score`에 반영한다.
   - `SMA5_CLOSE_BREAK`는 -4점과 `DAILY_MA_WATCH_PRESSURE`로 BUY_READY를
     WATCH로 낮추며 Hard Block으로 취급하지 않는다.
   - `SMA20_CLOSE_BREAK`는 `DAILY_MA_HARD_BLOCK`, `UNKNOWN`·필수 데이터
     부족은 `DAILY_MA_REACTION_UNKNOWN`과 구체적인 `unknown_fields`로 BUY
     계열을 차단한다.
   - 기존 이격도·매물대 proxy·RR veto 의미는 유지했다.
3. CLI Markdown과 backtest 증거 직렬화를 연결했다.
   - backtest diagnostics가 평가된 후보의 실제 `daily_ma_reaction`과
     `rr_breakdown`을 보존한다.
   - hourly-pullback Markdown은 전달받은 후보 payload가 있을 때만 두 값을
     출력한다. 전달받지 않은 `volume_score`, `distance_state`, 실제 Volume
     Profile 값은 임의 생성하지 않는다.
   - location gate를 통과한 BUY decision ledger에도 동일한 반응/RR 근거를
     저장한다.

### TDD 및 검증

| 단계 | 명령 | 결과 |
|---|---|---|
| 기준선 | `python -m pytest -q` | 204 passed |
| 대표반응 RED→GREEN | `python -m pytest tests/test_daily_ma_reaction.py -q` | 51 passed |
| evaluator/backtest 집중 회귀 | `python -m pytest tests/test_daily_ma_reaction.py tests/test_location_score.py tests/test_location_context.py tests/test_location_decision.py tests/test_location_gate_integration.py -q` | 103 passed |
| CLI/보고 경로 집중 회귀 | `python -m pytest tests/test_cli.py tests/test_location_gate_integration.py -q` | 12 passed |
| 최종 전체 테스트 | `python -m pytest -q` | 215 passed |
| 컴파일 | `python -m compileall -q src` | exit 0 |
| diff 검사 | `git diff --check 8e6f47a..HEAD` 및 `git diff --check` | clean |

### 운영 경계

- broker 주문, 실주문, 알림, Telegram/Discord, Windows 작업 스케줄러를
  변경하거나 실행하지 않았다.
- `--location-filter` 기본값은 기존처럼 off다. 옵션을 켠 backtest 경로에서는
  일봉 반응 UNKNOWN이 fail-closed로 거래를 차단한다.

### 남은 경고

- `volume_score`와 `distance_state`는 현재 hourly-pullback diagnostics가 해당
  최종 필드를 전달하지 않으므로 Markdown에서 만들지 않는다.
- 실제 Volume Profile은 아직 구현되지 않았고, 현재 매물대 근거는 실제로 계산된
  경우에만 `swing_high_proxy_v1`로 표시한다.

## RSI(14) 관찰 전용

- Wilder RSI(14)는 완료 일봉과 `as_of` 이전 자료로만 계산하는 관찰용 수치다.
- 정상 시 `rsi14`는 숫자이며, 계산 불가 시 `rsi14=null` 및
  `unknown_fields`에 `rsi14`를 남긴다. 이 UNKNOWN은 RSI 관찰값의
  fail-closed 표현이며 일일 MA 반응 자체를 대체하지 않는다.
- `rsi_state`, `rsi_bonus`, `rsi_reasons`, recovery/divergence/overbought/
  weakening 자동판정은 제거했다.
- RSI는 daily reaction 점수, 20점 상한, 기존 100점 배분, gate, Hard Block,
  `entry_eligible`, WATCH 판정에 영향을 주지 않는다.
- context, decision payload, CLI Markdown, backtest/ledger evidence에는
  `rsi14`만 직렬화한다.

| RSI 검증 | 명령 | 결과 |
|---|---|---|
| daily/context/decision/CLI 집중 회귀 | `python -m pytest tests/test_daily_ma_reaction.py tests/test_location_context.py tests/test_location_decision.py tests/test_cli.py -q` | 120 passed |
| 전체 회귀 | `python -m pytest -q` | 248 passed |
| 컴파일 | `python -m compileall -q src` | exit 0 |
| diff 검사 | `git diff --check` | clean |
