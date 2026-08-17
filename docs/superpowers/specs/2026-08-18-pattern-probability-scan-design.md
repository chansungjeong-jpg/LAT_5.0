# 종목별 패턴 확률 스캐너 v1 설계

작성일: 2026-08-18

## 1. 목적

"돌파 후 며칠 뒤 재진입"이 통계적으로 신뢰 가능한 우위인지, 종목마다 즉흥
백테스트를 매번 손으로 돌리지 않고도 판정할 수 있게 한다. 판정은 표본외
검증과 유의성 문턱값을 통과한 경우에만 `PASS`로 표시하며, 그 결과조차
실행 신호가 아니라 관찰 강화 후보로만 취급한다.

계기: 2026-08-17 현대무벡스(319400)를 대상으로 1회성 스크래치 백테스트를
돌려 n=41, 승률 58.5%(5일)/53.7%(10일)를 확인했다. 이를 재사용 가능한
도구로 승격한다.

## 2. 기본 원칙

- 패턴 정의는 결과를 보기 전에 고정한다. 사후 파라미터 조정을 하지 않는다.
- 표본외(OOS) 검증을 통과하지 못한 결과는 표시하되 `PASS`로 부르지 않는다.
- 최소 표본수 미달은 `UNKNOWN`(`INSUFFICIENT_SAMPLE`)으로 남기고 임의
  판정하지 않는다.
- 거래비용·슬리피지·과거 시점 Watchlist 재구성은 v1 범위에서 제외한다
  (아래 6장에 명시).
- 이 스캐너의 출력은 매수 신호가 아니다. Watchlist 포함이 매수 가능이 아닌
  것과 같은 원칙이다.

## 3. 패턴 정의 (v1, 1개 고정)

```text
돌파일: 당일 수익률 >= +7% AND 당일 거래량 >= 직전 20일 평균 거래량 x 2
진입: 돌파일 기준 +3거래일 종가
청산: 진입일 기준 +5거래일 종가, 그리고 별도로 +10거래일 종가 (둘 다 계산)
수익률 = 청산가 / 진입가 - 1
```

향후 다른 패턴을 추가하려면 새 스펙 문서를 별도로 작성한다(이 문서는
이 패턴 하나만 다룬다).

## 4. 아키텍처

### 4.1 `src/lat5/pattern_probability.py` (순수 함수, DB 비의존)

- `find_breakout_events(daily: pd.DataFrame) -> pd.DataFrame`
  일봉 OHLCV 프레임에서 돌파일 인덱스를 찾는다. 열: `date`, `pos`.
- `compute_forward_returns(daily, events, *, entry_offset=3, hold_days=(5, 10)) -> pd.DataFrame`
  이벤트마다 진입일과 각 보유기간의 수익률을 계산한다. 특정 보유기간의
  청산일이 프레임 끝을 넘으면 그 열만 `NaN`으로 남기고 행 자체는 버리지
  않는다(5일 창은 계산 가능해도 10일 창은 데이터 부족일 수 있어 두 창의
  표본 집합이 다를 수 있음 — 4.1 `WindowStats` 참고). 열: `breakout_date`,
  `entry_date`, `ret_5`, `ret_10`.
- `split_oos(events: pd.DataFrame, *, cutoff_frac=0.7) -> tuple[DataFrame, DataFrame]`
  `breakout_date` 오름차순 정렬 후 이벤트 개수 기준(행 인덱스)으로 앞 70%를
  학습, 뒤 30%를 검증으로 나눈다. 달력 기간 기준 70/30이 아니다 — 이벤트가
  시간에 걸쳐 고르게 분포하지 않아 기간 기준으로 자르면 학습/검증 표본수가
  한쪽으로 쏠릴 수 있기 때문이다.
- `t_stat(returns: pd.Series) -> float`
  단일표본 t검정(귀무가설: 평균수익률=0), `mean / (std(ddof=1) / sqrt(n))`으로
  직접 계산한다. `scipy`는 설치돼 있지만 `src/lat5`의 다른 모듈이 쓰지
  않는 의존성이라 이 모듈도 추가하지 않는다.
- `evaluate_ticker(daily: pd.DataFrame, *, min_n=30, t_threshold=1.99) -> TickerVerdict`
  위 함수들을 조합해 종목 하나를 판정한다.

```python
@dataclass(frozen=True)
class TickerVerdict:
    ticker: str
    verdict: str  # PASS | PARTIAL | FAIL | INSUFFICIENT_SAMPLE
    hold_5: WindowStats
    hold_10: WindowStats

@dataclass(frozen=True)
class WindowStats:
    n_train: int
    n_test: int
    t_train: float | None
    t_test: float | None
    win_rate_train: float | None
    win_rate_test: float | None
    avg_return_train: float | None
    avg_return_test: float | None
    sufficient_sample: bool  # n_train>=min_n AND n_test>=min_n
    passed: bool  # sufficient_sample AND t_train>=threshold AND t_test>=threshold
```

`n_train`/`n_test`는 5일 보유와 10일 보유 창에서 각각 따로 집계한다. 10일
청산은 5일 청산보다 더 먼 미래 데이터가 필요해 최근 이벤트 일부가 10일
창에서만 미래 데이터 부족으로 빠질 수 있기 때문이다(같은 이벤트 집합이
아닐 수 있음).

### 4.2 판정 로직

```text
NOT hold_5.sufficient_sample OR NOT hold_10.sufficient_sample
  -> INSUFFICIENT_SAMPLE

hold_5.passed AND hold_10.passed
  -> PASS

hold_5.passed XOR hold_10.passed
  -> PARTIAL

그 외
  -> FAIL
```

5일·10일 보유 중 하나만 통과해도 `PASS`로 부르지 않는 이유: 그 자체가
"두 문 중 하나만 열리면 통과"인 다중검정이기 때문이다. 오늘 무벡스 사례도
5일 보유만 봤다면 성급히 통과시켰을 수 있다.

### 4.3 `scripts/pattern_probability_scan.py`

Watchlist 154종목을 순회하며 `evaluate_ticker`를 호출하고
`reports/pattern_probability/{as_of}.md`에 표로 기록한다. 표 열: 코드,
종목명, 판정, n_train, n_test, t_train(5일/10일), t_test(5일/10일),
승률(train/test, 5일/10일).

CLI: `--db`, `--watchlist`, `--as-of` (기존 `filter_monthly10_weekly5.py`
등과 동일한 인자 규약).

독립 스크립트로만 존재한다. `run_daily_signal_reports.py` 등 일일
파이프라인에는 편입하지 않는다 — 이력 재수집이 없는 날은 결과가 동일해
매일 돌릴 이유가 없다.

### 4.4 테스트

`tests/test_pattern_probability.py` — 합성 OHLCV 프레임(고정 fixture)으로
아래를 검증한다. 실제 DB에 의존하지 않는다.

- `find_breakout_events`가 정확히 조건에 맞는 날만 찾는지
- `compute_forward_returns`가 미래 데이터 부족한 이벤트를 올바르게 제외하는지
- `split_oos`가 시간순으로 정확히 70/30 분할하는지
- `t_stat`이 알려진 분포에 대해 올바른 값을 내는지
- `evaluate_ticker`가 표본수 미달/PASS/PARTIAL/FAIL 네 경로를 모두 정확히
  판정하는지 (합성 데이터로 각 케이스 구성)

## 5. 데이터 흐름

```text
ohlcv_daily(전체 이력, 종목별)
  -> find_breakout_events
  -> compute_forward_returns
  -> split_oos
  -> t_stat(train), t_stat(test)  [5일/10일 각각]
  -> evaluate_ticker
  -> reports/pattern_probability/{as_of}.md
```

## 6. v1 범위 제외 (명시적 caveat)

- **거래비용·슬리피지**: raw 종가 수익률만 사용한다. 기존 `backtest.py`의
  비용 엔진과는 다른 숫자다.
- **과거 시점 Watchlist 재구성**: 현재 154종목 구성을 전체 이력에 소급
  적용한다. 생존편향이 있을 수 있다.
- **다중검정 전역 보정(Bonferroni 등)**: 154종목을 동시에 검정하지만
  종목별 개별 t-threshold(1.99)만 적용하고 전역 오탐률은 보정하지 않는다.
  X-trading `gun_shot_decl` 판별과 동일한 기준선을 유지하기 위함이다. 이
  때문에 `PASS`로 나온 종목이라도 실행 신호로 쓰지 않는다는 원칙(1장)이
  더 중요해진다.

## 7. 에러 처리

- 종목의 일봉 이력이 40행 미만이면(`find_breakout_events`가 20일 이동평균
  거래량을 계산할 수 없음) `INSUFFICIENT_SAMPLE`로 기록하고 스킵한다.
- 이벤트가 0건이면 `INSUFFICIENT_SAMPLE`.
- DB 연결 실패 등은 스크립트 레벨에서 기존 스크립트들과 동일하게 즉시
  비정상 종료한다(fail-closed, 임의 기본값 대체 없음).
