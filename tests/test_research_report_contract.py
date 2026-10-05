from lat5 import research_report_contract as contract

FACTS = {
    "pipeline_floor": "WARN",
    "hypotheses": [{"id": "H-001"}, {"id": "H-002"}],
    "holdout_ready": [],
}

GOOD = """상태: WARN

> 관찰·연구 보고이며 매매 신호가 아닙니다.

## 한눈에 보기
- H-001 기각, H-002 대기.

## 파이프라인 상태
최근 실행 일부 BLOCKED.

## 가설 현황
H-001 / H-002 표.

## 이번에 한 일
점검만 수행.

## 한계·미확인
세션 캘린더는 자체 계산.

## 다음 행동 (사용자 결정)
- 없음
"""


def test_good_report_has_no_violations():
    assert contract.validate(GOOD, FACTS) == []


def test_missing_section_is_a_violation():
    text = GOOD.replace("## 한계·미확인\n세션 캘린더는 자체 계산.\n\n", "")

    problems = contract.validate(text, FACTS)

    assert any("한계·미확인" in p for p in problems)


def test_status_cannot_be_better_than_the_facts_floor():
    text = GOOD.replace("상태: WARN", "상태: OK")

    problems = contract.validate(text, FACTS)

    assert any("상태" in p and "floor" in p for p in problems)


def test_status_line_is_required():
    problems = contract.validate(GOOD.replace("상태: WARN\n", ""), FACTS)

    assert any("상태:" in p for p in problems)


def test_every_hypothesis_in_the_facts_must_be_mentioned():
    problems = contract.validate(GOOD.replace("H-002", "H-00X"), FACTS)

    assert any("H-002" in p for p in problems)


def test_adoption_claims_are_rejected_because_they_need_user_approval():
    for phrase in ("H-002는 채택 완료되었다", "운영 반영 완료", "H-002 채택됨"):
        problems = contract.validate(GOOD + "\n" + phrase + "\n", FACTS)
        assert any("채택" in p or "운영 반영" in p for p in problems), phrase


def test_trade_recommendation_language_is_rejected():
    problems = contract.validate(GOOD + "\n이 종목을 매수 추천합니다.\n", FACTS)

    assert any("매매" in p for p in problems)


def test_disclaimer_is_required():
    problems = contract.validate(GOOD.replace("관찰·연구 보고이며 매매 신호가 아닙니다.", ""), FACTS)

    assert any("매매 신호" in p for p in problems)


def test_ready_holdout_must_be_reported_as_run_or_explained():
    facts = {**FACTS, "holdout_ready": ["H-002"]}

    problems = contract.validate(GOOD, facts)

    assert any("holdout" in p for p in problems)
    ok = GOOD.replace("점검만 수행.", "H-002 holdout 1회 실행 결과를 기록함.")
    assert contract.validate(ok, facts) == []
