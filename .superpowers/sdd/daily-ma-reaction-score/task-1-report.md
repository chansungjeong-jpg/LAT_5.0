# Task 1 구현 보고서

## 구현 범위

completed daily bar만 `daily.index.normalize() < as_of.normalize()`로 필터링해 SMA5·SMA20·SMA60을 계산하는 순수 데이터 계약을 추가했다. `as_of`와 같은 날짜의 bar는 장중 partial 가능성이 있으므로 전체 제외한다.

- `DailyMAReactionInputs`: 일봉 DataFrame과 평가 시점 계약
- `DailyMAReaction`: 반응명, 기본 점수, 품질 보너스, 총점, SMA 값, 상태, 사유, unknown fields
- 필수 OHLCV 컬럼 또는 SMA 기간이 부족하면 `UNKNOWN`과 누락 필드를 반환
- 주문·알림·스케줄러 및 기존 통합 경로는 변경하지 않음

## 변경 파일

- `src/lat5/daily_ma_reaction.py`
- `tests/test_daily_ma_reaction.py`
- `.superpowers/sdd/daily-ma-reaction-score/task-1-report.md`

## TDD 및 검증 결과

### RED

실패 테스트를 먼저 실행했다.

```text
python -m pytest tests/test_daily_ma_reaction.py -q
ModuleNotFoundError: No module named 'lat5.daily_ma_reaction'
```

### GREEN

최소 구현 후 focused 테스트가 통과했다.

```text
python -m pytest tests/test_daily_ma_reaction.py -q
4 passed
```

### 전체 회귀

```text
python -m pytest -q
152 passed
```

Task 2 이후 범위인 SMA 반응 감지, ATR 기반 품질 보너스, golden-cross 보너스, 기존 scorer 통합은 구현하지 않았다.
## Reviewer follow-up

- The planned public API is now `score_daily_ma_reaction`. The original `score_daily_reaction` name remains as a compatibility alias.
- Completed-bar semantics are fail-closed and date-based: only rows whose normalized bar date is strictly earlier than `as_of.normalize()` are used. The entire `as_of` calendar date is excluded, including a same-day intraday partial bar.
- Every completed OHLCV field (`open`, `high`, `low`, `close`, `volume`) is converted to numeric and checked for finite values. Missing, non-numeric, `NaN`, and infinite values return `UNKNOWN` and include the affected field names in `unknown_fields`.
- Inputs must have a monotonic increasing `DatetimeIndex` without `NaT`. Non-datetime or unsorted indexes fail closed with `datetime_index` in `unknown_fields`.

### Reviewer follow-up TDD and regression results

RED after adding the review regression tests:

```text
python -m pytest tests/test_daily_ma_reaction.py -q
ImportError: cannot import name `score_daily_ma_reaction`
```

GREEN after the minimal contract hardening:

```text
python -m pytest tests/test_daily_ma_reaction.py -q
23 passed
```

Full regression:

```text
python -m pytest -q
171 passed
```
