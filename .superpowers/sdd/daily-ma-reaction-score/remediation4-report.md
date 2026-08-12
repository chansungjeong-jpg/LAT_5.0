# Daily MA Reaction Score — Remediation 4 보고서

- 저장소: `C:\trading_system\LAT_5.0`
- 시작 HEAD: `3714acf1e4f673f82f21ad98a2925f02951f80ef`
- 작업일: 2026-08-13
- 대상: `approval-review.md` BLOCKER B1/B2
- 결론: **BLOCKER 2건 수정, fail-closed entry 계약 적용**

## 1. 근본 원인

`evaluate_watchlist_position()`의 `state`는 관찰 우선순위와 진입 자격을 함께 표현하고
있었다. 점수 60~79의 `WATCH_HIGH`는 veto가 있어도 상태가 유지됐고, 백테스트가
`BUY_READY`와 `WATCH_HIGH`를 모두 진입 후보로 허용해 다음 문제가 발생했다.

- 70점 `NO_PULLBACK` 및 `OVERHEATED`가 5분 반전 이후 paper BUY 경로로 진행 가능
- `weekly_trend_ok`, `m60_trend_ok`, `m60_slope_pct`, `daily_trend_ok` 누락이
  `unknown_fields`/veto 없이 또는 unknown만 남긴 채 진입 가능
- `UNKNOWN` 문자열은 truthy 점수를 받거나 `m60_slope_pct` 변환 예외를 발생

작업 전 독립 프로브 결과는 다음과 같았다.

| 케이스 | 점수 | 상태 | veto | unknown | entry_eligible |
|---|---:|---|---|---|---|
| NO_PULLBACK | 70 | WATCH_HIGH | NO_PULLBACK | 없음 | 키 없음 |
| OVERHEATED | 70 | WATCH_HIGH | OVERHEATED | 없음 | 키 없음 |
| weekly missing | 60 | WATCH_HIGH | 없음 | weekly만 기록 | 키 없음 |
| m60 trend missing | 50 | WATCH | 없음 | 없음 | 키 없음 |
| daily missing | 65 | WATCH_HIGH | 없음 | 없음 | 키 없음 |

## 2. 구현 설계

관찰 상태는 그대로 두고 실행 계약을 분리했다.

1. evaluator가 모든 반환 경로에서 `entry_eligible: bool`을 명시한다.
2. `entry_eligible=true`는 `state=BUY_READY`이고 veto가 하나도 없을 때만 가능하다.
3. `WATCH_HIGH`는 관찰 상태로 유지하지만 항상 진입 불가다.
4. `NO_PULLBACK`/`OVERHEATED`는 점수와 무관하게 veto를 보존하고 진입을 차단한다.
5. 주봉/60분/일봉 필수 컨텍스트가 누락·`None`·`UNKNOWN`이면 필드명을
   `unknown_fields`에 보존하고 `ENTRY_PREREQUISITE_UNKNOWN` veto를 추가한다.
6. required unknown 때문에 원점수가 BUY_READY여도 관찰용 `WATCH_HIGH`로 제한한다.
7. 백테스트는 `location.get("entry_eligible") is True`만 허용한다. 키가 없는
   레거시 payload도 fail-closed다.
8. diagnostics에는 `entry_eligible`, ledger evidence에는
   `location_entry_eligible`을 veto/unknown/reaction/RR과 함께 기록한다.

## 3. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/lat5/location_decision.py` | required-context UNKNOWN 판정, veto, 명시적 entry eligibility |
| `src/lat5/backtest.py` | WATCH_HIGH allow-list 제거, strict eligibility gate 및 evidence 보존 |
| `tests/test_location_decision.py` | 70점 veto, required missing/UNKNOWN, 정상 BUY_READY 회귀 |
| `tests/test_location_gate_integration.py` | evaluator→backtest→SQLite ledger 진입 차단 회귀 |
| `docs/superpowers/specs/2026-08-13-daily-ma-reaction-score-design.md` | 승인된 진입 자격 계약 명문화 |
| `docs/superpowers/plans/2026-08-13-entry-eligibility-remediation.md` | TDD 실행 계획 |

## 4. TDD 증거

### Evaluator RED

`python -m pytest tests/test_location_decision.py -q`

- 결과: **11 failed, 27 passed**
- 기대 실패: `entry_eligible` 키 없음, required veto/unknown 누락,
  `m60_slope_pct="UNKNOWN"` 변환 예외

### Evaluator GREEN

`python -m pytest tests/test_location_decision.py -q`

- 결과: **38 passed**

### Backtest/ledger RED

`python -m pytest tests/test_location_gate_integration.py -q`

- 결과: **7 failed, 4 passed**
- 기대 실패: ineligible `WATCH_HIGH`가 모두 trade를 생성하고 diagnostics에
  `entry_eligible`이 없음

### Backtest/ledger GREEN 및 mutation check

- 집중 GREEN: **12 passed**
- gate를 기존 `BUY_READY/WATCH_HIGH` allow-list로 일시 복원한 mutation run:
  **7 failed, 5 passed** — 순수 WATCH_HIGH, 두 veto, required missing 케이스가 모두
  trade 생성으로 실패
- strict eligibility gate 복원 후: **12 passed**

## 5. 요구사항 검증

| 요구사항 | 결과 |
|---|---|
| score 70 + NO_PULLBACK | WATCH_HIGH 관찰 유지, veto 보존, eligibility false, trade/BUY ledger 0 |
| score 70 + OVERHEATED | WATCH_HIGH 관찰 유지, veto 보존, eligibility false, trade/BUY ledger 0 |
| plain WATCH_HIGH | veto가 없어도 eligibility false, trade/BUY ledger 0 |
| weekly required missing/UNKNOWN | unknown 보존 + prerequisite veto + 진입 차단 |
| m60 trend/slope missing/UNKNOWN | 각 unknown 보존 + prerequisite veto + 진입 차단 |
| daily required missing/UNKNOWN | unknown 보존 + prerequisite veto + 진입 차단 |
| 100점 배분 | 기존 `30/20/20/10/10/5/5` 계산 유지 |
| reaction/RR evidence | 기존 payload 유지, eligibility evidence만 추가 |
| CLI/report | 기존 직렬화 계약 변경 없음, 전체 회귀로 검증 |

## 6. 전체 검증

| 명령 | 결과 |
|---|---|
| `python -m pytest -q` | **242 passed** |
| `python -m compileall -q src` | **exit 0** |
| `git diff --check` | **exit 0**; Windows CRLF 안내만 존재 |

## 7. 금지 범위 확인

- 주문·브로커 실행 코드 변경 없음
- 알림/notifier 변경 없음
- 스케줄러·Windows Task·`.bat`·`.ps1` 변경 없음
- 기존 미추적 리뷰 산출물은 수정·스테이징하지 않음
- paper backtest의 진입 gate와 evidence만 변경

## 8. 커밋

지정 메시지: `fix: fail closed on entry prerequisites`
