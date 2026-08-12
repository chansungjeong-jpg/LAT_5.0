# Task 3 보고서 — 일봉 반응 품질 보너스

## 범위

- 기준 HEAD: `d5d102a`
- 변경: `src/lat5/daily_ma_reaction.py`, `tests/test_daily_ma_reaction.py`
- 미변경: Task 4 `location_score` 통합, 주문, 알림, 브로커, 스케줄러

## 구현

`DailyMAReaction` 결과에 `quality_components`, `quality_reasons`,
`quality_method`를 추가하고 다음 품질 보너스를 계산한다.

| 컴포넌트 | 조건 | 점수 |
|---|---|---:|
| `strong_body` | 양봉 body, ATR 정규화 비율 `>= 0.8`, 최근 20개 완료 body의 `p80` 이상 | +3 |
| `close_near_high` | `(close-low)/(high-low) >= 0.70` | +2 |
| `reaction_slope_up` | 선택된 대표 반응 SMA의 현재값이 전일보다 큼 | +3 |
| `golden_cross` | 전일 `SMA20 <= SMA60`이고 당일 `SMA20 > SMA60` | +2 |

최근 20개 body percentile 산정 방식은 결과의
`quality_method="body_atr_ratio_and_recent_20_body_p80"`로 보존한다.
기존 대표 반응 우선순위와 base score는 유지하며, 최종 점수는
`min(20, base_score + quality_bonus)`로 제한한다.

## TDD 검증

### RED

- `quality_reasons`가 아직 없는 상태에서 strong-body 테스트를 먼저 실행했다.
- 결과: 기존 테스트 `39 passed`, 신규 테스트 `1 failed`
- 실패 원인: `DailyMAReaction`에 `quality_reasons`가 없어 기능 부재를 검출
- 이후 나머지 품질 테스트를 추가하고 구현 전 실행했으며, 기존 `41 passed`, 신규 `3 failed`로 각 미구현 컴포넌트를 확인했다.

### GREEN 및 회귀

```text
python -m pytest tests/test_daily_ma_reaction.py -q
47 passed

python -m pytest -q
195 passed

python -m compileall -q src tests
exit 0

git diff --check
clean
```

추가한 경계 검증:

- close position 정확히 `0.70`은 통과, 그 아래는 미통과
- 골든크로스는 현재 `SMA20 > SMA60`일 때만 통과
- 모든 품질 조건이 함께 계산돼도 total score는 `20`을 초과하지 않음

## 커밋

`feat: add daily ma reaction quality bonuses`
