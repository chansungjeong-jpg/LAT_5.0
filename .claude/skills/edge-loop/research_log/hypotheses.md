# 가설 사전등록 로그

양식: `../HYPOTHESIS_TEMPLATE.md`. 새 항목은 맨 아래 추가, 기존 항목 수정 금지(상태 필드만 갱신).

---

## H-001: 체결시점 변경 — 다음날 시가진입 → 신호일 종가진입+H일차 시가청산

- 등록일: 2026-09-07 (소급 등록 — 스킬 만들기 전 대화에서 이미 실행됨)
- 근거: 154종목×2015~2026 야간(전일종가→시가)/장중(시가→종가) 레그를 연 단위로 쪼개면 야간이 12년 전부 평균 양수, 장중은 8/12년 음수. 기존 체결은 신호일 야간 레그를 놓치고 청산일 장중 레그를 떠안는 구조.
- 변경 범위: `resolve_entry_close`, `resolve_outcome_close_to_open` 추가(기존 `resolve_entry`/`resolve_outcome`은 그대로 둠)
- 예상 부호: A/B(종가진입)가 기존보다 gross/net 모두 개선
- 채택 기준: SKILL.md 규칙4 그대로
- 평가 구간: 2026-08-13 ~ 2026-09-07 (당시엔 train/holdout 분리 전 — 전체를 한 번에 봄)
- 상태: **RESOLVED — FAILED** (`failures.md` 참고). train/holdout 분리 정책은 이 실패 이후 도입.

---

## H-002: 체결강도·외국인 순매수 feature — 사전등록

- 등록일: 2026-09-09
- 근거: `investor_flow`(외국인 순매수), `execution_strength`(체결강도) 테이블이 수집은 되는데 위치점수·후보판·RS 어디에도 안 쓰인다(`data_health.py`에만 등장). 국지적 데이터라 사전확률 높음.
- 변경 범위: `edge_validation.py`에 `evaluate_flow_signal(daily_trunc, flow_trunc, strength_trunc, as_of) -> FlowResult` 신규 함수 1개 추가. 회복 통과군 대상, 평가일 기준 최근 N일 외국인 순매수 누적 + 체결강도 평균의 횡단면 순위(상/중/하)를 스냅샷에 부착. 기존 `evaluate_recovery`/`evaluate_relative_strength`/`evaluate_location`은 손대지 않음.
- 예상 부호: 상위 그룹(외국인 순매수 강함 + 체결강도 높음)의 forward H일 수익률이 하위 그룹보다 높음
- 채택 기준: SKILL.md 규칙4 그대로
- train 구간: 2026-08-13 ~ 2026-09-02
- holdout 구간: 2026-09-03 ~ 2026-09-09 (등록 시점 세션 캘린더 최근 5거래일 — 실행 시점에 최신 캘린더로 재확인할 것)
- train 실행(2026-09-09, `artifacts/edge_validation/h002_train_20260909/`): 두 신호가 서로 다른 결과 — 아래 상태 참고.
- 상태:
  - **외국인 순매수 5일누적: RESOLVED — FAILED_TRAIN** (`failures.md` H-002a 참고, holdout 안 감)
  - **체결강도 당일평균: PENDING_HOLDOUT** (train 통과, holdout 2026-09-03~09 H=10 성숙 대기)
