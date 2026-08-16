# Task 1 구현 리뷰

## 판정

**변경 요청 (MAJOR 3, MINOR 1).**  새 모듈은 Task 1 범위를 벗어나지 않았고, 현 체크아웃에서 focused `4 passed`, 전체 `152 passed`는 재현됐다. 그러나 공개 계약명, completed-bar/no-lookahead 경계, OHLCV 유효값 처리 때문에 Task 1 계약을 승인할 수 없다.

## 검증 근거

| 항목 | 독립 검증 결과 | 판단 |
|---|---|---|
| focused test | `python -m pytest tests/test_daily_ma_reaction.py -q` -> `4 passed in 0.56s` | 보고서와 일치 |
| 전체 회귀 | `python -m pytest -q` -> `152 passed in 1.91s` | 보고서와 일치 |
| diff/범위 | `655b1b0..7866790`은 모듈, 전용 테스트, 구현 보고서만 변경; `git diff --check`도 깨끗함 | Task 1 범위 이탈 없음 |
| 테스트 신뢰도 | 네 테스트는 정상 경로/미래 행 배제/컬럼 부재만 다룬다 | 아래 경계 결함을 검출하지 못함 |

## 발견 사항

### MAJOR — 계획의 공개 함수 계약이 구현에 없다

- 근거: [task-1-brief.md](task-1-brief.md) 8-10행은 `score_daily_ma_reaction(daily, as_of)`를 공개 인터페이스로 정의한다. 그러나 [daily_ma_reaction.py](../../../src/lat5/daily_ma_reaction.py) 56-58행은 `score_daily_reaction`만 정의하고, [test_daily_ma_reaction.py](../../../tests/test_daily_ma_reaction.py) 4-7행도 그 이름을 사용해 계약 불일치를 숨긴다.
- 재현: `from lat5.daily_ma_reaction import score_daily_ma_reaction`은 `ImportError`가 났다.
- 영향: Task 1에서 약속한 import가 불가능하다. 단, 전체 계획의 Task 2 이후에는 `score_daily_reaction`도 사용하므로, 구현을 바꾸기 전에 계획 SSOT에서 어느 이름을 최종 API로 할지 확정해야 한다.

### MAJOR — `as_of`와 같은 날짜의 미완성 일봉을 포함해 no-lookahead 보장이 깨진다

- 근거: [daily_ma_reaction.py](../../../src/lat5/daily_ma_reaction.py) 70행의 `daily.index <= as_of`는 일봉 index가 자정이고 `as_of`가 장중 시각이면 당일 bar를 포함한다. 전체 계획 [2026-08-13-daily-ma-reaction-score.md](../../../docs/superpowers/plans/2026-08-13-daily-ma-reaction-score.md) 11-14행은 현재/미래 bar lookahead를 금지하고, 기존 [location_decision.py](../../../src/lat5/location_decision.py) 64-77 및 87행도 일봉은 `as_of` **이전** 행만 읽는 계약이다.
- 재현: 2026-08-09 자정 index의 미완성 close를 `10000`으로 둔 뒤 `as_of=2026-08-09 10:00`으로 호출하면 `SMA5=2053.2` (`KNOWN`)가 반환됐다. 당일을 제외한 완료 5개 close 평균은 `66.0`이다.
- 테스트 공백: [test_daily_ma_reaction.py](../../../tests/test_daily_ma_reaction.py) 42-52행은 다음 날짜(8/13)를 제외할 뿐, 같은 거래일 장중 경계를 검증하지 않는다.
- 필요 조치: `as_of`를 "평가일 시작"으로 정의해 엄격히 이전 행만 쓰거나, `as_of`가 완료 bar의 날짜라는 명시적 계약/검증을 추가해야 한다. 어느 쪽이든 장중 partial daily bar가 `KNOWN` 결과에 들어가지 않음을 테스트해야 한다.

### MAJOR — OHLCV는 컬럼 존재만 검사하고, 필수값 결측·비유한값은 `KNOWN`으로 통과한다

- 근거: [daily_ma_reaction.py](../../../src/lat5/daily_ma_reaction.py) 60-68행은 컬럼 이름만 검사한다. 이후 70-74행은 close만 SMA에 전달하며, [_sma](../../../src/lat5/daily_ma_reaction.py) 28-32행은 close의 `NaN`만 거르고 `inf`, 문자열/비수치, 그리고 open/high/low/volume 값은 검증하지 않는다. 이는 계획 [task-1-brief.md](task-1-brief.md) 8행의 completed OHLCV frame 및 32행의 필수 OHLCV/UNKNOWN 계약과 맞지 않는다.
- 재현: 마지막 완료 행의 `open`, `high`, `low`, 또는 `volume`을 각각 `NaN`으로 바꿔도 결과는 모두 `KNOWN`, `unknown_fields=()`였다. close를 `inf`로 바꾸면 `KNOWN`, `sma5=inf`가 반환됐다.
- 테스트 공백: [test_daily_ma_reaction.py](../../../tests/test_daily_ma_reaction.py) 55-61행은 `volume` 컬럼 삭제만 검증한다.
- 필요 조치: 완료 구간의 필수 OHLCV 값을 수치·유한값으로 검증하고, 부족/무효한 항목을 field name과 함께 `UNKNOWN`으로 반환해야 한다. close의 `NaN/inf/non-numeric`, non-close OHLCV 결측, 그리고 `as_of` 이전 구간만 검사하는 사례를 추가해야 한다.

### MINOR — 순서가 보장되지 않은 DatetimeIndex에서 SMA가 시간순 최근 값이 아니라 물리적 마지막 행으로 계산된다

- 근거: [daily_ma_reaction.py](../../../src/lat5/daily_ma_reaction.py) 70-74행은 필터 후 정렬하지 않고 `_sma(...tail(window))`를 호출한다. 저장소 loader는 [data.py](../../../src/lat5/data.py) 76-88행에서 정렬하지만, 이 모듈의 공개 DataFrame 계약 자체에는 정렬/DatetimeIndex 검증이 없다.
- 재현: 70개 일봉의 행 순서를 섞으면 결과는 `KNOWN`이지만 `SMA5=144.0`; 시간순 최근 5개 평균은 `167.0`이었다.
- 필요 조치: 입력을 시간순으로 정렬하거나 monotonic DatetimeIndex를 명시적으로 요구하고, 비정렬 입력의 동작을 테스트로 고정해야 한다.

## 긍정 사항

- 미래 날짜 행을 제외하는 기본 `as_of` 필터와 SMA5/20/60의 기간 부족 시 `UNKNOWN` 반환은 구현돼 있다.
- close의 `NaN`이 SMA 기간에 있으면 해당 SMA가 `UNKNOWN`이 되는 동작은 안전하다.
- 반응 감지, ATR/quality bonus, 기존 scorer 통합, 주문/알림/스케줄러 변경은 포함하지 않아 Task 1 코드 범위를 지켰다.

## 승인 조건

1. 계획의 함수명을 SSOT에서 하나로 확정하고 구현·테스트·후속 Task 호출을 일치시킨다.
2. 장중 `as_of`에서 same-day partial bar가 계산에 들어가지 않는 completed-bar 계약을 테스트로 증명한다.
3. 완료 구간의 OHLCV 결측/비수치/비유한값을 `UNKNOWN`으로 fail-closed 처리하고 테스트한다.
4. 비정렬 index 정책을 구현과 테스트에 고정한다.
