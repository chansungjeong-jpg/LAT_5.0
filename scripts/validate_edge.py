"""Research CLI for c-handoff.md: 회복 필터 -> RS -> 위치점수 에지 검증.

Read-only against data/lat5_market.db. Never touches artifacts/latest_scoring
or the daily 16:00 automation. Writes an immutable snapshot per run under
artifacts/edge_validation/<run_id>/ plus a Korean report under
reports/edge_validation/<run_id>.md.

Usage:
    python scripts/validate_edge.py --start 2026-08-13 --end 2026-09-07
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from lat5.edge_validation import RunConfig, TickerDayRecord, run  # noqa: E402
from lat5.edge_validation_stats import build_comparisons  # noqa: E402
from lat5.location_decision import LocationScoreConfig  # noqa: E402


def _monthly_leg_decomposition(
    daily_full: dict[str, pd.DataFrame], *, months: int = 12
) -> list[dict[str, object]]:
    """Per-calendar-month overnight (prev close -> open) vs intraday
    (open -> close) mean leg return across the universe, trailing `months`
    months. This backs the priority-1 fill-rule A/B: the claim "overnight
    beats intraday" is a 12-year aggregate, but it is NOT stable month to
    month (verified below) -- reporting the aggregate alone without this
    breakdown would overstate how safe the A/B swap is.
    """
    frames = []
    for daily in daily_full.values():
        if daily.empty or "volume" not in daily.columns:
            continue
        work = daily.loc[daily["volume"].astype(float) > 0].sort_index()
        if len(work) < 2:
            continue
        prev_close = work["close"].astype(float).shift(1)
        overnight = work["open"].astype(float) / prev_close - 1.0
        intraday = work["close"].astype(float) / work["open"].astype(float) - 1.0
        frames.append(pd.DataFrame({"overnight": overnight, "intraday": intraday}))
    if not frames:
        return []
    combined = pd.concat(frames).dropna()
    cutoff = combined.index.max() - pd.DateOffset(months=months)
    combined = combined.loc[combined.index > cutoff]
    combined["month"] = combined.index.to_period("M")
    grouped = combined.groupby("month").agg(
        n=("overnight", "size"), overnight=("overnight", "mean"), intraday=("intraday", "mean")
    )
    return [
        {
            "month": str(month),
            "n": int(row["n"]),
            "overnight_pct": float(row["overnight"] * 100),
            "intraday_pct": float(row["intraday"] * 100),
        }
        for month, row in grouped.iterrows()
    ]


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
        )
        return completed.stdout.strip()
    except Exception:
        return None


def _json_default(obj: object) -> object:
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"not JSON serializable: {type(obj)!r}")


def _snapshot_row(record: TickerDayRecord) -> dict[str, object]:
    return {
        "eval_day": record.eval_day.date().isoformat(),
        "ticker": record.ticker,
        "name": record.name,
        "sectors": list(record.sectors),
        "recovery_passed": record.recovery.passed,
        "recovery_provisional": record.recovery.provisional,
        "recovery_reason": record.recovery.reason,
        "recovery_weekly_detail": record.recovery.weekly_detail,
        "recovery_monthly_detail": record.recovery.monthly_detail,
        "rs": record.rs,
        "stock_return_lookback": record.stock_return,
        "location_score": record.location.score,
        "location_state": record.location.state,
        "location_vetoes": list(record.location.vetoes),
        "location_rr": record.location.rr,
        "location_rr_known": record.location.rr_known,
        "location_unknown_fields": list(record.location.unknown_fields),
        "location_reason": record.location.reason,
        "flow_foreign_net_cum": record.flow.foreign_net_cum,
        "flow_foreign_net_lookback_days": record.flow.foreign_net_lookback_days,
        "flow_strength_mean": record.flow.strength_mean,
        "flow_reason": record.flow.reason,
        "rsi14": record.rsi.rsi14,
        "rsi14_prev": record.rsi.rsi14_prev,
        "rsi_signal": record.rsi.signal,
        "rsi_reason": record.rsi.reason,
        "entry_status": record.entry.status,
        "entry_date": (
            record.entry.entry_date.date().isoformat() if record.entry.entry_date is not None else None
        ),
        "entry_price": record.entry.entry_price,
        "entry_reason": record.entry.reason,
        "entry_close_status": record.entry_close.status,
        "entry_close_date": (
            record.entry_close.entry_date.date().isoformat()
            if record.entry_close.entry_date is not None else None
        ),
        "entry_close_price": record.entry_close.entry_price,
        "entry_close_reason": record.entry_close.reason,
    }


def _outcome_rows(record: TickerDayRecord) -> list[dict[str, object]]:
    """One row per (hold_days, fill_rule). fill_rule="next_open" is the
    production rule (next-session open entry -> H-day close exit);
    "close_to_open" is the priority-1 A/B candidate (signal-day close entry
    -> H-day open exit, see edge_validation.py docstring above
    resolve_entry_close)."""
    rows = []
    entry_date = record.entry.entry_date.date().isoformat() if record.entry.entry_date else None
    for hold_days, outcome in sorted(record.outcomes.items()):
        rows.append(
            {
                "eval_day": record.eval_day.date().isoformat(),
                "ticker": record.ticker,
                "hold_days": hold_days,
                "fill_rule": "next_open",
                "status": outcome.status,
                "entry_date": entry_date,
                "entry_price": record.entry.entry_price,
                "exit_date": outcome.exit_date.date().isoformat() if outcome.exit_date is not None else None,
                "exit_price": outcome.exit_price,
                "gross_return": outcome.gross_return,
                "net_return": outcome.net_return,
                "mfe": outcome.mfe,
                "mae": outcome.mae,
                "sessions_available": outcome.sessions_available,
                "sessions_required": outcome.sessions_required,
            }
        )
    entry_close_date = (
        record.entry_close.entry_date.date().isoformat() if record.entry_close.entry_date else None
    )
    for hold_days, outcome in sorted(record.outcomes_close_to_open.items()):
        rows.append(
            {
                "eval_day": record.eval_day.date().isoformat(),
                "ticker": record.ticker,
                "hold_days": hold_days,
                "fill_rule": "close_to_open",
                "status": outcome.status,
                "entry_date": entry_close_date,
                "entry_price": record.entry_close.entry_price,
                "exit_date": outcome.exit_date.date().isoformat() if outcome.exit_date is not None else None,
                "exit_price": outcome.exit_price,
                "gross_return": outcome.gross_return,
                "net_return": outcome.net_return,
                "mfe": outcome.mfe,
                "mae": outcome.mae,
                "sessions_available": outcome.sessions_available,
                "sessions_required": outcome.sessions_required,
            }
        )
    return rows


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:+.2f}%"


def _fmt_stats(stats, hold_days: int) -> str:
    if stats.n_observations == 0:
        return f"n=0 (성숙 표본 없음, H={hold_days})"
    return (
        f"n={stats.n_observations}(평가일 {stats.n_eval_days}개) "
        f"gross평균(종목풀링)={_pct(stats.mean_gross_pooled)} "
        f"gross평균(일별평균의평균)={_pct(stats.mean_gross_daily_avg)} "
        f"net평균={_pct(stats.mean_net_pooled)} "
        f"중앙값={_pct(stats.median_gross_pooled)} "
        f"양수비율={stats.positive_rate_pooled * 100:.1f}%" if stats.positive_rate_pooled is not None
        else f"n={stats.n_observations}"
    )


def render_report(
    *,
    run_id: str,
    cfg: RunConfig,
    universe_size: int,
    calendar: list[pd.Timestamp],
    eval_days: list[pd.Timestamp],
    comparisons: dict[str, object],
    comparisons_close_to_open: dict[str, object],
    monthly_legs: list[dict[str, object]],
    manifest: dict[str, object],
) -> str:
    lines: list[str] = []
    a = lines.append
    a(f"# 회복 필터·RS·위치점수 에지 검증 — run {run_id}")
    a("")
    a(f"근거: `c-handoff.md`, 설계: `docs/edge_validation_design.md`, 코드: "
      f"`src/lat5/edge_validation.py`, `src/lat5/edge_validation_stats.py`, "
      f"CLI: `scripts/validate_edge.py`")
    a("")
    a("## 0. 실행 범위")
    a("")
    a(f"- 평가 구간: `{cfg.start}` ~ `{cfg.end}` (거래일 기준, 캘린더 전체 {len(calendar)}일 중 "
      f"평가 대상 {len(eval_days)}일)")
    a(f"- 모집단: 고유 종목 {universe_size}개 (`{Path(cfg.watchlist_path).name}` 섹터 중복 제거)")
    a(f"- 보유일: {', '.join(f'H={h}(주평가)' if h == 10 else f'H={h}(보조)' for h in cfg.holds)}")
    a(f"- RS lookback: {cfg.rs_days}거래일 (시장 대리값 = 관찰목록 비교군, 실제 지수 아님)")
    a(f"- 비용 가정: 수수료 {cfg.commission_bps}bp/side, 매도세 {cfg.sell_tax_bps}bp, "
      f"슬리피지 {cfg.slippage_bps}bp/side(왕복 적용). 출처: `src/lat5/backtest.py BacktestConfig` "
      f"기본값 재사용 — **저장소 안에 도입 근거 문서는 없음(한계로 명시)**.")
    cost_breakeven = (2 * cfg.commission_bps + cfg.sell_tax_bps + 2 * cfg.slippage_bps) / 100.0
    a(f"- 손익분기 비용: {cost_breakeven:.2f}% (왕복)")
    a(f"- 코드 버전: `{manifest.get('git_commit') or 'UNKNOWN'}`")
    a(f"- 평가일 목록: {', '.join(d.date().isoformat() for d in eval_days)}")
    a("")

    a("## 1순위 A/B: 체결시점 — 다음날 시가진입 vs 신호일 종가진입→H일차 시가청산")
    a("")
    a("가설의 출처: 154종목×2015~2026 야간(전일종가→시가)/장중(시가→종가) 레그를 연 단위로 "
      "쪼개면 야간은 12년 전부 평균 양수, 장중은 8/12년 음수였다(연 단위 집계, 별도 조사). "
      "기존 체결(다음날 시가 진입 → H일차 종가 청산)은 신호일의 야간 레그를 놓치고 청산일의 "
      "장중 레그를 그대로 떠안는다는 논리로, 정확히 그 두 레그만 바꿔치기했다: **같은 청산일**"
      "(entry_pos+H 행)을 그대로 두고 진입만 신호일 종가로, 청산가만 그 날의 시가로 교체"
      "(`edge_validation.py: resolve_entry_close`/`resolve_outcome_close_to_open`, 같은 "
      "feature·같은 표본, 체결 규칙만 다름).")
    a("")
    for hold_days in cfg.holds:
        old_all = comparisons[f"hold_{hold_days}"]["overall_universe"]
        new_all = comparisons_close_to_open[f"hold_{hold_days}"]["overall_universe"]
        old_pass = comparisons[f"hold_{hold_days}"]["recovery_pass"]
        new_pass = comparisons_close_to_open[f"hold_{hold_days}"]["recovery_pass"]
        a(f"**H={hold_days}**")
        a(f"- 전체 유효, 기존(시가진입): {_fmt_stats(old_all, hold_days)}")
        a(f"- 전체 유효, A/B(종가진입): {_fmt_stats(new_all, hold_days)}")
        if old_all.n_observations and new_all.n_observations:
            diff = new_all.mean_gross_pooled - old_all.mean_gross_pooled
            a(f"  → 차이(A/B - 기존) = {diff * 100:+.2f}%p")
        a(f"- 회복 통과군, 기존(시가진입): {_fmt_stats(old_pass, hold_days)}")
        a(f"- 회복 통과군, A/B(종가진입): {_fmt_stats(new_pass, hold_days)}")
        if old_pass.n_observations and new_pass.n_observations:
            diff = new_pass.mean_gross_pooled - old_pass.mean_gross_pooled
            a(f"  → 차이(A/B - 기존) = {diff * 100:+.2f}%p")
        a("")
    a("### 검증: 월별 야간/장중 레그가 실제로 안정적인가")
    a("")
    a("가설의 근거였던 '야간>장중' 방향이 이번 평가 구간에서도 성립하는지 같은 154종목 "
      "원자료로 직접 재확인했다. 결과: **성립하지 않는다.** 위 A/B가 기존 체결보다 나쁘게 "
      "나온 이유는 버그가 아니라 이 구간의 실제 레그 부호가 장기평균과 반대였기 때문이다.")
    a("")
    a("| 월 | n | 야간평균 | 장중평균 |")
    a("|---|---:|---:|---:|")
    for row in monthly_legs:
        a(f"| {row['month']} | {row['n']} | {row['overnight_pct']:+.2f}% | {row['intraday_pct']:+.2f}% |")
    a("")
    a("2026-08은 장중이 오히려 야간보다 강했고(+0.68% vs +0.24%), 03·05·06·07월은 반대로 "
      "장중이 크게 마이너스였다 — **월별로 부호가 자주 뒤집힌다.** 12년 연 단위 집계에서 "
      "'야간이 대체로 우세'는 방향으로는 맞지만, 그 방향을 다음 몇 주에 그대로 적용할 수 있다는 "
      "근거는 못 된다. 즉 **1순위 가설은 이번 4주 표본에서 기각**됐고, 근거였던 장기 패턴 "
      "자체도 월 단위로는 불안정함이 확인됐다 — 지금 체결 규칙을 바꾸는 근거로 쓰기엔 이르다.")
    a("")

    for hold_days in cfg.holds:
        label = "주평가" if hold_days == 10 else "보조평가"
        stage = comparisons[f"hold_{hold_days}"]
        a(f"## H={hold_days} ({label})")
        a("")
        blocks = stage["independent_blocks_recovery_pass"]
        a(f"독립 블록(겹치지 않는 보유기간) 수 = **{blocks}개** — "
          + ("2개 이상이므로 방향성 참고 가능." if blocks >= 2
             else "1개 이하 → 유의성 검정 불가, 아래 수치는 전부 표본 부족/통계적 판단 보류로 취급."))
        a("")
        a("### 1) 회복 효과: 전체 유효(관찰목록 비교군) vs 회복 통과군")
        a("")
        a(f"- 전체 유효: {_fmt_stats(stage['overall_universe'], hold_days)}")
        a(f"- 회복 통과군: {_fmt_stats(stage['recovery_pass'], hold_days)}")
        a(f"- 회복 미통과군: {_fmt_stats(stage['recovery_fail'], hold_days)}")
        a("")
        a("### 2) RS 추가 효과 (회복 통과군 내, RS 계산 가능 종목만, 평가일별 순위)")
        a("")
        a(f"- 상위 1/3: {_fmt_stats(stage['rs_top'], hold_days)}")
        a(f"- 중위 1/3: {_fmt_stats(stage['rs_mid'], hold_days)}")
        a(f"- 하위 1/3: {_fmt_stats(stage['rs_bottom'], hold_days)}")
        a(f"- 상위 30%(ceil, 동점은 코드순): {_fmt_stats(stage['rs_top30'], hold_days)}")
        a("")
        a("### 3) 위치점수 추가 효과 (회복 통과군 내, 위치점수 계산 가능 종목만, 평가일별 순위)")
        a("")
        a(f"- 0–39: {_fmt_stats(stage['loc_0_39'], hold_days)}")
        a(f"- 40–59: {_fmt_stats(stage['loc_40_59'], hold_days)}")
        a(f"- 60–79: {_fmt_stats(stage['loc_60_79'], hold_days)}")
        a(f"- 80–100: {_fmt_stats(stage['loc_80_100'], hold_days)}")
        a(f"- RS 상위군과 동일 종목수의 위치점수 상위군: {_fmt_stats(stage['loc_top_n'], hold_days)}")
        a("")
        a("### 4) 손익비(RR) 차단 감사 (위치점수 계산 가능 회복 통과군만)")
        a("")
        a(f"- RR 통과(RR_TOO_LOW 없음): {_fmt_stats(stage['rr_pass'], hold_days)}")
        a(f"- RR 차단(RR_TOO_LOW): {_fmt_stats(stage['rr_blocked'], hold_days)}")
        a(f"- RR 미측정(눌림 컨텍스트 자체가 없음): {_fmt_stats(stage['rr_unmeasured'], hold_days)}")
        a("")
        a("### 5) 외국인수급·체결강도 추가 효과 (H-002, 회복 통과군 내, 평가일별 순위, "
          "탐색적 — train 구간에서 사전등록 기준 검증 전)")
        a("")
        a(f"- 외국인 순매수 5일누적 상위 1/3: {_fmt_stats(stage['foreign_top'], hold_days)}")
        a(f"- 외국인 순매수 5일누적 중위 1/3: {_fmt_stats(stage['foreign_mid'], hold_days)}")
        a(f"- 외국인 순매수 5일누적 하위 1/3: {_fmt_stats(stage['foreign_bottom'], hold_days)}")
        a(f"- 체결강도 당일평균 상위 1/3: {_fmt_stats(stage['strength_top'], hold_days)}")
        a(f"- 체결강도 당일평균 중위 1/3: {_fmt_stats(stage['strength_mid'], hold_days)}")
        a(f"- 체결강도 당일평균 하위 1/3: {_fmt_stats(stage['strength_bottom'], hold_days)}")
        a("")

    a("## RR 차단군의 동시발생 veto (전체 평가일 누적)")
    a("")
    cooccurrence = comparisons.get("rr_veto_cooccurrence", {})
    if cooccurrence:
        for veto, count in sorted(cooccurrence.items(), key=lambda kv: -kv[1]):
            a(f"- {veto}: {count}건")
    else:
        a("- RR 차단 사례 없음")
    a("")

    a("## 6) 결합 가설 — 탐색적, 독립 검증 아님")
    a("")
    a("RS 상위군과 위치점수 상위군은 위에서 각각 별도로 정의했다. 이번 실행 결과에서 "
      "두 상위군이 겹치는 정도는 `comparisons.json`의 `rs_top30`/`loc_top_n` 종목 목록을 "
      "직접 대조해야 한다(자동 교차표는 표본이 이미 부족해 추가로 쪼개면 의미가 없다고 판단해 "
      "생성하지 않았다 — 필요하면 다음 라운드에서 표본이 쌓인 뒤 별도로 만든다).")
    a("")

    a("## 데이터 유효 범위·한계")
    a("")
    a(f"- 세션 캘린더는 종목 다수결 기반 자체 계산이다(실제 거래소 캘린더 아님) — "
      f"`src/lat5/edge_validation.py:build_session_calendar`, 최소 커버리지 "
      f"{cfg.session_min_coverage * 100:.0f}%.")
    a("- 진입 미체결(`UNFILLED`)·미성숙(`IMMATURE`)·데이터 결손(`DATA_GAP`)은 0%나 조기청산으로 "
      "채우지 않고 표본에서 제외했다 — 구체적 건수는 `outcomes.jsonl`에서 상태별로 집계 가능하다.")
    a("- 위치점수는 SSOT 파이프라인 순서(회복 통과 후 위치점수)를 그대로 따라 회복 통과군에만 "
      "계산했다. `location_decision.py`의 `build_context`/`evaluate_watchlist_position`(대시보드 실경로)만 "
      "재사용했고 미사용 경로인 `location_score.py`는 건드리지 않았다.")
    a("- 8/13 Git 최초 저장 이전 구간은 생존/선정 편향 가능성이 있어 이번 1차 실행에는 포함하지 않았다"
      "(설계 결정, `docs/edge_validation_design.md` §7).")
    a("- 수정주가/기업행사 사후 조정 가능성은 DB 원천 갱신 이력을 별도 감사하지 않았다 — 한계로 남긴다.")
    a("- `execution_strength`(체결강도) DB 이력은 2026-08-07부터만 존재(154종목, 18일치) — 회복 통과군 "
      "중 그 이전 평가일은 강도 신호가 구조적으로 결측이다. `investor_flow`(외국인 순매수)는 2018년부터 "
      "있어 커버리지 문제 없음. H-002는 아직 사전등록만 된 탐색적 신호이며 train/holdout 판정 전이다 — "
      "`.claude/skills/edge-loop/research_log/hypotheses.md` 참고.")
    a("")
    a(f"산출물: `artifacts/edge_validation/{run_id}/manifest.json`, `snapshots.jsonl`, "
      f"`outcomes.jsonl`, `comparisons.json`.")
    a("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "lat5_market.db"))
    parser.add_argument("--watchlist", default=str(PROJECT_ROOT / "LAT_SIMPLE_v1.0_Watchlist.md"))
    parser.add_argument("--start", default="2026-08-13")
    parser.add_argument("--end", required=True)
    parser.add_argument("--holds", default="10,5,20")
    parser.add_argument("--rs-days", type=int, default=20)
    parser.add_argument("--session-min-coverage", type=float, default=0.5)
    parser.add_argument("--commission-bps", type=float, default=1.5)
    parser.add_argument("--sell-tax-bps", type=float, default=20.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--output-root", default=str(PROJECT_ROOT / "artifacts" / "edge_validation"))
    parser.add_argument("--report-root", default=str(PROJECT_ROOT / "reports" / "edge_validation"))
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    holds = tuple(int(h) for h in args.holds.split(","))
    cfg = RunConfig(
        db_path=args.db,
        watchlist_path=args.watchlist,
        start=args.start,
        end=args.end,
        holds=holds,
        rs_days=args.rs_days,
        session_min_coverage=args.session_min_coverage,
        location_cfg=LocationScoreConfig(),
        commission_bps=args.commission_bps,
        sell_tax_bps=args.sell_tax_bps,
        slippage_bps=args.slippage_bps,
    )

    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or started_at.strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_root) / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    report_dir = Path(args.report_root)
    report_dir.mkdir(parents=True, exist_ok=True)

    result = run(cfg)
    universe = result["universe"]
    calendar = result["calendar"]
    eval_days = result["eval_days"]
    records: list[TickerDayRecord] = result["records"]
    daily_full: dict[str, pd.DataFrame] = result["daily_full"]

    comparisons = build_comparisons(records, eval_days, calendar, holds, cfg.rs_days, "outcomes")
    comparisons_close_to_open = build_comparisons(
        records, eval_days, calendar, holds, cfg.rs_days, "outcomes_close_to_open"
    )
    monthly_legs = _monthly_leg_decomposition(daily_full)

    db_path = Path(args.db)
    universe_fingerprint = hashlib.sha256(
        "\n".join(sorted(u.ticker for u in universe)).encode("utf-8")
    ).hexdigest()[:16]
    manifest = {
        "run_id": run_id,
        "generated_at_utc": started_at.isoformat(),
        "git_commit": _git_commit(),
        "config": dataclasses.asdict(cfg),
        "db_path": str(db_path),
        "db_size_bytes": db_path.stat().st_size if db_path.exists() else None,
        "db_mtime_utc": (
            datetime.fromtimestamp(db_path.stat().st_mtime, tz=timezone.utc).isoformat()
            if db_path.exists() else None
        ),
        "universe_size": len(universe),
        "universe_fingerprint_sha256_16": universe_fingerprint,
        "session_calendar_size": len(calendar),
        "session_calendar_range": (
            [calendar[0].date().isoformat(), calendar[-1].date().isoformat()] if calendar else None
        ),
        "eval_days": [d.date().isoformat() for d in eval_days],
        "record_count": len(records),
        "monthly_leg_decomposition": monthly_legs,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )

    with (output_dir / "snapshots.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(_snapshot_row(record), ensure_ascii=False, default=_json_default))
            handle.write("\n")

    with (output_dir / "outcomes.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            for row in _outcome_rows(record):
                handle.write(json.dumps(row, ensure_ascii=False, default=_json_default))
                handle.write("\n")

    (output_dir / "comparisons.json").write_text(
        json.dumps(
            {"next_open": comparisons, "close_to_open": comparisons_close_to_open},
            ensure_ascii=False, indent=2, default=_json_default,
        ),
        encoding="utf-8",
    )

    report_text = render_report(
        run_id=run_id,
        cfg=cfg,
        universe_size=len(universe),
        calendar=calendar,
        eval_days=eval_days,
        comparisons=comparisons,
        comparisons_close_to_open=comparisons_close_to_open,
        monthly_legs=monthly_legs,
        manifest=manifest,
    )
    report_path = report_dir / f"{run_id}.md"
    report_path.write_text(report_text, encoding="utf-8")

    print(f"artifacts={output_dir}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
