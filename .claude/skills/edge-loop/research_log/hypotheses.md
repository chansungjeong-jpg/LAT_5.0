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

---

## H-003: RSI(14) 완료봉 회복 신호 — 사전등록

- 등록일: 2026-09-11
- 근거: `daily_ma_reaction.py`는 2026-08-13에 RSI 회복(30/40 상향돌파)을 +2/+3 점수 보너스로 넣었다가 같은 날 `refactor: keep rsi as observation only`(5168ec9)로 되돌려 지금은 `rsi14` 원값만 관찰용으로 노출하고 점수/게이트에서 완전히 제외돼 있다(`docs/superpowers/specs/2026-08-13-rsi-observation-design.md`). 되돌린 사유 문서에 수치 검증 근거가 없다 — edge_validation 체인으로 한 번도 독립 검증된 적 없는 신호. RS·위치점수와 같은 방식으로 회복 통과군 내 효과만 본다.
- 변경 범위: `edge_validation.py`에 `RSIRecoveryResult`/`evaluate_rsi_recovery_signal()` 신규 함수 1개 추가(기존 `wilder_rsi14`를 두 번 호출해 전일/당일 값 비교, 완료봉만 사용, 새 RSI 수식 작성 안 함). `TickerDayRecord`에 `rsi` 필드 추가, `run_eval_day`에서 회복 통과군에 한해 계산(flow와 동일 게이팅). `edge_validation_stats.py`의 `build_comparisons`에 `rsi_recovery`/`rsi_no_recovery` 이분 그룹 추가(기존 `evaluate_recovery`/`evaluate_relative_strength`/`evaluate_location`/`evaluate_flow_signal`은 손대지 않음).
- 예상 부호: 같은 평가일 회복 통과군 중 RSI 회복 신호(전일<30→당일≥30, 또는 전일<40→당일≥40) 발생 종목의 forward H일 수익률이 신호 없는 종목보다 높음.
- 채택 기준: SKILL.md 규칙4 그대로.
- train 구간: 2026-08-13 ~ 2026-09-04 (holdout 시작 전날까지)
- holdout 구간: 2026-09-07 ~ 2026-09-11 (등록 시점 세션 캘린더 최근 5거래일 — 실행 시점에 최신 캘린더로 재확인할 것)
- train 실행(2026-09-11, `artifacts/edge_validation/h003_train_20260911/`): rsi_recovery n=1(H=10/H=5), n=0(H=20) — 표본 부족으로 holdout 진행 없이 train 단계에서 기각.
- 상태: **RESOLVED — FAILED_TRAIN** (`failures.md` H-003 참고)
