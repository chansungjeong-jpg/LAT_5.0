# LAT SIMPLE v1.0 리팩토링 명세서 (v2 — 실제 코드 기준 정정판)

## Watchlist Position Finder

작성일: 2026-08-09 (v1) / 개정: 2026-08-09 (v2)
개정 사유: v1은 `probability_engine`, `expected_value_engine`, `Config Loader`, `Telegram`,
`Trade Journal` 등 실제 `src/lat5/`에 존재하지 않는 모듈을 대상으로 작성됨. v2는 실제
코드(`src/lat5/*.py`, 26개 테스트 1,586줄, `data/lat5_market.db`)를 직접 조회해 정정.
상세 근거: 코드 리뷰 아티팩트 참조.

목적: 기존 LAT 코드를 전면 재작성하지 않고, 기존 데이터 수집/백테스트/저널 구조를 유지한
상태에서 **전략 판단부 앞단에 Watchlist 좋은 위치 찾기 필터**를 추가한다.

---

## 1. 최종 목표 (변경 없음)

```text
좋은 종목인가?  X
좋은 종목이 지금 좋은 위치인가?  O
```

LAT는 전 종목 스캐너가 아니다. 이미 선별된 Core Watchlist(154종목, `LAT_SIMPLE_v1.0_Watchlist.md`)
종목이 거래량·눌림·이격도·매물대·손익비 기준상 좋은 위치에 왔는지 판단한다.

---

## 2. 아키텍처 결정 — v1과 다른 핵심 변경

v1은 Location Score 결과를 **그 자체로 매수 신호**처럼 다뤘다 (§13에 `holding_days`,
§14에 "WATCH_HIGH가 다음날 BUY_READY 전환 시 진입"). 이는 현재 백테스트 엔진과 정면 충돌한다:
`backtest.py`의 4개 runner(`run_technical_baseline`, `run_hourly_breakout_baseline`,
`run_hourly_abc_support_baseline`, `run_hourly_pullback_reversal_baseline`)는 전부
**당일 5분봉 루프 안에서만 동작**하고, EOD 강제청산·14:30 진입컷·종목당 1일 1거래
제약을 갖는 인트라데이 전용 구조다 (예: `hourly_abc_support.py:232` `simulate_pullback_reversal_trade`).
"멀티데이 스윙 보유"를 전제하면 청산부 전면 재작성이 필요해지고, 이는 "기존 백테스트
엔진을 최대한 유지한다"는 원칙(§원 문서 §2)과 충돌한다.

**v2 결정: Location Score는 독립 전략이 아니라, 기존 인트라데이 엔진의 상류(upstream)
일일 필터다.**

```text
[매일 장전]
Core Watchlist (154종목)
  ↓ evaluate_watchlist_position() — 일봉/이격/거래량/매물대 기준 점수
BUY_READY / WATCH_HIGH / WATCH / IGNORE  (+ reasons, wait_for)
  ↓ BUY_READY(및 옵션: WATCH_HIGH) 종목만 통과
[장중, 기존 엔진 그대로]
run_hourly_pullback_reversal_baseline() 등 — 실제 진입/손절/청산 타이밍 결정
```

이 결정으로:

- 기존 백테스트/체결 시뮬레이션 코드는 **한 줄도 안 바꾼다** (원 원칙 §2 실제로 성립).
- "보유 기간" 개념이 Location Score에는 없다 — 하루 단위로 재평가되는 필터일 뿐이고,
  실제 포지션의 보유/청산은 기존 엔진이 갖고 있는 룰(1R 절반청산, 2R, EMA20 이탈,
  60분 시간청산, EOD)을 그대로 따른다.
- WATCH_HIGH는 "매수 후보 오늘 대기, 내일도 재평가" 의미로 재정의한다. "다음날 자동
  진입" 같은 표현은 제거한다.

---

## 3. 실제 코드 인벤토리 (v1 §3/§4 대체)

v1 §3("유지")·§4("제거")는 실제 코드와 대응이 안 됐다. 실측 기준 3분류로 재작성.

### 3-1. 그대로 유지 (실존, 무변경)

```text
src/lat5/data.py             — KiwoomDataStore, parse_watchlist, aggregate_60m, daily_ema_context
src/lat5/patterns.py         — confirmed_pivots, build_rising_channel, ABC 탐지
src/lat5/hourly_breakout.py  — 60분 MA/OR 돌파 시뮬
src/lat5/hourly_abc_support.py — 강한 돌파 + ABC/MA60 눌림 + 5분 반전 진입 시뮬
src/lat5/paper.py            — size_position, paper_entry_fill/exit_fill, PaperLedger(SQLite)
src/lat5/backtest.py         — 4개 runner, summarize_trades
src/lat5/collector.py, collector_store.py, kiwoom_client.py,
  lat_credentials.py, lat_token_provider.py, token_provider.py — 수집 파이프라인
src/lat5/cli.py              — backtest/collect/data-health 서브커맨드
src/lat5/data_health.py      — 데이터 건강 리포트
```

`scoring.py`(daily_trend, 섹터 점수 유틸)는 존재하지만 `backtest.py`가 `daily_trend` 하나만
쓰고 섹터 점수 함수(`classify_sector` 등)는 **어디에도 연결돼 있지 않다** — 이번 작업에서
연결하되, §4의 게이트 방식 변경 참조.

### 3-2. 신규 개발 (v1이 "유지"로 잘못 분류한 것)

```text
Config Loader     — 없음. PyYAML이 pyproject.toml 의존성에도 없음.
                    v1의 yaml 예시는 그대로 못 씀 → §12 참조(dataclass로 대체)
Telegram 알림      — 없음. 이번 스코프 밖(§14에서 제외)
Trade Journal      — 별도 테이블 없음. paper.py의 `decisions` 테이블
                    (timestamp/ticker/sector/decision/reason/strategy_id/
                    algorithm_version/inputs_json)이 가장 근접 — §10 참조
매물대(Volume Profile) — 없음. 신규 구현 필요(§8-7)
```

### 3-3. 판단부 seam 추출 (신규 모듈, 이번 작업 핵심)

```text
src/lat5/location_decision.py   — 신규. evaluate_watchlist_position(ctx, cfg)
```

경로 정정: v1의 `lat/decision/location_decision.py`는 존재하지 않는 패키지 이름(`lat`) —
실제 패키지는 `src/lat5/`.

---

## 4. Sector Flow 게이트 — v1과 다른 처리

`execution_strength` 테이블 실측: **2026-08-07 하루치, 2종목, 792행뿐** — 과거 시계열 없음.
`investor_flow`는 2종목만 커버. 섹터 성립 요건(멤버 ≥3, Core Watchlist 커버리지 ≥70%)을
충족하는 섹터가 현재 데이터로는 **하나도 없다**.

**v1 §8-2("Sector Score < 60 → 즉시 IGNORE")를 그대로 넣으면 전 종목이 IGNORE된다.**

v2 처리:

```text
Phase 0 (현재, 데이터 부족)
  sector_score = UNKNOWN
  섹터는 감점하되 하드 IGNORE는 걸지 않음 (score_lower만 사용, 0점 처리)
  reasons에 "섹터 데이터 부족" 명시

Phase 1 (execution_strength/investor_flow 시계열 축적 후, 사용자 판정)
  scoring.classify_sector() 연결, §8-2 하드게이트 활성화
```

---

## 5. 최종 판단 흐름 (변경 없음, 위치만 명확화)

```text
[일 1회, 장전 실행]
Core Watchlist
↓
Sector Flow (Phase 0: 통과, 감점만)
↓
Daily / 60m Trend
↓
Daily Candle Strength
↓
Volume
↓
Pullback Position
↓
Distance
↓
Supply Zone / Risk Reward
↓
BUY_READY / WATCH_HIGH / WATCH / IGNORE
  ↓ (BUY_READY만, 옵션으로 WATCH_HIGH도)
[기존 인트라데이 엔진 — 무변경]
run_hourly_pullback_reversal_baseline() 등
```

---

## 6. 최종 상태값 (변경 없음)

| 상태 | 의미 | 행동 |
|---|---|---|
| `BUY_READY` | 좋은 위치 도달 | 오늘 인트라데이 엔진 스캔 대상에 포함 |
| `WATCH_HIGH` | 좋은 위치에 가까움 | 집중 감시, 내일 재평가 |
| `WATCH` | 종목은 보되 아직 멀다 | 관찰만, 스캔 제외 |
| `IGNORE` | 조건 부족 | 제외 |

---

## 7. Location Score 100점 + Veto 캡 (v1 버그 3건 수정)

v1 §11 예시 코드를 실제로 계산해보면 §8이 "0점/REJECT" 또는 "BUY 금지"라고 명시한
케이스가 전부 80점 이상 BUY_READY로 새는 것을 확인했다:

| 버그 | 점수 계산 | v1 결과 | §8 규정 |
|---|---|---|---|
| 눌림 없이 급등 | 15+15+25+**0**+15+10=80 | BUY_READY | 0점/WATCH |
| RR < 1.5 | 15+15+25+20+15+**0**=90 | BUY_READY | 0점/REJECT |
| 이격도 과열 | 15+15+25+20+**0**+10=85 | BUY_READY | BUY 금지 |

원인: 점수는 감산식(항목별 0점)일 뿐 **다른 항목이 만점이면 상쇄된다.** §8의 "REJECT/금지"
문구는 점수 산식에 반영된 적이 없다.

**v2 수정: 점수 계산과 별개로 veto 캡을 점수 이후에 적용한다.**

```text
veto = pullback_position == "없음(급등)"  → state는 최대 WATCH
veto = rr < 1.5                          → state는 최대 IGNORE (REJECT급)
veto = distance overheated (과열)         → state는 최대 WATCH
veto = watchlist_ok == False             → state는 강제 IGNORE
veto = sector_score known and < 60 (Phase 1만) → 강제 IGNORE

state = min(score_threshold_state, veto_cap_state)
```

점수표(가중치)는 v1과 동일:

| 항목 | 점수 | 역할 |
|---|---:|---|
| 섹터 돈흐름 | 15점 | 해당 섹터에 돈이 들어오는가 (Phase 0: 미적용시 0점 처리, veto 없음) |
| 추세 | 15점 | 일봉/60분 추세가 살아 있는가 |
| 거래량 | 25점 | 진짜 수급이 들어왔는가 |
| 눌림 위치 | 20점 | 좋은 매수 위치인가 (0점 시 WATCH 캡 veto) |
| 이격도 | 15점 | 추격매수 위험이 낮은가 (과열 시 WATCH 캡 veto) |
| 매물대/손익비 | 10점 | 위로 먹을 공간이 있는가 (RR<1.5 시 IGNORE 캡 veto) |

판정 기준(캡 적용 후):

```text
80점 이상  → BUY_READY
60~79점   → WATCH_HIGH
40~59점   → WATCH
40점 미만 → IGNORE
```

---

## 8. 세부 규칙 (v1과 대부분 동일, veto 명시만 추가)

### 8-1. Watchlist 조건

```text
watchlist_ok = True  (아니면 강제 IGNORE)
```

### 8-2. Sector Flow

Phase 0(현재): 게이트 없음, 감점만. Phase 1(데이터 축적 후):

```text
Sector Score >= 70 → 15점
Sector Score >= 60 → 10점
Sector Score < 60  → 0점 + IGNORE veto
```

### 8-3. Daily / 60분 추세 (v1과 동일)

| 항목 | 점수 |
|---|---:|
| 일봉 10EMA 위 | 5점 |
| 60분 추세 회복 | 5점 |
| 일봉 양봉 개수 | 5점 |

기준: 일봉 10EMA 위 또는 회복 중, 60분 20EMA/60EMA 위 회복, 최근 5일 양봉 3개 이상,
최근 10일 양봉 5개 이상. 실측(005930/000660, 232일): 10EMA 위 70.7%/69.4%,
양봉5≥3 53.0%/67.2%, 양봉10≥5 60.8%/80.2% — 단독 조건으로는 흔함, 필터력은 조합에서 나옴.

### 8-4. 거래량 규칙 (v1과 동일, 25점)

```text
증가(기준봉) → 감소(눌림) → 증가(돌파)
```

매수 금지 패턴은 veto로 처리(§7):

```text
가격 돌파 + 거래량 없음 → 눌림 위치 0점 → WATCH 캡
눌림인데 거래량 증가    → 거래량 점수 손실만(veto 없음, 점수로 자연 배제)
장대 윗꼬리 + 거래량 폭증 → 매도 물량 가능성 → reasons에 경고만 기록(v1 미정의 처리 보완)
```

### 8-5. 눌림 위치 (v1과 동일, 20점 + veto)

```text
20EMA 부근 지지 확인 → 20점
눌림 진행 중         → 10점
눌림 없이 급등        → 0점 + WATCH 캡 veto
```

실측: 60분 EMA20 근접 눌림 발생률 53.9%/47.8% (005930/000660).

### 8-6. 이격도 (v1과 동일, 15점 + veto)

```text
5분 20EMA 이격도 <= +3%   일봉 10EMA 이격도 <= +10%  → 15점
약간 부담                                            → 7점
과열                                                 → 0점 + WATCH 캡 veto
```

### 8-7. 매물대 / 손익비 (v1과 동일 정의, 구현 신규 + veto)

키움 REST OHLCV로 Volume Profile 추정 매물대 계산 — **신규 구현**(§3-2).

```text
RR >= 2.0 + 위 매물대 멀다 → 10점
RR >= 1.5                 → 6점
RR < 1.5                  → 0점 + IGNORE 캡 veto
```

---

## 9. BUY_READY 조건 요약 (§7 점수+veto의 결과 — 별도 AND 게이트 아님)

v1은 §7(점수제)과 §9(AND 게이트)가 병렬로 존재해 정본이 불명확했다. v2는 **§7 점수+veto가
유일한 판정 로직**이고, 아래는 그 결과를 사람이 읽기 쉽게 요약한 것일 뿐이다(별도 구현 없음).

```text
Watchlist 종목 AND Sector veto 없음 AND 눌림 veto 없음 AND
이격도 veto 없음 AND RR veto 없음 AND 캡 적용 후 점수 >= 80
→ BUY_READY
```

---

## 10. Trade Journal 매핑 (v1 §13 대체 — 신규 테이블 대신 기존 확장)

`paper.py`의 `decisions` 테이블(§3-1)이 이미 timestamp/ticker/sector/decision/reason/
strategy_id/algorithm_version/inputs_json을 갖는다. v1처럼 신규 테이블을 만들지 않고
`inputs_json`에 Location Score 내역을 실어보낸다:

```json
{
  "location_score": 72,
  "sector_score": "UNKNOWN",
  "trend_score": 10,
  "volume_score": 21,
  "pullback_score": 20,
  "distance_score": 15,
  "rr_score": 6,
  "vetoes": [],
  "reasons": ["거래량 증가", "단기 추세 회복"],
  "wait_for": ["105,000~108,000 눌림 지지"]
}
```

`decision` 컬럼에는 `BUY_READY`/`WATCH_HIGH`/`WATCH`/`IGNORE`를 그대로 쓴다(기존 BUY/WATCH/
REJECT 3단계 대신 4단계로 확장 — `decisions` 테이블은 `decision TEXT`라 스키마 변경 불필요).
WATCH_HIGH/WATCH/IGNORE도 매 평가일 기록해야 사후 검증(§원 문서 §13 질문들: "거래량 점수
높은 종목이 실제로 잘 갔는가" 등)이 가능하다.

---

## 11. 데이터 현실과 단계적 롤아웃 (v1에 없던 신규 섹션)

```text
Core Watchlist: 154종목 (20개 섹터)
5분봉 보유:     2종목 (005930, 000660), 232일 (2025-08-26~2026-08-07)
일봉 보유:      2종목 (005930: 10,904행, 000660: 7,391행)
체결강도:       2종목, 1일치(2026-08-07)뿐
외국인 수급:    2종목, 2018년부터(가장 풍부)
```

```text
Phase 0 (현재) — 2종목 파일럿
  location_decision.py 유닛 테스트로 검증(합성 ctx, TDD)
  005930/000660만 실데이터 evaluate, Sector veto OFF
  기존 hourly-pullback-reversal과 나란히 돌려 필터 전/후 거래 수 비교

Phase 1 — 154종목 수집
  collector.py로 전 종목 5분봉/일봉/체결강도/외국인 수급 확보
  data-health로 커버리지 확인 후 Sector veto ON

Phase 2 — 백테스트 정식 채택
  BUY_READY만 실제 진입, WATCH_HIGH는 기록만 (원 문서 §14 유지)
LAT_SIMPLE_v1_0_final_spec.md의 "Backtest Honesty" 준수: 체결강도 과거치 없으면 기술 베이스라인으로 표기
```

---

## 12. Config (v1 YAML 예시 대체 — 신규 의존성 없이)

`pyproject.toml`에 PyYAML이 없다. YAML을 새로 들이지 않고 기존 코드 스타일(`BacktestConfig`
frozen dataclass, `backtest.py:27`)을 따른다:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LocationScoreWeights:
    sector_flow: int = 15
    trend: int = 15
    volume: int = 25
    pullback_position: int = 20
    distance: int = 15
    rr_supply: int = 10


@dataclass(frozen=True)
class LocationScoreConfig:
    buy_ready: int = 80
    watch_high: int = 60
    watch: int = 40
    weights: LocationScoreWeights = field(default_factory=LocationScoreWeights)
    sector_min_score: int = 60
    sector_strong_score: int = 70
    sector_gate_enabled: bool = False  # Phase 0: False, Phase 1: True
    daily_ema: int = 10
    m60_ema_fast: int = 20
    m60_ema_slow: int = 60
    recent_5_days_min_bullish: int = 3
    recent_10_days_min_bullish: int = 5
    anchor_volume_ratio: float = 1.5
    breakout_volume_ratio: float = 1.2
    pullback_volume_dry_ratio: float = 0.8
    m5_ema20_max_pct: float = 0.03
    m5_ema20_warning_pct: float = 0.05
    daily_ema10_max_pct: float = 0.10
    daily_ema10_warning_pct: float = 0.12
    min_rr: float = 1.5
    good_rr: float = 2.0
    supply_zone_lookback_days: int = 20
```

YAML이 필요해지면(예: 운영 중 파라미터 튜닝을 코드 배포 없이 하고 싶을 때) 그때 PyYAML을
`pyproject.toml`에 추가하는 별도 작업으로 분리한다.

---

## 13. 신규 핵심 파일

```text
src/lat5/location_decision.py
```

핵심 함수 (경로만 정정, 시그니처는 v1과 동일):

```python
def evaluate_watchlist_position(ctx: dict, cfg: LocationScoreConfig) -> dict:
    """
    Watchlist 종목의 현재 위치를 평가한다.

    Returns:
        {
            "symbol": str,
            "state": "BUY_READY" | "WATCH_HIGH" | "WATCH" | "IGNORE",
            "location_score": int,
            "vetoes": list[str],
            "reasons": list[str],
            "wait_for": list[str],
        }
    """
```

`ctx`의 각 필드가 `None`이면(LAT_SIMPLE_v1_0_final_spec.md의 "데이터 부족 시 처리" 원칙)
해당 항목은 0점 처리하되 `reasons`가 아니라 별도 `unknown_fields`에 기록한다 — v1처럼
결측을 조용히 False로 강등하지 않는다(원 문서 §11 코드의 `ctx.get("anchor_volume_ok")`
패턴 금지).

---

## 14. Decision Engine 예시 구조 (v1 §11 버그 3건 수정판)

```python
def make_location_decision(ctx: dict, cfg: LocationScoreConfig) -> dict:
    score = 0
    reasons: list[str] = []
    wait_for: list[str] = []
    vetoes: list[str] = []
    unknown_fields: list[str] = []

    def _get(key: str) -> object | None:
        value = ctx.get(key)
        if value is None:
            unknown_fields.append(key)
        return value

    if not ctx.get("watchlist_ok", False):
        return {
            "state": "IGNORE", "location_score": 0, "vetoes": ["NOT_ON_WATCHLIST"],
            "reasons": ["Watchlist 제외 종목"], "wait_for": [], "unknown_fields": [],
        }

    sector_score = _get("sector_score")
    if cfg.sector_gate_enabled and sector_score is not None and sector_score < cfg.sector_min_score:
        return {
            "state": "IGNORE", "location_score": 0, "vetoes": ["SECTOR_WEAK"],
            "reasons": ["섹터 돈흐름 약함"], "wait_for": ["Sector Score 60 이상 회복"],
            "unknown_fields": unknown_fields,
        }
    if sector_score is not None:
        if sector_score >= cfg.sector_strong_score:
            score += 15; reasons.append("섹터 돈흐름 강함")
        elif sector_score >= cfg.sector_min_score:
            score += 10; reasons.append("섹터 돈흐름 보통 이상")

    if ctx.get("daily_trend_ok"):
        score += 5; reasons.append("일봉 추세 양호")
    else:
        wait_for.append("일봉 10EMA 회복")
    if ctx.get("m60_trend_ok"):
        score += 5; reasons.append("60분 추세 회복")
    else:
        wait_for.append("60분 추세 회복")
    if ctx.get("daily_bull_count_ok"):
        score += 5; reasons.append("일봉 양봉 개수 양호")
    else:
        wait_for.append("일봉 양봉 개수 회복")

    if ctx.get("anchor_volume_ok"):
        score += 8; reasons.append("기준봉 거래량 증가")
    if ctx.get("pullback_volume_dry"):
        score += 6; reasons.append("눌림 거래량 감소")
    if ctx.get("breakout_volume_ok"):
        score += 7; reasons.append("돌파 거래량 증가")
    else:
        wait_for.append("돌파 거래량 증가 확인")
    if ctx.get("bullish_candle_strength_ok"):
        score += 4; reasons.append("양봉 지속성 양호")

    pullback_state = ctx.get("pullback_state")  # "near_ema20" | "in_progress" | "none"
    if pullback_state == "near_ema20":
        score += 20; reasons.append("20EMA 부근 눌림 위치")
    elif pullback_state == "in_progress":
        score += 10; reasons.append("눌림 진행 중")
        wait_for.append("20EMA 지지 확인")
    else:
        wait_for.append("눌림 위치 대기")
        vetoes.append("NO_PULLBACK")  # v1 버그#1 수정: WATCH 캡

    m5_dist = ctx.get("m5_ema20_distance_pct", 999)
    daily_dist = ctx.get("daily_ema10_distance_pct", 999)
    if m5_dist <= cfg.m5_ema20_max_pct and daily_dist <= cfg.daily_ema10_max_pct:
        score += 15; reasons.append("이격도 정상")
    elif m5_dist <= cfg.m5_ema20_warning_pct and daily_dist <= cfg.daily_ema10_warning_pct:
        score += 7; reasons.append("이격도 약간 부담")
        wait_for.append("이격도 축소")
    else:
        wait_for.append("과열 해소 대기")
        vetoes.append("OVERHEATED")  # v1 버그#3 수정: WATCH 캡

    rr = ctx.get("rr", 0)
    overhead_supply_close = ctx.get("overhead_supply_close", True)
    if rr >= cfg.good_rr and not overhead_supply_close:
        score += 10; reasons.append("손익비 우수")
    elif rr >= cfg.min_rr:
        score += 6; reasons.append("손익비 최소 기준 통과")
    else:
        wait_for.append("손익비 1.5 이상 자리 대기")
        vetoes.append("RR_TOO_LOW")  # v1 버그#2 수정: IGNORE 캡

    if score >= cfg.buy_ready:
        state = "BUY_READY"
    elif score >= cfg.watch_high:
        state = "WATCH_HIGH"
    elif score >= cfg.watch:
        state = "WATCH"
    else:
        state = "IGNORE"

    # veto 캡 적용 — v1의 핵심 누락 부분
    if "RR_TOO_LOW" in vetoes:
        state = "IGNORE"
    elif ("NO_PULLBACK" in vetoes or "OVERHEATED" in vetoes) and state == "BUY_READY":
        state = "WATCH"

    return {
        "state": state, "location_score": score, "vetoes": vetoes,
        "reasons": reasons, "wait_for": wait_for, "unknown_fields": unknown_fields,
        "rr": rr, "sector_score": sector_score,
    }
```

---

## 15. 백테스트 통합 (v1에 없던 신규 섹션 — §2 아키텍처 결정의 구현 지점)

기존 runner를 바꾸지 않고, watch_items를 순회하기 **전에** 필터를 끼운다:

```python
# backtest.py 각 run_* 함수 진입부, unique_items 순회 직전
filtered_items = [
    item for item in unique_items
    if evaluate_watchlist_position(build_ctx(store, item, day), cfg)["state"]
    in ("BUY_READY", "WATCH_HIGH")
]
```

`build_ctx()`는 `KiwoomDataStore.load_daily`/`load_minutes`/`aggregate_60m`/
`daily_ema_context`(모두 §3-1 기존 함수)로부터 ctx dict를 만드는 신규 함수 — 이번 작업의
seam 추출 대상.

---

## 16. Claude 구현 지시문 (v1 §15 정정)

```text
LAT 리팩토링 목표: 기존 인트라데이 백테스트/체결 엔진(backtest.py, paper.py,
hourly_abc_support.py 등)은 무변경. Location Score를 그 앞단 일일 필터로 추가한다.

신규 파일:
- src/lat5/location_decision.py
  - evaluate_watchlist_position(ctx, cfg) -> dict  (§14 veto 캡 반영)
  - build_context(store, item, as_of_date) -> dict  (ctx 조립, §15)
  - LocationScoreConfig  (dataclass, §12 — PyYAML 신규 의존성 금지)

핵심 조건 (§7~§9):
- Watchlist 종목만 평가, 아니면 강제 IGNORE
- Sector veto는 Phase 0에서 OFF (cfg.sector_gate_enabled=False)
- 눌림 없음/이격 과열 veto → BUY_READY 상한 WATCH로 캡
- RR < 1.5 veto → 강제 IGNORE
- 점수 80/60/40 임계값은 veto 캡 적용 후 최종 state 결정에만 사용

Trade Journal: 신규 테이블 만들지 말고 paper.py의 decisions.inputs_json에
location_score/vetoes/reasons/wait_for 포함 (§10). decision 컬럼 값에
BUY_READY/WATCH_HIGH/WATCH/IGNORE 사용 가능(스키마 변경 불필요).

백테스트 통합: 각 run_*_baseline() 진입부에서 unique_items를 evaluate_watchlist_position
결과로 사전 필터링(§15). runner 내부 로직은 손대지 않는다.

먼저 TDD로: location_decision.py를 합성 ctx dict로 유닛 테스트(§14 버그 3건의
회귀 테스트 포함 — "눌림 없이 급등"이 WATCH 이하인지, "RR<1.5"가 IGNORE인지,
"이격 과열"이 WATCH 이하인지 반드시 검증). 그 다음 build_context()로 실데이터
연결(005930/000660 2종목 우선, §11 Phase 0).
```

---

## 17. 최종 한 줄

```text
리팩토링 핵심은 종목 발굴 시스템을 버리는 게 아니라(v1 표현 정정),
기존 인트라데이 진입 엔진 위에 "오늘 볼 가치가 있는 종목"을 고르는
일일 위치 판단 필터를 얹는 것이다. 판단부는 엔진을 대체하지 않고 선행한다.
```
