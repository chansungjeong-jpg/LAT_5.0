# LAT SIMPLE v1.0 최종 설계도면

> 상태: 이 문서의 미확정·충돌 항목은 2026-08-09 합의본인
> 이 문서가 현재 LAT 5.0의 공식 SSOT이다. 구현과 백테스트는 이 문서를 기준으로 한다.

작성일: 2026-08-09  
목적: 너무 복잡하지 않은 구조로, 돈이 들어오는 섹터 안에서 확률 높은 눌림목 자리만 찾는다.

---

## 1. 최종 결론

LAT SIMPLE v1.0은 KOSPI·KOSDAQ 전체 시장 흐름에서 주도주를 발굴하고,
거래대금과 상승률로 순위를 정한 뒤, 선정된 주도주의 현재 위치를 판단한다.
`LAT_SIMPLE_v1.0_Watchlist.md`는 초기 기준 유니버스이자 결과 snapshot으로 사용한다.
```text
돈흐름
기준봉
눌림
이격도
손익비
```

최종 파이프라인은 아래와 같다.

```text
Core Watchlist
↓
KOSPI/KOSDAQ 주도주 발굴·랭킹
↓
주봉 추세·상승각도
↓
일봉 추세·최근 5거래일 양봉 수
↓
60분 EMA60/EMA120 위치·상승각도
↓
거래량·거래대금 점수
↓
이격도
↓
매물대 proxy·Risk Reward
↓
BUY / WATCH / REJECT
```

v1.0의 핵심은 정교한 예측이 아니라, 나쁜 자리와 추격매수를 걸러내는 것이다.

---

## 2. v1.0에서 제외하는 것

### 2.1 Probability Score 제외

현재 실제 승률 데이터가 충분하지 않으므로 Probability Score는 v1.0에서 제외한다.

```text
Probability 0.75
Probability 0.82
```

같은 수치는 검증 전에는 가짜 정밀도가 될 수 있다.

적용 시점:

```text
v1.0 제외
백테스트와 실전 샘플 누적 후 v1.5에서 재검토
```

### 2.2 Expected Value 제외

Expected Value는 승률과 평균 손익이 검증되어야 의미가 있다.

현재 단계에서는 EV 계산보다 다음 조건을 먼저 안정화한다.

```text
시장·섹터 돈흐름
주봉·일봉 추세
60분 위치·거래량
이격도 과열 차단
매물대·손익비
```

적용 시점:

```text
v1.0 제외
백테스트 후 v1.5에서 추가 검토
```

### 2.3 CONDITIONAL_BUY 제외

초기 버전에서는 판단 등급을 복잡하게 나누지 않는다.

최종 판단값은 3개만 사용한다.

```text
BUY
WATCH
REJECT
```

---

## 3. 대상 유니버스

초기 대상은 `Core Watchlist`로 시작하되, 운영 시 KOSPI·KOSDAQ 전체 종목의
시장 데이터를 사용해 주도주를 발굴하고 Watchlist를 갱신한다.

```text
LAT_SIMPLE_v1.0_Watchlist.md
```

주도주 발굴 대상은 KOSPI·KOSDAQ 전체 종목이다. KOSPI200과 KOSDAQ150은
초기 검증 범위로 사용할 수 있으나, 최종 발굴 범위는 운영 설정으로 결정한다.

주도주 Leader Score는 다음 비중으로 계산한다.

```text
거래대금 순위 60%
상승률 순위   40%
```

거래대금이 높고 상승률이 양수인 종목을 우선 후보로 삼는다. 상승률만 높고
거래대금이 부족한 종목은 주도주 확정이 아니라 WATCH 후보로 남긴다.

Watchlist에서도 다음 섹터는 제외한다.

```text
디스플레이
게임·콘텐츠
```

이유:

```text
단기 주도주 후보로 반복 검증하기에는 변동성, 테마성, 지속성 리스크가 크다.
```

처리 기준:

```text
거래대금과 상승률 조건을 충족한 종목을 주도주 후보로 평가한다.
Watchlist는 매일 또는 설정된 주기로 Leader Score 결과에 따라 갱신한다.
Watchlist 내 제외 섹터는 자동 BUY 후보에서 제외한다.
```

---

## 4.0. US Market Context

미국시장 정보는 무료·지연 일봉 데이터로 수집한다. 초기 공급원은
`yfinance` 어댑터로 한정하고, 수집 계층과 판정 계층을 분리한다.

기본 관측 대상:

| 구분 | 티커 | 역할 |
|---|---|---|
| S&P 500 | SPY | 미국 대형주 위험선호 방향 |
| Nasdaq 100 | QQQ | 성장주·기술주 위험선호 방향 |
| Dow Jones | DIA | 전통 대형주·방어 흐름 |
| Russell 2000 | IWM | 중소형주 위험선호 방향 |
| 변동성 | VIX | 시장 공포·위험 회피 확인 |
| 반도체 | SMH 또는 SOXX | 국내 반도체 섹터의 외부 나침반 |

운영 규칙:

1. 미국시장은 종목 점수에 직접 가산하지 않고 `Market Flow`의 보조 게이트로만 사용한다.
2. 한국장 평가 시점에는 가장 최근 미국장 마감 데이터만 사용한다.
3. 데이터가 없거나, 기준 시각보다 오래되었거나, 일부 핵심 지표가 누락되면 미국시장 상태를 `UNKNOWN`으로 기록한다.
4. `UNKNOWN` 상태에서는 신규 `BUY`를 만들지 않고 `WATCH` 또는 `REJECT`로 종료한다.
5. 공급원 변경을 위해 `provider`, `as_of`, `collected_at`, 원본 응답 식별자를 저장한다.
6. 무료·지연 데이터는 연구·백테스트·장 마감 후 판단용이며, 실시간 매매 데이터로 간주하지 않는다.

미국시장 상태는 다음 입력을 이용해 별도 계산한다.

```text
US Market Context
  -> SPY / QQQ / DIA / IWM 방향
  -> VIX 위험도
  -> SMH 또는 SOXX 반도체 방향
  -> Market Flow 보조 판정
```

---

## 4.1. US-to-KR Mapping

미국시장 정보는 미국 ETF 자체를 매매하는 신호가 아니라, 국내 주식의
시장·산업·주도주 후보를 선별하는 외부 방향성으로 매핑한다.

```text
미국 지표
  -> 산업/테마 매핑
  -> 국내 시장·섹터 후보
  -> 당일 KOSPI/KOSDAQ 주도주 랭킹과 교집합
  -> 국내 종목 위치 점수
```

초기 매핑 레지스트리:

| 미국 지표 | 국내 매핑 영역 | 국내 후보 예시 | 사용 규칙 |
|---|---|---|---|
| SMH / SOXX | 반도체·장비 | 삼성전자, SK하이닉스, 한미반도체 등 | 국내 주도주 랭킹과 교집합일 때 우선순위 상승 |
| QQQ | 성장주·기술·AI | 관련 국내 주도주 | 개별 종목이 아니라 섹터 후보 선별에 사용 |
| SPY | 대형주·시장 전반 | KOSPI 대형주 | KOSPI 시장 게이트와 함께 사용 |
| IWM | 중소형 성장주 | KOSDAQ 주도주 | KOSDAQ 시장 게이트와 함께 사용 |
| DIA | 경기민감·전통산업 | 산업재·금융·경기민감 주도주 | 섹터 후보 보조 판단 |
| VIX | 전체 국내 시장 위험도 | 국내 전체 종목 | 급등 시 신규 매수 차단 또는 WATCH |

매핑 원칙:

1. 표의 국내 후보 예시는 고정 매수 목록이 아니다. 실제 후보는 매일 KOSPI/KOSDAQ 거래대금·상승률 랭킹에서 재선정한다.
2. 미국 지표와 국내 섹터의 방향이 일치하고, 국내 주도주 랭킹에도 포함된 종목만 `US_ALIGNED`로 표시한다.
3. 미국 지표가 강해도 국내 거래대금과 상승률이 확인되지 않으면 BUY 근거로 사용할 수 없다.
4. 국내 주도주이더라도 미국 지표와 반대 방향이면 매수 점수 가산 없이 `US_MISMATCH`로 기록한다.
5. 미국 지표와 국내 섹터·종목의 연결 근거가 없는 경우 `UNKNOWN_MAPPING`으로 기록하고 자동 BUY를 금지한다.
6. 매핑 정보는 `mapping_version`, `us_symbol`, `kr_market`, `kr_sector`, `effective_from`, `effective_to`, `source`를 함께 보존한다.

기업 단위 대응 매핑 예시:

| 해외 기준 기업 | 국내 대응 주도주 | 매핑 영역 | 비고 |
|---|---|---|---|
| Micron Technology (`MU`) | SK하이닉스 (`000660`) | 메모리 반도체 | 미국 메모리 업황의 국내 대응 후보 |
| Seagate Technology (`STX`) | 삼성전자 (`005930`) | 저장장치·메모리 | 데이터센터 저장장치 수요의 국내 대형주 대응 후보 |
| Sunrun (`RUN`) | 한화솔루션 (`009830`) | 태양광·신재생 | 미국 주거용 태양광·분산형 에너지 흐름의 국내 대응 후보 |

미국 태양광 관측 유니버스:

| 세부 영역 | 미국 종목 |
|---|---|
| 태양광 모듈·발전 | First Solar (`FSLR`) |
| 주거용 태양광·분산형 에너지 | Sunrun (`RUN`) |
| 태양광 인버터·에너지 관리 | Enphase Energy (`ENPH`), SolarEdge (`SEDG`) |
| 태양광 추적·구조물 | Array Technologies (`ARRY`), Nextracker (`NXT`) |
| 태양광·배터리 종합 | Canadian Solar (`CSIQ`) |

미국 태양광 유니버스는 개별 종목 하나의 방향이 아니라 공통 상승 종목 수,
거래대금 가중 방향, 대표 종목의 추세를 집계해 `US_SOLAR_FLOW`로 만든다.

AI·전력기기·에너지 기업 매핑:

| 미국 기준 기업 | 티커 | 국내 대응 후보 | 매핑 영역 |
|---|---|---|---|
| NVIDIA | `NVDA` | SK하이닉스, 삼성전자, 한미반도체 | AI 가속기·HBM·반도체 장비 |
| Microsoft / Amazon | `MSFT` / `AMZN` | NAVER, 카카오, 삼성SDS | 클라우드·AI 서비스·데이터센터 |
| Vertiv | `VRT` | LS ELECTRIC, HD현대일렉트릭, 효성중공업 | 데이터센터 전력·냉각 인프라 |
| Eaton | `ETN` | LS ELECTRIC, HD현대일렉트릭 | 전력관리·배전·전력망 |
| GE Vernova | `GEV` | 두산에너빌리티, HD현대일렉트릭, 효성중공업 | 발전·터빈·전력망 |
| Constellation Energy | `CEG` | 두산에너빌리티, 한전기술 | 원전·안정적 전력 |
| NextEra Energy | `NEE` | 한화솔루션, 두산에너빌리티 | 신재생·발전 |
| Exxon Mobil / Chevron | `XOM` / `CVX` | S-Oil, SK이노베이션 | 정유·에너지 |
| Lockheed Martin / RTX | `LMT` / `RTX` | 한화에어로스페이스, LIG넥스원, 한국항공우주 | 방산·항공우주·유도무기 |
| Eli Lilly / Vertex | `LLY` / `VRTX` | 삼성바이오로직스, 셀트리온, SK바이오팜 | 신약·바이오 |
| Tesla / Albemarle | `TSLA` / `ALB` | LG에너지솔루션, 삼성SDI, SK이노베이션 | 전기차·리튬·배터리 |
| Fluence Energy | `FLNC` | LG에너지솔루션, 삼성SDI, LS ELECTRIC | 전력저장장치·배터리 시스템 |

추가 플로우:

```text
US_DEFENSE_FLOW
US_BIOTECH_FLOW
US_BATTERY_FLOW
```

미국 10년물 국채금리(`US10Y`)는 섹터 플로우가 아니라 `US Market Flow`의
최상위 금리·유동성 변수로 취급한다.

```text
US10Y 상승 급격
  -> 성장주·바이오·2차전지 밸류에이션 부담
  -> Market 상태 보수화

US10Y 안정 또는 하락
  -> 위험자산 평가 환경 개선 가능
  -> 단, 국내 거래대금·상승률 확인 필요
```

금리 방향만으로 BUY하지 않는다. `US10Y` 데이터가 없거나 오래된 경우
Market Context를 `UNKNOWN`으로 기록하고 신규 BUY를 차단한다.

AI·전력기기·에너지 흐름은 별도 플로우로 집계한다.

```text
US_AI_FLOW
US_POWER_EQUIPMENT_FLOW
US_ENERGY_FLOW
  -> 미국 기준 기업 상승률·거래대금·추세 집계
  -> 국내 대응 후보의 시장·섹터 매핑
  -> KOSPI/KOSDAQ 주도주 랭킹과 교집합
  -> 종목 위치 점수
```

이 매핑은 동종기업 확정이 아니라 `reference_company` 관계다. 국내 후보가
당일 거래대금·상승률 주도주가 아니면 매수 후보로 승격하지 않는다.

기업 매핑은 1:1 동종기업 확정이 아니라 `reference_company` 관계다. 해외 기업의
주가 상승만으로 국내 대응 종목을 매수하지 않으며, 국내 거래대금·상승률 주도주
랭킹과 국내 종목 위치 점수를 함께 통과해야 한다.

```text
해외 기준 기업 상승
  -> 국내 대응 후보 탐색
  -> 국내 거래대금·상승률 확인
  -> 국내 섹터 흐름 확인
  -> 위치 점수 및 Hard Block 확인
  -> BUY / WATCH / REJECT
```

최종 반영은 다음처럼 제한한다.

```text
미국시장 방향성 = 보조 게이트
국내 시장·섹터 흐름 = 우선 게이트
국내 주도주 랭킹 = 후보 확정
종목 위치 점수 = 진입 위치 판단
```

---

## 4. Market Gate

시장 상태가 매수 가능한 환경인지 먼저 확인한다.
Market Flow는 KOSPI와 KOSDAQ 중 자금이 어디로 이동하는지 알려주는 최상위
나침반이며, 시장별 주도주 발굴의 범위와 우선순위를 결정한다.

통과 조건:

```text
Market = BUY
또는
Market = SELECTIVE_BUY
```

차단 조건:

```text
Market = REJECT
또는
Market = RISK_OFF
```

판단:

| Market 상태 | 판단 |
|---|---|
| BUY | Core Watchlist 전체의 위치 평가 가능 |
| SELECTIVE_BUY | 자금이 유입되는 시장·섹터의 Watchlist만 우선 평가 |
| WATCH | 신규 BUY 금지, 관찰 |
| REJECT / RISK_OFF | 신규 BUY 금지 |

---

## 5. Sector Flow Gate

섹터에 돈이 들어오는지 확인한다.
Sector Flow는 발굴된 주도주가 속한 섹터 중 어느 섹터로 자금이 이동하는지
알려주는 두 번째 나침반이며, 주도주 순위와 위치 평가의 우선순위를 조정한다.

최종 기준:

```text
Sector Score >= 60
```

판단표:

| Sector Score | 판단 |
|---:|---|
| 70 이상 | 강함 |
| 60~69 | 가능 |
| 60 미만 | 제외 |

설계 의도:

```text
70점 이상만 기다리면 신호가 너무 적을 수 있다.
60점 이상부터는 후보로 열어두되, 종목 조건과 자리 조건으로 한 번 더 거른다.
```

---

## 6. Leader / Core Watchlist Gate

주도주 선정은 KOSPI·KOSDAQ 전체 종목의 거래대금·상승률 랭킹으로 수행한다.
선정 결과는 Core Watchlist snapshot으로 저장하고 이전 snapshot과 비교한다.

통과 조건:

```text
Leader Score 기준을 통과한 종목
```

제외 조건:

```text
Leader Score 기준 미달 종목
제외 섹터 종목
```

판단:

| 종목 상태 | 판단 |
|---|---|
| Leader Score 통과 | Core Watchlist 편입 후 위치 평가 |
| Leader Score 하락 | WATCH 또는 Watchlist 제외 |
| Leader Score 미달 | 평가하지 않음 |
| 제외 섹터 | 자동 BUY 후보 제외 |

---

## 7. Anchor Gate

기준봉은 돈이 실제로 들어온 흔적이다.

통과 조건:

```text
Anchor 발생
```

Anchor의 의미:

```text
평소보다 강한 거래대금
의미 있는 상승 캔들
섹터 돈흐름과 같은 방향
이후 눌림을 기다릴 기준점 제공
```

판단:

| Anchor 상태 | 판단 |
|---|---|
| 명확한 기준봉 있음 | 다음 단계 진행 |
| 기준봉 약함 | WATCH |
| 기준봉 없음 | REJECT |

---

## 8. Trend Gate

일봉 추세가 무너진 종목은 제외한다.

통과 조건:

```text
Daily Trend OK
```

Trend OK의 의미:

```text
일봉상 하락 추세가 아니어야 한다.
기준봉 이후 구조가 유지되어야 한다.
중요 지지선을 심하게 이탈하지 않아야 한다.
```

판단:

| 일봉 추세 | 판단 |
|---|---|
| 상승 / 회복 / 유지 | 통과 |
| 애매함 | WATCH |
| 하락 / 붕괴 | REJECT |

---

## 9. 위치 점수 Gate

v1.0의 핵심은 패턴 이름이 아니라 주봉·일봉·60분봉 기준의 위치와 거래량이다.
ABC 패턴은 공식 매수 조건에서 폐기하며, 기존 ABC 코드는 과거 비교용으로만 보존한다.

총점은 100점이다.

| 구성 요소 | 배점 |
|---|---:|
| 거래량·거래대금 | 30 |
| 60분 EMA60/EMA120 위치 | 20 |
| 일봉 SMA5/SMA20/SMA60 대표반응 | 20 |
| 주봉 추세 | 10 |
| 일봉 추세 지속성 | 5 |
| 상승각도 | 10 |
| 최근 5거래일 양봉 수 | 5 |

거래량은 가장 높은 점수 비중을 가진다. 일봉 거래대금은 최소 유동성 확인용
Hard Block으로 사용하고, 60분 거래량은 최근 20개 완료 봉 평균 대비 비율로
점수화한다.

상승각도는 가격 단위에 의존하는 기하학적 각도가 아니라 EMA의 정규화된
변화율로 계산한다.

```text
정규화 상승각도 = (현재 EMA - 기준 EMA) / 기준 EMA
```

판단:

| 위치 점수 상태 | 판단 |
|---|---|
| 추세·위치·거래량이 양호 | 다음 단계 진행 |
| 점수는 양호하지만 이격·매물대가 불리함 | WATCH |
| 추세 붕괴·필수 데이터 누락·RR 미달 | REJECT |

### 9.1 일봉 SMA 반응 점수 계약

일봉 위치 점수는 완료된 일봉만 사용하여 SMA5·SMA20·SMA60의 반응을 하나의
대표반응으로 기록한다. 같은 봉에서 여러 반응이 성립해도 기본 점수는 중복 합산하지
않으며, 아래 우선순위에서 가장 높은 하나만 채택한다.

| 우선순위 | 대표반응 | 기본 점수 |
|---:|---|---:|
| 1 | `SMA60_UPWARD_CROSS_STRONG_BULL` — 전일 종가가 SMA60 이하, 당일 종가가 SMA60 초과이며 강한 양봉 마감 | +10 |
| 2 | `SMA20_PULLBACK_RECOVERY` — 저가가 SMA20의 0.25 ATR 이내이고 SMA20 위 양봉 마감 | +8 |
| 3 | `SMA20_CLOSE_BREAK` — 전일 종가가 SMA20 이상이고 당일 종가가 SMA20 아래 | -8 |
| 4 | `SMA5_RECOVERY` — 전일 종가가 SMA5 아래이고 당일 종가가 SMA5 이상 | +6 |
| 5 | `SMA5_HOLD` — 당일 종가가 SMA5 이상을 유지 | +3 |
| 6 | `SMA5_CLOSE_BREAK` — 전일 종가가 SMA5 이상이고 당일 종가가 SMA5 아래 | -4 |
| 7 | `NONE` — 위 반응 없음 | 0 |

품질 보너스는 해당 완료 일봉의 반응 품질과 함께 계산하며, 합계의 상한은 항상
`min(20, 기본 점수 + 품질 보너스)`다. 보너스는 강한 몸통 +3, 고가 부근 마감 +2,
반응 SMA 상승 기울기 +3, SMA20의 SMA60 상향 골든크로스 +2다. 골든크로스는 독립
매수 신호나 별도 위치점수 구성요소가 아니며 이 품질 보너스로만 반영한다.
대표반응이 `NONE`이면 캔들 품질이나 골든크로스가 성립해도 품질 보너스는 0이다.

SMA5 이탈은 Hard Block이 아니다. 장중 저가만 SMA5 아래이고 종가가 회복하면 이탈
감점을 적용하지 않는다. 종가 이탈은 -4점과 WATCH 압력으로 남기고, 다음 완료 일봉이
SMA5를 회복하면 `SMA5_RECOVERY` +6으로 재평가한다.

SMA20 종가 이탈은 `DAILY_MA_HARD_BLOCK`으로 BUY 계열 판정을 차단한다. 일봉 반응이
`UNKNOWN`이거나 점수·필수 입력이 누락된 경우에는 `DAILY_MA_REACTION_UNKNOWN`과
구체적인 `unknown_fields`를 남기고 BUY 계열 판정을 차단한다. `five_day_state`는 대표
반응 이름을 복사하지 않고 현재 종가의 SMA5 유지·이탈·회복 상태를 별도로 기록한다.

평가 시점 `as_of`에는 그 이전에 완료된 일봉만 사용한다. `as_of` 당일 봉, 미완료 봉,
미래 봉은 SMA·ATR·품질·반응 계산에 사용하지 않는다. 필요한 OHLCV/SMA/ATR 데이터가
부족하면 반응은 `UNKNOWN`, 점수는 0으로 기록하며 BUY 근거로 대체하지 않는다.

---

## 10. 이격도 Gate

이격도는 점수화하지 않는다.

역할:

```text
과열 진입 방지 필터
추격매수 차단 필터
```

### 10.1 5분봉 이격도

진입 타점의 과열 여부를 확인한다.

계산식:

```text
5분 이격도 = 현재가 / 5분 20EMA - 1
```

최종 기준:

```text
5분 20EMA 대비 +3% 이하 통과
5분 20EMA 대비 +3% 초과 시 신규 BUY 금지
```

판단:

| 5분 20EMA 이격도 | 판단 |
|---:|---|
| +3% 이하 | 매수 가능 |
| +3% 초과 | WATCH / 추격매수 금지 |

### 10.2 일봉 이격도

종목 전체의 과열 여부를 확인한다.

계산식:

```text
일봉 이격도 = 현재가 / 일봉 10EMA - 1
```

최종 기준:

```text
일봉 10EMA 대비 +10% 이하 통과
일봉 10EMA 대비 +10% 초과 시 WATCH
```

판단:

| 일봉 10EMA 이격도 | 판단 |
|---:|---|
| +10% 이하 | 정상 |
| +10% 초과 | WATCH / 과열 주의 |

최종 이격도 처리:

```text
이격도 좋음 → 통과
이격도 과열 → BUY 금지 또는 WATCH
```

---

## 11. Risk Reward Gate

손익비는 최종 매수 가능 여부를 결정하는 핵심 조건이다.

최종 기준:

```text
RR >= 1.5
```

판단표:

| RR | 판단 |
|---:|---|
| 2.0 이상 | A급 BUY |
| 1.5~2.0 | BUY 가능 |
| 1.5 미만 | REJECT |

설계 의도:

```text
RR 2.0 이상은 선호 조건
RR 1.5 이상은 실전 최소 조건
RR 1.5 미만은 좋은 종목이어도 좋은 자리가 아니다
```

---

## 12. 최종 BUY 조건

아래 조건을 모두 만족해야 BUY다.

```text
Market = BUY 또는 SELECTIVE_BUY
AND Sector Score >= 60
AND Core Watchlist 종목
AND Anchor 또는 유효한 거래량 신호
AND Weekly/Daily Trend OK
AND 60분 EMA60/EMA120 위치 조건 충족
AND 공식 위치 점수 기준 충족
AND 5분 20EMA 이격도 <= +3%
AND 일봉 10EMA 이격도 <= +10%
AND RR >= 1.5
→ BUY
```

A급 BUY 조건:

```text
위 조건을 모두 만족
AND Sector Score >= 70
AND RR >= 2.0
→ A급 BUY
```

---

## 13. WATCH 조건

좋은 종목이지만 아직 좋은 자리가 아니면 WATCH다.

WATCH 예시:

```text
Market은 괜찮지만 Sector Score가 60 근처
추세와 거래량은 강하지만 60분 위치가 아직 애매함
60분 위치는 좋지만 상단 매물대가 가까움
5분 이격도 +3% 초과
일봉 이격도 +10% 초과
RR이 1.5에 근접하지만 아직 부족
제외 섹터지만 단기 관찰 필요
```

WATCH의 의미:

```text
지금 사지 않는다.
조건이 다시 정렬될 때까지 기다린다.
```

---

## 14. REJECT 조건

아래 중 하나라도 해당하면 REJECT다.

```text
Market = REJECT 또는 RISK_OFF
Sector Score < 60
Core Watchlist 종목이 아님
유효한 거래량 신호 없음
Daily Trend 붕괴
주봉 또는 일봉 추세 붕괴
60분 EMA120 하향 구조
RR < 1.5
Core Watchlist 제외 섹터에서 자동 BUY 후보로 들어온 경우
```

REJECT의 의미:

```text
좋은 종목일 수는 있어도 LAT SIMPLE v1.0의 매수 자리는 아니다.
```

---

## 15. 판단 우선순위

우선순위는 아래 순서로 둔다.

```text
1. Market
2. Sector Flow
3. Core Watchlist
4. 주봉·일봉 추세
5. 60분 위치
6. 거래량
7. 이격도
8. 매물대
9. RR
10. BUY / WATCH / REJECT
```

중요 원칙:

```text
앞단 조건이 무너지면 뒷단 계산을 과하게 하지 않는다.
```

예:

```text
Sector Score < 60이면 이격도와 RR이 좋아도 REJECT
거래량·추세·위치가 없으면 RR이 좋아도 WATCH 또는 REJECT
이격도가 과열이면 좋은 종목이어도 BUY 금지
RR < 1.5이면 모든 조건이 좋아도 REJECT
```

---

## 16. 데이터 부족 시 처리

데이터가 없거나 계산할 수 없으면 통과로 보지 않는다.

기본 원칙:

```text
확인 불가 = BUY 금지
```

처리:

| 누락 데이터 | 판단 |
|---|---|
| Market 상태 없음 | WATCH 또는 REJECT |
| Sector Score 없음 | REJECT |
| 5분봉 데이터 없음 | WATCH |
| 일봉 EMA 계산 불가 | WATCH |
| RR 계산 불가 | REJECT |

설계 의도:

```text
모르는 상태에서 사지 않는다.
확인된 자리만 매수한다.
```

---

## 17. v1.0 출력 포맷

각 후보 종목은 최소한 아래 정보를 출력한다.

```text
symbol
name
market_state
sector_name
sector_score
leader_or_watchlist
anchor_status
daily_trend_status
weekly_trend_status
daily_trend_status
recent_5d_bullish_count
m60_location_score
volume_score
slope_score
daily_ma_reaction.reaction
daily_ma_reaction.base_score
daily_ma_reaction.quality_bonus
daily_ma_reaction.quality_reasons
daily_ma_reaction.sma5
daily_ma_reaction.sma20
daily_ma_reaction.sma60
daily_ma_reaction.five_day_state
minute_ema20_gap_pct
daily_ema10_gap_pct
distance_state
supply_zone_method
rr_breakdown
rr
final_state
reason
```

`daily_ma_reaction`은 대표반응·기본점수·품질 보너스/근거·SMA값·5일선 상태를
직렬화한 위치결정 필드다. `volume_score`는 위치 점수의 최대 30점 구성요소이며,
`distance_state`는 점수 가산이 아니라 과열 Hard Block/WATCH 상태다. `rr_breakdown`은
현재가·손절가·목표가·기대손실·기대보상·RR과 `supply_zone_method`를 포함할 수 있다.

현 런타임이 산출하지 않는 값(예: 실제 Volume Profile 매물대)은 임의 숫자로 채우지
않는다. `UNKNOWN`/`null`과 원인 필드로 남기며, 현재 매물대는 `swing_high_proxy_v1`
같이 실제 사용한 방법이 있을 때만 표시한다. 범용 CLI 기술기준선 보고서는 위치결정
payload를 받지 않으면 위 세부 필드를 만들어 출력하지 않는다.

예시:

```text
decision = BUY
reason = Weekly/Daily trend OK, 60m EMA location strong, volume score 27, 5m gap 1.8%, daily gap 6.5%, RR 1.8
```

```text
decision = WATCH
reason = Trend and volume strong, but 5m gap 3.6% exceeds chase limit
```

```text
decision = REJECT
reason = RR 1.2 below minimum 1.5
```

---

## 18. v1.5 이후 확장 후보

v1.0에서 충분한 백테스트와 실전 샘플이 쌓이면 아래를 검토한다.

```text
Probability Score
Expected Value
섹터별 최적 이격도
종목군별 RR 기준 차등화
장세별 BUY 기준 조정
```

단, v1.5에서도 원칙은 유지한다.

```text
복잡한 시스템보다
실제로 돈이 들어오는 자리와 손익비가 좋은 자리만 남긴다.
```

---

## 19. 최종 한 줄 정의

```text
LAT SIMPLE v1.0
= Trend + Volume + 60m Location + Daily SMA Reaction + 이격도 + Supply Proxy + RR
```

최종 목적:

```text
뇌동매매를 막고,
돈이 들어오는 섹터에서,
대장주 또는 관심주만 고르고,
기준봉 이후 첫 눌림에서,
과열되지 않은 자리와 손익비 1.5 이상만 매수한다.
```
