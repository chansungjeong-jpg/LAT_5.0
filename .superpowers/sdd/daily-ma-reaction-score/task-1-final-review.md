# Task 1 최종 리뷰

검토일: 2026-08-13  
검토 대상: `task-1-brief.md`, `review-655b1b0..8a393fc.diff`, `task-1-rereview.md`

## 최종 판정

**PASS** — 심각한 잔여 문제 없음.

## 중복 날짜/타임스탬프 fail-closed 검증

`src/lat5/daily_ma_reaction.py`의 완료 구간은 `as_of`의 calendar date보다 이전인 행만 포함한다. 그 완료 구간에서 `index.normalize().duplicated()`가 하나라도 발견되면 `datetime_index`를 `unknown_fields`에 넣고 `status="UNKNOWN"`, `reaction="UNKNOWN"`, 모든 점수 0인 결과를 반환한다.

따라서 다음 두 입력 모두 fail-closed로 처리된다.

- 같은 날짜의 서로 다른 timestamp 2개
- 동일한 daily timestamp 중복

전용 회귀 테스트 2개가 각각 `UNKNOWN`과 `datetime_index`를 검증하며, 독립 수동 확인도 `UNKNOWN ('datetime_index',)`를 반환했다. `as_of` 날짜의 partial bar나 미래 행은 완료 구간 밖이므로 중복 검사의 대상이 아니며, 해당 날짜를 계산에서 제외하는 기존 no-lookahead 계약과 일치한다.

## 기존 재리뷰 지적 해결 여부

기존 재리뷰의 잔여 MAJOR였던 완료 일봉 날짜 중복 문제는 해결됐다. 그보다 앞선 지적도 모두 해결됐다.

| 지적 | 최종 확인 |
|---|---|
| 계획된 `score_daily_ma_reaction` 공개 API 부재 | 함수가 공개되고, 기존 `score_daily_reaction`은 호환 alias이며 alias 동치 테스트가 있다. |
| same-day partial bar lookahead | `as_of.normalize()`와 같은 날짜를 제외해 SMA가 평가일 bar를 사용하지 않는다. |
| 필수 OHLCV의 결측·비수치·비유한값 통과 | 완료 구간의 5개 OHLCV를 numeric·finite 검증하고 불량 field를 `UNKNOWN`에 기록한다. |
| 비정렬/non-datetime index 처리 | non-datetime, `NaT`, 비단조 index를 `datetime_index`로 fail-closed 처리한다. |
| 완료 구간의 중복 날짜/timestamp | 날짜 단위 중복 guard와 두 종류의 회귀 테스트가 추가됐다. |

## 새로 실행한 검증

- `python -m pytest tests/test_daily_ma_reaction.py -q` → **25 passed**
- `python -m pytest -q` → **173 passed**
- `python -m compileall -q src tests` → **pass**
- `git diff --check 655b1b0..HEAD` → **clean**
- 중복 날짜 수동 호출 → `UNKNOWN ('datetime_index',)`

## 범위 확인

`655b1b0..HEAD`의 변경 파일은 구현 보고서, `src/lat5/daily_ma_reaction.py`, `tests/test_daily_ma_reaction.py`뿐이다. Task 1의 순수 일봉 데이터 계약·SMA 계산·입력 검증과 전용 테스트 범위에 머물렀고, Task 2 이후의 반응 감지·ATR 품질 보너스·golden-cross 보너스·기존 scorer 통합 및 주문/알림/스케줄러 변경은 포함되지 않았다.

결론적으로 중복 입력은 관련 완료 구간에서 fail-closed `UNKNOWN`이며, 앞선 지적은 모두 해결됐고 테스트 및 변경 범위도 Task 1에 부합한다.
