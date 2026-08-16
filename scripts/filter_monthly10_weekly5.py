from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from lat5.data import KiwoomDataStore, parse_watchlist  # noqa: E402
from lat5.monthly_weekly_filter import (  # noqa: E402
    periods_as_of,
    recent_recovery,
    recovery_details,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "lat5_market.db"))
    parser.add_argument(
        "--watchlist", default=str(PROJECT_ROOT / "LAT_SIMPLE_v1.0_Watchlist.md")
    )
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument(
        "--output-dir", default=str(PROJECT_ROOT / "reports" / "monthly_weekly_filter")
    )
    args = parser.parse_args()
    as_of = pd.Timestamp(args.as_of)
    items = {item.ticker: item for item in parse_watchlist(args.watchlist)}
    matches: list[tuple[object, dict[str, object], dict[str, object]]] = []

    with KiwoomDataStore(args.db) as store:
        for item in items.values():
            daily = store.load_daily(item.ticker)
            weekly, monthly = periods_as_of(daily, as_of, include_in_progress=True)
            if recent_recovery(weekly, 5) and recent_recovery(monthly, 10):
                provisional = bool(
                    monthly.index[-1].to_period("M") == as_of.to_period("M")
                    or weekly.index[-1] > as_of
                )
                matches.append(
                    (item, recovery_details(weekly, 5), recovery_details(monthly, 10), provisional)
                )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{as_of.date().isoformat()}.md"
    lines = [
        f"# 월봉 SMA10·주봉 SMA5 회복 필터 — {as_of.date().isoformat()}",
        "",
        "조건: 직전 완료봉이 해당 이동평균선 아래이고 최신 완료봉이 이동평균선 이상으로 회복한 종목.",
        "진행 중 월봉·주봉을 포함하며, 진행 중 기간이 사용된 종목은 잠정으로 표시.",
        "",
        f"대상 종목: {len(items)}개",
        f"통과 종목: {len(matches)}개",
        "",
        "| 코드 | 종목 | 섹터 | 상태 | 주봉 회복 | 월봉 회복 |",
        "|---|---|---|---|---|---|",
    ]
    for item, weekly, monthly, provisional in matches:
        lines.append(
            f"| {item.ticker} | {item.name} | {item.sector} | {'잠정' if provisional else '확정'} | "
            f"{weekly['previous_period']} → {weekly['current_period']} | "
            f"{monthly['previous_period']} → {monthly['current_period']} |"
        )
    if not matches:
        lines.append("| - | 해당 없음 | - | - | - | - |")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"output={output}")
    print(f"as_of={as_of.date()} universe={len(items)} matches={len(matches)}")
    for item, _, _, _ in matches:
        print(f"{item.ticker}\t{item.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
