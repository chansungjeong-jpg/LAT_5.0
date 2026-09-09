---
name: edge-loop
description: LAT_5.0 회복필터·RS·위치점수·체결규칙에 대한 새 가설을 측정 기반으로 반복 검증하는 루프. 골든셋 대신 train/holdout 거래일 분할을 쓰고, edge_validation.py 하네스로 gross/net/MFE/MAE/독립블록수를 채점한다. 가설은 한 번에 하나만, 사전등록 후 코드 diff 하나만 넣고 재실행, 기준 충족 시에만 채택. Use when 사용자가 LAT_5.0의 파이프라인 개선, 새 feature 추가, 에지(가설) 검증, 체결/청산 규칙 실험을 요청할 때.
---

# LAT_5.0 에지 검증 루프

`docs/edge_validation_design.md`가 계약, 이 스킬은 그 계약 위에서 가설을 **반복** 굴리는 절차다.
매 실행은 `research_log/hypotheses.md`에 기록 없이는 시작하지 않는다.

## 절대 규칙

1. **사전등록 없이 코드부터 바꾸지 않는다.** 가설·예상방향·채택기준을 `research_log/hypotheses.md`에 먼저 적는다 — 결과 보고 기준을 고르면 그 순간 무효.
2. **한 번에 diff 하나.** 여러 곳 동시 변경 금지. `src/lat5/edge_validation.py`/`edge_validation_stats.py`에 새 함수를 추가하는 방식으로(기존 함수 수정 아님) 이전 가설과 독립적으로 유지한다.
3. **holdout 절대 훔쳐보지 않는다.** 세션 캘린더 기준 **최근 5거래일**은 항상 holdout. 가설 탐색(코드 작성·파라미터 조정)은 train 구간(`c-handoff.md` 8/13 ~ holdout 시작일 전날)에서만 하고, holdout은 최종 확인 1회만 돌린다.
4. **채택 기준은 3개 동시 충족**: (a) train·holdout 부호 일관 (b) `independent_blocks_recovery_pass` ≥ 2 (c) net 기준으로도 개선. 하나라도 빠지면 기각 — "방향은 맞는데 표본이 적다"는 채택 사유가 아니다.
5. **SSOT·운영코드 자동수정 금지.** `LAT_SIMPLE_v1_0_final_spec.md`, `scripts/run_daily_signal_reports.py`, `location_decision.py`의 임계값은 채택된 가설이라도 사용자 승인 후에만 반영한다.
6. **실주문·외부알림 없음.** 이 시스템은 관찰 전용(`c-handoff.md` 범위). 스킬도 마찬가지.

## Holdout 정책

- 세션 캘린더(`edge_validation.build_session_calendar`)에서 뒤에서 5개 거래일 = holdout.
- H=10 outcome은 홀드아웃 마지막 날 기준으로도 즉시 성숙하지 않는다 — **정상**. 홀드아웃 확정판정은 그 outcome이 실제로 MATURE로 찍히는 날까지 미룬다(전진검증, 조작 불가능한 지연).
- train 구간이 좁아지는 트레이드오프는 알고 감수한 것(사용자 확정, 2026-09-09). 표본이 더 쌓이면 holdout 폭을 넓히는 것도 재검토 대상.

## 절차 (매 가설마다)

1. `research_log/hypotheses.md`에 새 항목 추가: 가설·근거(왜 이 feature/규칙이 될 것 같은지)·예상 부호·채택기준(위 규칙4)·train/holdout 구간 날짜. 상태 `REGISTERED`.
2. `src/lat5/edge_validation.py`에 최소 diff로 계산 추가(예: feature snapshot에 필드 하나, 또는 `resolve_*` 변형 함수 하나). TDD로 회귀테스트 먼저(`tests/test_edge_validation.py` 패턴 따름).
3. train 구간으로 `python scripts/validate_edge.py --start <train_start> --end <holdout_start-1일>` 실행, `comparisons.json`/report 확인. 기준 미달이면 여기서 기각 가능(holdout 훔쳐볼 필요 없음) — `failures.md`에 기록, 상태 `FAILED_TRAIN`.
4. train 통과 시 상태 `PENDING_HOLDOUT`으로 바꾸고, holdout outcome이 성숙할 때까지 대기(다른 가설 진행 가능).
5. holdout 성숙 후 `python scripts/validate_edge.py --start <holdout_start> --end <오늘>` 1회 실행 — **재시도 금지**(1회 결과가 곧 판정). 규칙4 충족 → `adopted.md`로, 미충족 → `failures.md`로 이동, 상태 `RESOLVED`.
6. 채택돼도 SSOT/운영코드 반영은 사용자에게 별도로 물어본다(규칙5).

## 파일 지도

- 계약: `docs/edge_validation_design.md`, `c-handoff.md`
- 계산: `src/lat5/edge_validation.py`, `src/lat5/edge_validation_stats.py`
- 실행: `scripts/validate_edge.py`
- 회귀테스트: `tests/test_edge_validation*.py`
- 사전등록/판정 로그: `research_log/hypotheses.md`, `research_log/adopted.md`, `research_log/failures.md`
- 등록 양식: `HYPOTHESIS_TEMPLATE.md`

## 다중검정 예산

가설 시도마다 `research_log/hypotheses.md`에 일련번호(H-001, H-002…)를 매겨 누적 시도수를 항상 알 수 있게 한다. 시도수가 늘수록(대략 10건 단위) 채택기준(규칙4)에 다중비교 보정(Bonferroni류)을 얹는 걸 고려한다 — X-trading의 attempt_count/TRIAGE.md와 같은 취지.
