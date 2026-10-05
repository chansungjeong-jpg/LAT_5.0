"""Deterministic facts for the LAT research agent.

The agent interprets and reports; this module decides what is *true*:
hypothesis states, whether a holdout has matured, whether a holdout was
already spent, and the pre-registered adoption rule (edge-loop SKILL rule 4).
No LLM, no network, no writes to the market DB. A fact the agent cannot
reduce below is a floor: e.g. an unmatured holdout can never be "judged".
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HYPOTHESES_PATH = Path(".claude") / "skills" / "edge-loop" / "research_log" / "hypotheses.md"
EDGE_ARTIFACTS = Path("artifacts") / "edge_validation"

# Which comparison groups encode each pre-registered hypothesis, and the sign
# the registration predicted for (top - bottom). New hypotheses must be added
# here when they are registered -- the agent only *proposes* them.
HYPOTHESIS_GROUPS = {
    "H-002:strength": {"top": "strength_top", "bottom": "strength_bottom", "expected_sign": 1, "hold": 10},
    "H-002:foreign": {"top": "foreign_top", "bottom": "foreign_bottom", "expected_sign": 1, "hold": 10},
    "H-003": {"top": "rsi_recovery", "bottom": "rsi_no_recovery", "expected_sign": 1, "hold": 10},
}

_STATE_ORDER = ("PENDING_HOLDOUT", "FAILED_TRAIN", "FAILED_HOLDOUT", "ADOPTED", "FAILED", "REGISTERED", "RESOLVED")
_DATE = r"(\d{4}-\d{2}-\d{2})"
_RANGE = re.compile(_DATE + r"\s*~\s*" + _DATE)


def _state_of(text: str) -> str | None:
    for state in _STATE_ORDER:
        if state in text:
            return state
    return None


def parse_hypotheses(text: str) -> list[dict]:
    blocks = re.split(r"(?m)^## (?=H-\d+)", text)[1:]
    items = []
    for block in blocks:
        header, _, body = block.partition("\n")
        match = re.match(r"(H-\d+):\s*(.*)", header.strip())
        if not match:
            continue
        item = {"id": match.group(1), "title": match.group(2).strip(), "train": None, "holdout": None,
                "status_items": []}
        in_status = False
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("- train 구간:"):
                found = _RANGE.search(stripped)
                item["train"] = found.groups() if found else None
            elif stripped.startswith("- holdout 구간:"):
                found = _RANGE.search(stripped)
                item["holdout"] = found.groups() if found else None
            if stripped.startswith("- 상태:"):
                in_status = True
                rest = stripped[len("- 상태:"):].strip()
                state = _state_of(rest)
                if state:
                    item["status_items"].append(("", state))
                continue
            if in_status:
                if line.startswith("---") or (line.startswith("- ") and not line.startswith("- 상태")):
                    in_status = False
                    continue
                if line.startswith("  -"):
                    label_match = re.search(r"\*\*(.+?):\s*[^*]*\*\*", stripped)
                    state = _state_of(stripped)
                    if label_match and state:
                        item["status_items"].append((label_match.group(1).strip(), state))
        items.append(item)
    return items


def research_budget(hypotheses: list[dict]) -> dict:
    states = [state for h in hypotheses for _, state in h["status_items"]]
    return {
        "registered": len(hypotheses),
        "failed": sum(1 for s in states if s.startswith("FAILED")),
        "pending": sum(1 for s in states if s in ("PENDING_HOLDOUT", "REGISTERED")),
        "adopted": sum(1 for s in states if s == "ADOPTED"),
        "attempts_note": "다중검정: 시도 수가 늘수록(대략 10건 단위) 채택기준에 보정을 얹는 것을 검토한다.",
    }


def load_sessions(db_path: Path | str, min_coverage: float = 0.5) -> list[str]:
    """Trading sessions = dates on which at least ``min_coverage`` of the
    tickers have a daily row (same idea as the harness' session calendar)."""
    path = Path(db_path)
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            total = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM ohlcv_daily WHERE provider='kiwoom'").fetchone()[0]
            rows = conn.execute(
                "SELECT date, COUNT(DISTINCT ticker) FROM ohlcv_daily WHERE provider='kiwoom' "
                "GROUP BY date ORDER BY date").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    threshold = max(1, -(-int(total) * int(min_coverage * 100) // 100))
    return [day for day, count in rows if count >= threshold]


def sessions_after(day: str, sessions: list[str]) -> int:
    return sum(1 for s in sessions if s > day)


def _add_weekdays(start: date, days: int) -> date:
    cursor = start
    while days > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days -= 1
    return cursor


def holdout_maturity(holdout_end: str, hold_days: int, sessions: list[str]) -> dict:
    """H-day outcomes for the last holdout eval day exist once ``hold_days``
    sessions have passed after it (entry day + H-1 more)."""
    after = sessions_after(holdout_end, sessions)
    missing = max(0, hold_days - after)
    estimated = None
    if missing:
        last = max([holdout_end] + list(sessions))
        estimated = _add_weekdays(datetime.strptime(last, "%Y-%m-%d").date(), missing).isoformat()
    return {"matured": missing == 0, "sessions_after": after, "sessions_missing": missing,
            "estimated_date": estimated, "estimate_note": "평일 기준 추정, 휴장일 미반영" if missing else None}


def holdout_run_exists(root: Path, hypothesis_id: str) -> bool:
    folder = Path(root) / EDGE_ARTIFACTS
    if not folder.exists():
        return False
    prefix = hypothesis_id.lower().replace("-", "")
    return any(p.is_dir() and p.name.startswith(prefix) and "holdout" in p.name for p in folder.iterdir())


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _group_diff(stage: dict, top: str, bottom: str, key: str) -> float | None:
    a, b = stage.get(top) or {}, stage.get(bottom) or {}
    if not a.get("n_observations") or not b.get("n_observations"):
        return None
    if a.get(key) is None or b.get(key) is None:
        return None
    return a[key] - b[key]


def evaluate_rule4(train: dict, holdout: dict, *, top: str, bottom: str, hold: int = 10,
                   expected_sign: int = 1, fill: str = "next_open") -> dict:
    """edge-loop SKILL rule 4, all three required: (a) train and holdout both
    move in the pre-registered direction, (b) >=2 independent blocks in the
    holdout, (c) the same direction holds net of costs. "Direction is right but
    the sample is thin" is not an adoption reason (rule 4)."""
    train_stage = (train.get(fill) or {}).get(f"hold_{hold}") or {}
    holdout_stage = (holdout.get(fill) or {}).get(f"hold_{hold}") or {}
    gross_train = _group_diff(train_stage, top, bottom, "mean_gross_pooled")
    gross_hold = _group_diff(holdout_stage, top, bottom, "mean_gross_pooled")
    net_train = _group_diff(train_stage, top, bottom, "mean_net_pooled")
    net_hold = _group_diff(holdout_stage, top, bottom, "mean_net_pooled")
    blocks = holdout_stage.get("independent_blocks_recovery_pass") or 0

    result = {
        "hold": hold, "expected_sign": expected_sign,
        "gross_diff": {"train": gross_train, "holdout": gross_hold},
        "net_diff": {"train": net_train, "holdout": net_hold},
        "independent_blocks": blocks,
        "n": {"holdout_top": (holdout_stage.get(top) or {}).get("n_observations"),
              "holdout_bottom": (holdout_stage.get(bottom) or {}).get("n_observations")},
    }
    h5_train = _group_diff((train.get(fill) or {}).get("hold_5") or {}, top, bottom, "mean_gross_pooled")
    h5_hold = _group_diff((holdout.get(fill) or {}).get("hold_5") or {}, top, bottom, "mean_gross_pooled")
    result["h5_consistent"] = (None if h5_train is None or h5_hold is None
                               else _sign(h5_train) == _sign(h5_hold) != 0)

    if gross_train is None or gross_hold is None or net_train is None or net_hold is None:
        result.update(verdict="INSUFFICIENT", checks={}, failed=[],
                      reason="train 또는 holdout에 성숙 표본이 없어 판정 불가(미성숙은 0이 아님)")
        return result

    checks = {
        "sign_consistent": _sign(gross_train) == _sign(gross_hold) == expected_sign,
        "independent_blocks": blocks >= 2,
        "net_improves": _sign(net_train) == _sign(net_hold) == expected_sign,
    }
    failed = [name for name, ok in checks.items() if not ok]
    result.update(checks=checks, failed=failed, verdict="ADOPT_CANDIDATE" if not failed else "REJECT",
                  reason=None if not failed else "규칙4 미충족: " + ", ".join(failed))
    return result


def hypothesis_facts(root: Path, sessions: list[str]) -> list[dict]:
    text_path = Path(root) / HYPOTHESES_PATH
    items = parse_hypotheses(text_path.read_text(encoding="utf-8")) if text_path.exists() else []
    out = []
    for item in items:
        facts = {**item, "maturity": None, "holdout_run_exists": holdout_run_exists(root, item["id"])}
        pending = any(state in ("PENDING_HOLDOUT",) for _, state in item["status_items"])
        if pending and item["holdout"]:
            facts["maturity"] = holdout_maturity(item["holdout"][1], 10, sessions)
        facts["pending"] = pending
        out.append(facts)
    return out


def collect_facts(root: Path, today: date | None = None) -> dict:
    from lat5 import dashboard_data as dd
    from lat5 import ops_status

    root = Path(root)
    today = today or date.today()
    db = root / "data" / "lat5_market.db"
    sessions = load_sessions(db)
    hypotheses = hypothesis_facts(root, sessions)
    history = dd.load_history(root)
    change = dd.daily_change(history)
    runs = ops_status.load_pipeline_runs(root / "reports" / "daily_pipeline", limit=10)
    payloads = dd.load_payloads(root)
    return {
        "generated_for": today.isoformat(),
        "data_date": dd.latest_data_date(db),
        "latest_session": sessions[-1] if sessions else None,
        "pipeline_runs": runs,
        "pipeline_floor": "WARN" if any(r["result"] != "COMPLETE" for r in runs[:3]) else "OK",
        "tasks": {name: ops_status.query_task(name) for name in
                  ("LAT5_Monthly10_Weekly5_Recovery", "LAT5_Morning_Pipeline_Health_Check")},
        "report_dates": {"filter": sorted(history.filter_by_date)[-5:], "rs": sorted(history.rs_by_date)[-5:]},
        "change": ({k: (v if not isinstance(v, list) else [x.get("ticker") for x in v])
                    for k, v in change.items() if k != "rs_movers"} if change else None),
        "latest_filter_count": len(history.filter_by_date[max(history.filter_by_date)]) if history.filter_by_date else None,
        "payload_issues": payloads.issues,
        "hypotheses": hypotheses,
        "budget": research_budget(parse_hypotheses(
            (root / HYPOTHESES_PATH).read_text(encoding="utf-8")) if (root / HYPOTHESES_PATH).exists() else []),
        "holdout_ready": [h["id"] for h in hypotheses
                          if h["pending"] and h["maturity"] and h["maturity"]["matured"]
                          and not h["holdout_run_exists"]],
    }


def _load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _run_holdout(root: Path, key: str, today: date) -> int:
    hypothesis_id = key.split(":")[0]
    facts = collect_facts(root, today)
    target = next((h for h in facts["hypotheses"] if h["id"] == hypothesis_id), None)
    if target is None or not target["pending"]:
        print(f"REFUSED: {hypothesis_id} is not PENDING_HOLDOUT")
        return 2
    if target["holdout_run_exists"]:
        print(f"REFUSED: a holdout run for {hypothesis_id} already exists (single-shot rule)")
        return 2
    if not target["maturity"]["matured"]:
        print(f"REFUSED: holdout not matured, missing {target['maturity']['sessions_missing']} sessions")
        return 2
    run_id = f"{hypothesis_id.lower().replace('-', '')}_holdout_{today.strftime('%Y%m%d')}"
    start = target["holdout"][0]
    end = facts["latest_session"]
    command = [sys.executable, str(root / "scripts" / "validate_edge.py"), "--start", start, "--end", end,
               "--run-id", run_id]
    print("RUN:", " ".join(command))
    return subprocess.run(command, cwd=str(root)).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LAT research agent facts (deterministic, read-only)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--today", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    facts_cmd = sub.add_parser("facts")
    facts_cmd.add_argument("--out", default=None)
    holdout_cmd = sub.add_parser("run-holdout")
    holdout_cmd.add_argument("--hypothesis", required=True, help="e.g. H-002:strength")
    rule_cmd = sub.add_parser("rule4")
    rule_cmd.add_argument("--hypothesis", required=True)
    rule_cmd.add_argument("--train", required=True, help="path to the train comparisons.json")
    rule_cmd.add_argument("--holdout", required=True, help="path to the holdout comparisons.json")
    args = parser.parse_args(argv)
    root = Path(args.root)
    today = date.fromisoformat(args.today) if args.today else date.today()

    if args.command == "facts":
        facts = collect_facts(root, today)
        text = json.dumps(facts, ensure_ascii=False, indent=2, default=str)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"facts={args.out} holdout_ready={facts['holdout_ready']} pipeline_floor={facts['pipeline_floor']}")
        else:
            print(text)
        return 0
    if args.command == "run-holdout":
        return _run_holdout(root, args.hypothesis, today)
    spec = HYPOTHESIS_GROUPS.get(args.hypothesis)
    if spec is None:
        print(f"unknown hypothesis group: {args.hypothesis}; register it in HYPOTHESIS_GROUPS")
        return 2
    result = evaluate_rule4(_load_json(args.train), _load_json(args.holdout), top=spec["top"],
                            bottom=spec["bottom"], hold=spec["hold"], expected_sign=spec["expected_sign"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
