# LAT 5.0 Claude 인수인계

작성일: 2026-08-16 (Asia/Seoul)
작업 디렉터리: `C:\trading_system\LAT_5.0`

## 인수인계 목적

LAT 5.0의 월봉 10선·주봉 5선 회복 우선 필터와 60분 추세선/이평 돌파 스코어링 파이프라인을 이어서 검증한다. 현재는 실주문 연동이 아니라 관찰·리포트 생성 범위이며, 데이터 건강성이 통과되기 전에는 후속 필터링을 실행하지 않는 fail-closed 구조다.

## 반드시 먼저 읽을 문서

- 공식 설계 SSOT: `LAT_SIMPLE_v1_0_final_spec.md`
- 역사 문서: `SSOT_CORE.md` (현재 의사결정의 SSOT로 사용하지 말 것)
- 최신 건강성 결과: `reports/data_health_latest.md`, `artifacts/data_health_latest.json`
- 최신 일일 파이프라인 로그: `reports/daily_pipeline/2026-08-15.log`
- 손상 행 백업: `reports/data_health/invalid_ohlcv_000720_19860329.json`

## 현재 구현 상태

### 1. 1차 필터

`scripts/filter_monthly10_weekly5.py`가 Core Watchlist의 중복 제거 종목 약 154개를 대상으로 다음을 순서대로 적용한다.

1. 월봉 SMA10 최근 회복
2. 주봉 SMA5 최근 회복
3. 현재 종가가 해당 이동평균 위에 있는지 확인

회복은 최근 3개 봉 안의 상향 돌파를 허용한다. 현재 진행 중인 월봉·주봉은 `잠정`으로 표시한다. 이 필터가 후속 60분 신호보다 무조건 먼저 실행되어야 한다.

관련 코드:

- `src/lat5/monthly_weekly_filter.py`
- `scripts/filter_monthly10_weekly5.py`
- `tests/test_monthly_weekly_filter.py`

삼성SDI(`006400`) 누락 문제를 실제 DB의 주봉·월봉 값으로 재검증한 뒤 회복 판정을 `recent_recovery`로 수정했고, 현재 필터 결과에는 포함된다.

### 2. 60분 돌파와 스코어링

- `src/lat5/trendline_breakout.py`
- `src/lat5/trendline_scoring.py`
- `scripts/scan_trendline_rank.py`

월봉·주봉 1차 필터 통과 종목에 대해서만 60분 추세선, EMA60/EMA120, 거래량 조건을 확인하고 이격도·매물대 여유·상위 시간 프레임을 점수화한다. 과도한 이격과 매물대 근접은 Hard Block이다.

기존 DB 기준으로 1차 필터 29종목, 60분 신호 3종목, Hard Block 후 최종 선정 0종목이었다. 이 숫자는 기준일과 데이터가 갱신되므로 현재 결과로 간주하지 말고 건강성 통과 후 재실행해야 한다.

### 3. 일일 자동화

`scripts/run_daily_signal_reports.py` 실행 순서:

1. 전체 수집
2. data-health
3. 월봉10·주봉5 회복 필터
4. 추세선/이평 돌파 랭킹

어느 단계라도 비정상 종료하면 다음 단계로 넘어가지 않는다. Windows 작업 스케줄러 작업은 다음과 같다.

- 작업명: `LAT5_Monthly10_Weekly5_Recovery`
- 실행: 매일 16:00
- 상태 확인 당시: `Ready`

## 최근 데이터 건강성 사건

`ohlcv_daily`에서 다음 원천 행이 비정상이었다.

- provider: `kiwoom`
- ticker: `000720`
- date: `1986-03-29`
- 원인: `high < low`
- 원천 API 재수집(run 10)에서도 동일한 값이 재현됨

조치:

- 원본 값은 `reports/data_health/invalid_ohlcv_000720_19860329.json`에 백업
- 해당 키의 행 1건만 DB에서 삭제
- `src/lat5/collector.py`에 OHLC 양수 및 `high >= low` 검증 추가
- 관련 회귀 테스트 추가

현재 상태:

- `data_integrity_ok`: `true`
- `invalid_ohlcv_rows`: `0`
- 일봉/5분봉/외국인 수급 커버리지: 154/154
- 체결강도 커버리지: 153/154
- 전체 health: `FAIL`

실패 이유는 데이터 손상이 아니라 마지막 수집 run 10이 보정용 단일 종목 수집이기 때문이다. run 10은 `COMPLETE`지만 `watchlist_count=1`, 전체 워치리스트는 154종목이므로 전체 수집 완료로 인정하지 않는다. 이 검증은 `src/lat5/data_health.py`의 `latest_collection_scope_ok`와 `latest_collection_complete`가 담당한다.

## 다음 작업 순서

1. 전체 154종목 수집을 실행하거나 다음 예약 실행 결과를 확인한다.
2. 최신 run의 조건을 확인한다.
   - `status=COMPLETE`
   - `watchlist_count >= 154`
   - `success_count >= 154`
   - `error_count=0`
3. data-health가 `PASS`인지 확인한다.
4. `run_daily_signal_reports.py`를 실행해 월봉·주봉 필터와 랭킹 결과를 기준일과 함께 재생성한다.
5. 삼성SDI(`006400`), 오토에버(`307950`), 현대무벡스(`319400`)가 실제 OHLC 기준으로 포함/제외된 이유를 결과 행에서 다시 검증한다.
6. 결과가 0종목이면 임의로 조건을 완화하지 말고 Hard Block 사유를 보고한다.

권장 확인 명령:

```powershell
Set-Location C:\trading_system\LAT_5.0
$env:PYTHONPATH='src'
python -m lat5.cli data-health --db data\lat5_market.db --watchlist LAT_SIMPLE_v1.0_Watchlist.md --output-dir .
python scripts\run_daily_signal_reports.py --as-of 2026-08-16
pytest -q
python -m compileall -q src scripts tests
schtasks /Query /TN LAT5_Monthly10_Weekly5_Recovery /FO LIST /V
```

`--skip-collect`는 기존 DB에 대한 로컬 파이프라인 검증용이다. 최신 전체 수집이 확인되지 않은 상태에서 결과를 최신 신호로 보고하지 말 것.

## 안전 규칙

- `.env`, 토큰 캐시, API 키를 열람·복사·문서화하지 말 것.
- 실주문, 예약주문, 알림 발송을 추가하거나 활성화하지 말 것.
- 데이터가 불완전하면 `UNKNOWN/FAIL/BLOCKED`로 남기고 후속 선정을 실행하지 말 것.
- 월봉10선과 주봉5선 회복은 선택 조건이 아니라 1차 필수 조건이다.
- EOD 데이터와 장중 데이터를 같은 기준일의 점수처럼 비교하지 말 것.
- DB 정정 시 먼저 원본을 백업하고, provider·ticker·date 등 정확한 키를 확인한 뒤 최소 범위만 수정할 것.

## 검증된 현재 기준

- 전체 테스트: `268 passed`
- compileall: 통과
- OHLCV 잘못된 행: `0`
- 최신 파이프라인 상태: data-health 단계에서 의도적으로 `BLOCKED`

## 추천 스킬

- `diagnose`: 전체 수집 및 health 실패 원인 재현
- `engineering:testing-strategy`: 수집·필터·랭킹 회귀 검증 설계
- `engineering:documentation`: SSOT 및 인수인계 문서 갱신
- `superpowers:verification-before-completion`: 완료 주장 전 증거 재검증
- `superpowers:systematic-debugging`: 원천 API의 비정상 OHLC 재발 시 재현·격리

## 인수인계 완료 조건

다음 에이전트는 최신 전체 수집 run과 data-health 결과를 직접 확인한 후에만 “정상 완료”라고 보고한다. 단순히 테스트 통과나 이전 리포트 존재만으로 최신 데이터 정상이라고 판단하지 않는다.
