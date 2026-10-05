"""Validate a research-agent report against the deterministic facts.

Checks structure and the honesty rules that must not depend on the agent's
judgement: the status cannot be better than the facts' floor, every
hypothesis is accounted for, a matured-but-unrun holdout cannot be ignored,
and nothing may claim adoption (SKILL rule 5: only the user adopts) or give
trade advice. Exit code 0 = PASS, 1 = problems found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = ("한눈에 보기", "파이프라인 상태", "가설 현황", "이번에 한 일", "한계·미확인", "다음 행동")
_RANK = {"OK": 0, "WARN": 1, "FAIL": 2}
_ADOPTION = re.compile(r"채택\s*(완료|되었|됐|됨)|운영\s*반영\s*완료|SSOT[^.\n]*(수정|반영)(했|완료)")
_ADVICE = re.compile(r"매수\s*추천|매수하세요|사세요|수익\s*보장|확실한\s*수익")


def validate(text: str, facts: dict) -> list[str]:
    problems: list[str] = []
    status = re.search(r"^상태:\s*(OK|WARN|FAIL)\b", text, re.MULTILINE)
    if not status:
        problems.append("첫머리에 '상태: OK|WARN|FAIL' 줄이 없다")
    else:
        floor = facts.get("pipeline_floor", "OK")
        if _RANK[status.group(1)] < _RANK.get(floor, 0):
            problems.append(f"상태 {status.group(1)} 는 사실이 정한 floor {floor} 보다 좋을 수 없다")

    for section in REQUIRED_SECTIONS:
        if not re.search(rf"^##\s*{re.escape(section)}", text, re.MULTILINE):
            problems.append(f"필수 섹션 누락: ## {section}")

    for hypothesis in facts.get("hypotheses", []):
        if hypothesis["id"] not in text:
            problems.append(f"가설 {hypothesis['id']} 가 보고서에 없다")

    if "매매 신호가 아" not in text:
        problems.append("'매매 신호가 아님' 고지 문구가 없다")
    if _ADVICE.search(text):
        problems.append("매매 권유성 표현이 있다 (관찰·연구 보고만 허용)")
    if _ADOPTION.search(text):
        problems.append("채택/운영 반영 완료 단정 금지 — 채택은 사용자 승인 후에만 (규칙5)")

    for hypothesis_id in facts.get("holdout_ready", []):
        if not re.search(rf"{re.escape(hypothesis_id)}[^\n]*holdout|holdout[^\n]*{re.escape(hypothesis_id)}", text):
            problems.append(f"{hypothesis_id} holdout 이 성숙·미실행인데 실행 결과나 보류 사유가 없다")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--facts", required=True)
    args = parser.parse_args(argv)
    facts = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    problems = validate(Path(args.report).read_text(encoding="utf-8"), facts)
    if problems:
        print("FAIL")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
