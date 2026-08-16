from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from lat5.data import KiwoomDataStore, aggregate_60m, parse_watchlist  # noqa: E402
from lat5.monthly_weekly_filter import periods_as_of, recent_recovery  # noqa: E402
from lat5.trendline_breakout import find_trendline_ma_breakout  # noqa: E402
from lat5.trendline_scoring import score_trendline_candidate  # noqa: E402


def _prepare_hourly(minutes: pd.DataFrame) -> pd.DataFrame:
    hourly = aggregate_60m(minutes)
    if hourly.empty:
        return hourly
    hourly["ema60"] = hourly["close"].ewm(span=60, adjust=False, min_periods=20).mean()
    hourly["ema120"] = hourly["close"].ewm(span=120, adjust=False, min_periods=20).mean()
    previous_close = hourly["close"].shift(1)
    tr = pd.concat(
        [
            hourly["high"] - hourly["low"],
            (hourly["high"] - previous_close).abs(),
            (hourly["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    hourly["atr14"] = tr.rolling(14, min_periods=5).mean()
    return hourly


def _latest_signal(hourly: pd.DataFrame, lookback: int) -> tuple[object, pd.DataFrame] | None:
    start = max(22, len(hourly) - lookback)
    for pos in range(len(hourly) - 1, start - 1, -1):
        signal = find_trendline_ma_breakout(hourly.iloc[: pos + 1])
        if signal is not None:
            return signal, hourly.iloc[: pos + 1]
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--fresh-bars", type=int, default=5)
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "lat5_market.db"))
    parser.add_argument("--watchlist", default=str(PROJECT_ROOT / "LAT_SIMPLE_v1.0_Watchlist.md"))
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports" / "trendline_rank"))
    args = parser.parse_args()
    as_of = pd.Timestamp(args.as_of)
    rows: list[dict[str, object]] = []
    first_filter_count = 0
    items = {item.ticker: item for item in parse_watchlist(args.watchlist)}
    with KiwoomDataStore(args.db) as store:
        for item in items.values():
            daily = store.load_daily(item.ticker)
            daily = daily.loc[daily.index <= as_of]
            weekly, monthly = periods_as_of(daily, as_of, include_in_progress=True)
            if len(weekly) < 5 or len(monthly) < 10:
                continue
            weekly_recovery = recent_recovery(weekly, 5)
            monthly_recovery = recent_recovery(monthly, 10)
            if not (weekly_recovery and monthly_recovery):
                continue
            first_filter_count += 1
            weekly_above = bool(weekly.close.iloc[-1] >= weekly.close.rolling(5).mean().iloc[-1])
            monthly_above = bool(monthly.close.iloc[-1] >= monthly.close.rolling(10).mean().iloc[-1])
            hourly = _prepare_hourly(store.load_minutes(item.ticker).loc[lambda x: x.index <= as_of])
            found = _latest_signal(hourly, args.fresh_bars)
            if found is None:
                continue
            signal, signal_frame = found
            score = score_trendline_candidate(
                signal_frame, signal, weekly_above=weekly_above, monthly_above=monthly_above
            )
            rows.append({
                "ticker": item.ticker,
                "name": item.name,
                "sector": item.sector,
                "signal_time": str(signal_frame.index[signal.breakout_pos]),
                "score": score.total_score,
                "components": score.components,
                "hard_blocks": score.hard_blocks,
                "evidence": score.evidence,
                "weekly_above": weekly_above,
                "monthly_above": monthly_above,
            })
    rows.sort(key=lambda row: (bool(row["hard_blocks"]), -int(row["score"]), str(row["ticker"])))
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report = output / f"{as_of.date().isoformat()}.md"
    selected = [row for row in rows if not row["hard_blocks"]]
    lines = [
        f"# 추세선·이평선 돌파 스코어 순위 — {as_of.date().isoformat()}",
        "",
        f"1차 대상: Core Watchlist {len(items)}종목 / 월봉10선·주봉5선 회복 통과 {first_filter_count}종목",
        f"2차 대상: 1차 통과 종목 중 최근 완료 60분봉 {args.fresh_bars}개 내 추세선·이평선 돌파",
        "점수: 추세선20 + 이평선20 + 거래량20 + 이격도15 + 매물대15 + 월봉·주봉10",
        f"신호 후보 {len(rows)}개, Hard Block 제외 선정 {len(selected)}개",
        "",
        "| 순위 | 코드 | 종목 | 점수 | 신호시각 | 월봉10선 | 주봉5선 | 근거 |",
        "|---:|---|---|---:|---|---|---|---|",
    ]
    for rank, row in enumerate(selected, 1):
        c = row["components"]
        lines.append(
            f"| {rank} | {row['ticker']} | {row['name']} | {row['score']} | {row['signal_time']} | "
            f"{'위' if row['monthly_above'] else '아래'} | {'위' if row['weekly_above'] else '아래'} | "
            f"추세선 {c['trendline']}, 이평 {c['moving_average']}, 거래량 {c['volume']}, "
            f"이격 {c['distance']}, 매물대 {c['supply_room']}, 상위 {c['higher_timeframe']} |"
        )
    if not selected:
        lines.append("| - | - | 해당 없음 | - | - | - | - | - |")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"output={report}")
    print(f"signals={len(rows)} selected={len(selected)}")
    for rank, row in enumerate(selected, 1):
        print(f"{rank}. {row['ticker']} {row['name']} score={row['score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
