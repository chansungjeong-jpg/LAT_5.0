import json
import sqlite3
from datetime import date

import pytest

from lat5 import research_facts as rf

HYPOTHESES_MD = """# 가설 사전등록 로그

---

## H-001: 체결시점 변경

- 등록일: 2026-09-07
- 평가 구간: 2026-08-13 ~ 2026-09-07 (당시엔 분리 전)
- 상태: **RESOLVED — FAILED** (`failures.md` 참고).

---

## H-002: 체결강도·외국인 순매수 feature

- 등록일: 2026-09-09
- train 구간: 2026-08-13 ~ 2026-09-02
- holdout 구간: 2026-09-03 ~ 2026-09-09 (등록 시점 세션 캘린더 최근 5거래일)
- 상태:
  - **외국인 순매수 5일누적: RESOLVED — FAILED_TRAIN** (`failures.md` H-002a 참고)
  - **체결강도 당일평균: PENDING_HOLDOUT** (train 통과)

---

## H-003: RSI 회복 신호

- 등록일: 2026-09-11
- train 구간: 2026-08-13 ~ 2026-09-04 (holdout 시작 전날까지)
- holdout 구간: 2026-09-07 ~ 2026-09-11 (등록 시점)
- 상태: **RESOLVED — FAILED_TRAIN** (`failures.md` H-003 참고)
"""


def test_parse_hypotheses_extracts_ids_ranges_and_states():
    items = rf.parse_hypotheses(HYPOTHESES_MD)

    assert [h["id"] for h in items] == ["H-001", "H-002", "H-003"]
    h2 = items[1]
    assert h2["train"] == ("2026-08-13", "2026-09-02")
    assert h2["holdout"] == ("2026-09-03", "2026-09-09")
    assert ("체결강도 당일평균", "PENDING_HOLDOUT") in h2["status_items"]
    assert ("외국인 순매수 5일누적", "FAILED_TRAIN") in h2["status_items"]
    assert items[0]["holdout"] is None
    assert items[2]["status_items"][0][1] == "FAILED_TRAIN"


def test_parse_hypotheses_open_items_are_pending_or_registered_only():
    items = rf.parse_hypotheses(HYPOTHESES_MD)

    open_ids = [(h["id"], label) for h in items for label, state in h["status_items"]
                if state in ("PENDING_HOLDOUT", "REGISTERED")]
    assert open_ids == [("H-002", "체결강도 당일평균")]


def test_sessions_after_counts_only_strictly_later_sessions():
    sessions = ["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"]

    assert rf.sessions_after("2026-09-09", sessions) == 3
    assert rf.sessions_after("2026-09-14", sessions) == 0


def test_holdout_maturity_matured_when_enough_sessions_after_holdout_end():
    sessions = [f"2026-09-{d:02d}" for d in range(9, 24) if date(2026, 9, d).weekday() < 5]

    result = rf.holdout_maturity("2026-09-09", 10, sessions)

    assert result["matured"] is True
    assert result["sessions_after"] == 10
    assert result["sessions_missing"] == 0


def test_holdout_maturity_reports_missing_sessions_and_estimate():
    sessions = ["2026-09-09", "2026-09-10", "2026-09-11"]

    result = rf.holdout_maturity("2026-09-09", 10, sessions)

    assert result["matured"] is False
    assert result["sessions_missing"] == 8
    assert result["estimated_date"] is not None  # weekday estimate, holidays not modelled


def _stage(top_g, bot_g, top_n=30, bot_n=30, blocks=2, top_net=None, bot_net=None):
    def group(gross, net, n):
        return {"n_observations": n, "mean_gross_pooled": gross, "mean_net_pooled": net}
    return {
        "strength_top": group(top_g, top_g - 0.0033 if top_net is None else top_net, top_n),
        "strength_bottom": group(bot_g, bot_g - 0.0033 if bot_net is None else bot_net, bot_n),
        "independent_blocks_recovery_pass": blocks,
    }


def _comparisons(h10, h5=None):
    return {"next_open": {"hold_10": h10, "hold_5": h5 or h10}}


def test_rule4_adopt_candidate_when_signs_blocks_and_net_all_pass():
    train = _comparisons(_stage(0.02, 0.00))
    holdout = _comparisons(_stage(0.015, 0.005, blocks=2))

    result = rf.evaluate_rule4(train, holdout, top="strength_top", bottom="strength_bottom")

    assert result["verdict"] == "ADOPT_CANDIDATE"
    assert all(result["checks"].values())


def test_rule4_rejects_when_holdout_sign_flips():
    train = _comparisons(_stage(0.02, 0.00))
    holdout = _comparisons(_stage(-0.01, 0.01))

    result = rf.evaluate_rule4(train, holdout, top="strength_top", bottom="strength_bottom")

    assert result["verdict"] == "REJECT"
    assert result["checks"]["sign_consistent"] is False
    assert "sign_consistent" in result["failed"]


def test_rule4_rejects_when_independent_blocks_below_two_even_if_direction_is_right():
    train = _comparisons(_stage(0.02, 0.00))
    holdout = _comparisons(_stage(0.03, 0.00, blocks=1))

    result = rf.evaluate_rule4(train, holdout, top="strength_top", bottom="strength_bottom")

    assert result["verdict"] == "REJECT"
    assert result["failed"] == ["independent_blocks"]


def test_rule4_rejects_when_gross_improves_but_net_does_not():
    # top beats bottom gross by +0.2%p but a higher cost on top flips net.
    train = _comparisons(_stage(0.02, 0.00))
    holdout = _comparisons(_stage(0.004, 0.002, top_net=-0.001, bot_net=0.001))

    result = rf.evaluate_rule4(train, holdout, top="strength_top", bottom="strength_bottom")

    assert result["verdict"] == "REJECT"
    assert result["failed"] == ["net_improves"]


def test_rule4_insufficient_when_holdout_group_has_no_matured_sample():
    train = _comparisons(_stage(0.02, 0.00))
    holdout = _comparisons({
        "strength_top": {"n_observations": 0, "mean_gross_pooled": None, "mean_net_pooled": None},
        "strength_bottom": {"n_observations": 0, "mean_gross_pooled": None, "mean_net_pooled": None},
        "independent_blocks_recovery_pass": 0,
    })

    result = rf.evaluate_rule4(train, holdout, top="strength_top", bottom="strength_bottom")

    assert result["verdict"] == "INSUFFICIENT"


def test_rule4_reports_h5_agreement_as_information_not_a_gate():
    train = _comparisons(_stage(0.02, 0.00), h5=_stage(0.01, 0.00))
    holdout = _comparisons(_stage(0.015, 0.005), h5=_stage(-0.01, 0.01))

    result = rf.evaluate_rule4(train, holdout, top="strength_top", bottom="strength_bottom")

    assert result["verdict"] == "ADOPT_CANDIDATE"
    assert result["h5_consistent"] is False


def test_rule4_expected_negative_sign_supported():
    train = _comparisons(_stage(0.00, 0.02))
    holdout = _comparisons(_stage(0.00, 0.01))

    result = rf.evaluate_rule4(train, holdout, top="strength_top", bottom="strength_bottom",
                               expected_sign=-1)

    assert result["checks"]["sign_consistent"] is True


def _session_db(path, dates, tickers=4):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE ohlcv_daily (provider TEXT, ticker TEXT, date TEXT, close REAL)")
    rows = [("kiwoom", f"{t:06d}", d, 1.0) for d in dates for t in range(tickers)]
    conn.executemany("INSERT INTO ohlcv_daily VALUES (?,?,?,?)", rows)
    # a stray placeholder day covering only one ticker must not count as a session
    conn.execute("INSERT INTO ohlcv_daily VALUES ('kiwoom','000000','2026-09-12',1.0)")
    conn.commit()
    conn.close()


def test_load_sessions_requires_majority_ticker_coverage(tmp_path):
    db = tmp_path / "m.db"
    _session_db(db, ["2026-09-09", "2026-09-10"])

    assert rf.load_sessions(db) == ["2026-09-09", "2026-09-10"]
    assert rf.load_sessions(tmp_path / "nope.db") == []


def test_holdout_run_exists_detects_prior_single_shot_run(tmp_path):
    folder = tmp_path / "artifacts" / "edge_validation"
    (folder / "h002_train_20260909").mkdir(parents=True)

    assert rf.holdout_run_exists(tmp_path, "H-002") is False
    (folder / "h002_holdout_20261005").mkdir()
    assert rf.holdout_run_exists(tmp_path, "H-002") is True


def test_budget_counts_registered_hypotheses_and_resolution():
    summary = rf.research_budget(rf.parse_hypotheses(HYPOTHESES_MD))

    assert summary["registered"] == 3
    assert summary["failed"] == 3  # H-001, H-002a, H-003
    assert summary["pending"] == 1
    assert summary["adopted"] == 0


def _fake_facts(**overrides):
    base = {"latest_session": "2026-10-02", "hypotheses": [{
        "id": "H-002", "pending": True, "holdout": ("2026-09-03", "2026-09-09"), "holdout_run_exists": False,
        "maturity": {"matured": True, "sessions_missing": 0}}]}
    base.update(overrides)
    return base


def test_run_holdout_refuses_when_already_run(monkeypatch, tmp_path, capsys):
    facts = _fake_facts()
    facts["hypotheses"][0]["holdout_run_exists"] = True
    monkeypatch.setattr(rf, "collect_facts", lambda root, today: facts)
    monkeypatch.setattr(rf.subprocess, "run", lambda *a, **k: pytest.fail("must not execute"))

    assert rf._run_holdout(tmp_path, "H-002:strength", date(2026, 10, 5)) == 2
    assert "single-shot" in capsys.readouterr().out


def test_run_holdout_refuses_when_not_matured(monkeypatch, tmp_path, capsys):
    facts = _fake_facts()
    facts["hypotheses"][0]["maturity"] = {"matured": False, "sessions_missing": 4}
    monkeypatch.setattr(rf, "collect_facts", lambda root, today: facts)
    monkeypatch.setattr(rf.subprocess, "run", lambda *a, **k: pytest.fail("must not execute"))

    assert rf._run_holdout(tmp_path, "H-002:strength", date(2026, 10, 5)) == 2
    assert "not matured" in capsys.readouterr().out


def test_run_holdout_refuses_unknown_or_non_pending_hypothesis(monkeypatch, tmp_path):
    facts = _fake_facts()
    facts["hypotheses"][0]["pending"] = False
    monkeypatch.setattr(rf, "collect_facts", lambda root, today: facts)
    monkeypatch.setattr(rf.subprocess, "run", lambda *a, **k: pytest.fail("must not execute"))

    assert rf._run_holdout(tmp_path, "H-002:strength", date(2026, 10, 5)) == 2
    assert rf._run_holdout(tmp_path, "H-999", date(2026, 10, 5)) == 2


def test_run_holdout_runs_registered_window_through_latest_session(monkeypatch, tmp_path):
    monkeypatch.setattr(rf, "collect_facts", lambda root, today: _fake_facts())
    seen = {}

    def fake_run(command, cwd=None):
        seen["command"] = command

        class Done:
            returncode = 0
        return Done()

    monkeypatch.setattr(rf.subprocess, "run", fake_run)

    assert rf._run_holdout(tmp_path, "H-002:strength", date(2026, 10, 5)) == 0
    command = seen["command"]
    assert command[command.index("--start") + 1] == "2026-09-03"
    assert command[command.index("--end") + 1] == "2026-10-02"
    assert command[command.index("--run-id") + 1] == "h002_holdout_20261005"


def test_pending_approval_state_is_parsed_and_counted_as_pending():
    text = HYPOTHESES_MD.replace("**체결강도 당일평균: PENDING_HOLDOUT** (train 통과)",
                                 "**체결강도 당일평균: PENDING_APPROVAL** (규칙4 통과, 승인 대기)")

    items = rf.parse_hypotheses(text)

    assert ("체결강도 당일평균", "PENDING_APPROVAL") in items[1]["status_items"]
    assert rf.research_budget(items)["pending"] == 1
    # an approval-pending hypothesis is not a holdout candidate any more
    assert not any(state == "PENDING_HOLDOUT" for _, state in items[1]["status_items"])
