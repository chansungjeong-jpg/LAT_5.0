# RSI 확인 보너스 설계

## 목적

Wilder RSI(14)를 독립 진입축으로 만들지 않고, 완료된 일봉의 `daily_ma_reaction` 품질을 보조한다. 기존 위치점수 100점 배분과 거래량 30점 최고 비중은 바꾸지 않는다.

## 데이터 및 실패-폐쇄 계약

- 계산과 비교는 `as_of` 이전의 완료 일봉만 사용한다. 같은 날의 미완료봉과 미래봉은 읽지 않는다.
- RSI는 Wilder 방식(`adjust=False`, 14개 변화량 이후 최초값)으로 계산한다.
- RSI 계산에 필요한 데이터가 부족하거나 RSI 값이 NaN/무한이면 반응 결과는 기존 `UNKNOWN` 계약을 사용한다. `unknown_fields`에는 `rsi14`를 남기며 BUY 계열은 기존 gate가 막는다.
- 이 규칙은 기존 OHLCV/SMA/ATR 검증을 대체하거나 약화하지 않는다.

## 점수와 상태

- `reaction total score = min(20, base_score + 기존 quality_bonus + rsi_bonus)`이다.
- RSI 보너스는 반응이 양수인 경우에만 적용한다. `NONE` 및 SMA 종가 이탈 반응은 0점이다.
- 전일 RSI < 30, 현재 RSI >= 30: `RSI_OVERSOLD_RECOVERY`, +3.
- 전일 RSI < 40, 현재 RSI >= 40: `RSI_40_RECOVERY`, +2. 두 회복은 +3만 선택한다.
- 최근 완료봉 5개 low의 최저값이 그 직전 5개 low의 최저값보다 낮고, 같은 두 구간 RSI 최저값은 높으면 `RSI_BULLISH_DIVERGENCE`, +2다. 현재 완료봉을 끝점으로 해석하며 미래 RSI를 사용하지 않는다.
- 현재 RSI >= 70: `rsi_state=OVERBOUGHT`, `rsi_bonus=0`, `rsi_reasons`에 근거를 남기고 evaluator에 `DAILY_MA_WATCH_PRESSURE`를 전달한다.
- 현재 RSI < 50 및 직전 완료봉 RSI보다 하락: `rsi_state=WEAKENING_BELOW_50`, 0점이다.
- 그 밖에는 `NEUTRAL`, 0점이다. 보너스 근거가 여럿이면 합산할 수 있다.

## 직렬화 및 소비자

`DailyMAReaction`, `build_context`, 결정 payload, CLI Markdown, backtest diagnostics/ledger evidence에 `rsi14`, `rsi_state`, `rsi_bonus`, `rsi_reasons`를 유지한다. `OVERBOUGHT`는 기존 SMA5 이탈과 같은 WATCH-pressure 경로를 공유하되 Hard Block, `entry_eligible`, 기존 veto의 의미는 변경하지 않는다.

## 검증

공개 `score_daily_reaction`, `build_context`, `evaluate_watchlist_position`, CLI report를 통해 회복 우선순위, divergence, overbought pressure, weakening 0점, UNKNOWN/no-lookahead와 직렬화를 테스트한다. 주문, 알림, 스케줄러는 범위 밖이다.
