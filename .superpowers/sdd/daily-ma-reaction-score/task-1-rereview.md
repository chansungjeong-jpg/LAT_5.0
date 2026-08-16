# Task 1 수정 커밋 재리뷰 — `655b1b0..873c1a1`

## 결론

**변경 요청 (MAJOR 1).** 이전 MAJOR 3건과 MINOR 1건은 모두 해결됐다. 그러나 중복된 일봉 날짜가 `KNOWN` SMA와 60-bar 충족으로 계산될 수 있어, 손상되거나 중복 수집된 입력에서 반응 점수를 신뢰할 수 없다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| focused | `python -m pytest tests/test_daily_ma_reaction.py -q` → **23 passed** |
| 전체 회귀 | `python -m pytest -q` → **171 passed** |
| 컴파일 | `python -m compileall -q src` → **pass** |
| diff whitespace | `git diff --check 655b1b0 873c1a1` 및 `git diff --check 7866790 873c1a1` → **clean** |

## 이전 지적 해결 여부

| 기존 지적 | 판정 | 근거 |
|---|---|---|
| `score_daily_ma_reaction` 공개 API | 해결 | [daily_ma_reaction.py](../../../src/lat5/daily_ma_reaction.py:98)가 계획상의 이름으로 정의되고, [line 161](../../../src/lat5/daily_ma_reaction.py:161)의 기존 이름은 호환 alias다. [테스트 lines 43-51](../../../tests/test_daily_ma_reaction.py:43)가 import 및 alias 동치를 검증한다. |
| same-day partial bar lookahead 차단 | 해결 | [lines 70-76](../../../src/lat5/daily_ma_reaction.py:70)가 `normalize() < as_of.normalize()`만 선택하므로 평가일 전체를 제외한다. [테스트 lines 54-65](../../../tests/test_daily_ma_reaction.py:54)가 같은 날짜의 `10_000` close를 SMA에서 제외함을 검증한다. |
| finite OHLCV 필수값 검증 | 해결 | [lines 82-95](../../../src/lat5/daily_ma_reaction.py:82)가 completed 구간의 모든 OHLCV를 numeric·finite로 검증하고, [lines 121-128](../../../src/lat5/daily_ma_reaction.py:121)가 불량 field로 `UNKNOWN`을 반환한다. [테스트 lines 77-87](../../../tests/test_daily_ma_reaction.py:77)는 5개 필드 각각의 `None`/`NaN`/`inf`를 확인한다. |
| 비정렬 `DatetimeIndex` 처리 | 해결 | [lines 65-68](../../../src/lat5/daily_ma_reaction.py:65)가 non-datetime, `NaT`, 비단조 인덱스를 fail-closed 처리한다. [테스트 lines 102-118](../../../tests/test_daily_ma_reaction.py:102)가 non-datetime 및 역순 인덱스를 고정한다. |

## 발견 사항

### MAJOR — 중복된 완료 일봉 날짜가 60개 완료 bar로 계산된다

- 근거: [daily_ma_reaction.py lines 65-68](../../../src/lat5/daily_ma_reaction.py:65)는 `DatetimeIndex`가 단조 증가인지만 확인한다. 따라서 중복 timestamp 또는 서로 다른 시각이지만 같은 거래일로 normalize되는 행을 거부하지 않는다. 이후 [lines 74-76](../../../src/lat5/daily_ma_reaction.py:74)가 모두 completed rows로 포함하고, [lines 130-133](../../../src/lat5/daily_ma_reaction.py:130)가 행 수 기준으로 SMA5/20/60을 계산한다.
- 재현: 동일한 2026-06-01 일봉 1개를 60회 복제한 frame은 `index.is_monotonic_increasing=True`, `index.is_unique=False`이며, `score_daily_ma_reaction(frame, Timestamp("2026-06-02"))`가 `status="KNOWN"`, `sma60=100.0`을 반환했다. 실제 완료 거래일은 1일뿐이므로 `UNKNOWN`이어야 한다.
- 영향: 중복 수집/병합 데이터가 최소 60 거래일 요건을 인위적으로 충족시키고 SMA 및 이후 Task 2 반응 점수를 왜곡한다. Task 1의 completed **daily** bar 계약과 fail-closed 원칙을 위반한다.
- 요청 조치: completed input에 대해 날짜 단위 고유성을 검증해야 한다. 현재 date-based filtering과 일관되게 `daily.index.normalize().is_unique`를 요구하고, 실패 시 `UNKNOWN`/`datetime_index`를 반환한다. 동일 timestamp 중복과 동일 날짜의 서로 다른 시각 중복을 각각 회귀 테스트로 고정한다.
- 테스트 공백: [tests/test_daily_ma_reaction.py lines 102-118](../../../tests/test_daily_ma_reaction.py:102)는 비-DatetimeIndex와 역순만 검사하며 중복 timestamp/date를 검사하지 않는다.

## 긍정 확인

- 미래 행의 불량 OHLCV는 완료 구간 밖이면 계산을 막지 않고, 완료 구간의 불량 OHLCV만 fail-closed 한다([테스트 lines 90-99](../../../tests/test_daily_ma_reaction.py:90)).
- 873c1a1은 public API, no-lookahead, finite OHLCV, 정렬 검증에 국한되어 주문·알림·스케줄러·기존 통합 경로를 건드리지 않았다.

## 최종 판정

**Request changes.** 기존 4개 지적은 해소됐으나, 날짜 중복 입력을 `UNKNOWN`으로 막고 해당 회귀 테스트를 추가한 뒤 재리뷰가 필요하다.
