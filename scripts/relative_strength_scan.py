from __future__ import annotations

import argparse
import json
from pathlib import Path

from lat5.data import KiwoomDataStore, parse_watchlist
from lat5.relative_strength import market_average_return, relative_strength

DAYS = 20
JSON_OUTPUT = Path("artifacts") / "latest_scoring" / "relative_strength.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args()

    items = parse_watchlist(args.watchlist)
    frames = {}
    with KiwoomDataStore(args.db) as store:
        for item in items:
            daily = store.load_daily(item.ticker)
            if not daily.empty:
                frames[item.ticker] = daily.sort_index()

    market_return = market_average_return(frames, days=args.days)

    rows = []
    for item in items:
        daily = frames.get(item.ticker)
        if daily is None:
            continue
        result = relative_strength(daily, market_return, days=args.days)
        if result is not None:
            rows.append((item.ticker, item.name, result))
    rows.sort(key=lambda row: row[2].rs, reverse=True)

    market_return_text = (
        f"{market_return * 100:.2f}%" if market_return is not None else "계산불가"
    )
    out_dir = Path("reports") / "relative_strength"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.as_of}.md"
    lines = [
        f"# 상대강도(RS) 스캔 — {args.as_of}",
        "",
        f"기준: {args.days}거래일 수익률. 시장 대리값 = Watchlist {len(frames)}종목 "
        f"동일가중 평균수익률({market_return_text}). "
        "**진짜 KOSPI/KOSDAQ 지수 아님** — 지수 차트 TR 코드 미확인 상태의 임시 대리값"
        "(`market_proxy_method=watchlist_equal_weight_v1`).",
        "",
        "| 순위 | 코드 | 종목 | 종목 수익률 | 시장(대리) 수익률 | RS |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for rank, (ticker, name, result) in enumerate(rows, start=1):
        lines.append(
            f"| {rank} | {ticker} | {name} | {result.stock_return * 100:.2f}% | "
            f"{result.market_return * 100:.2f}% | {result.rs * 100:+.2f}%p |"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(
        json.dumps(
            {
                "as_of": args.as_of,
                "days": args.days,
                "market_proxy_method": "watchlist_equal_weight_v1",
                "market_return": market_return,
                "universe_size": len(frames),
                "rows": [
                    {
                        "ticker": ticker,
                        "name": name,
                        "stock_return": result.stock_return,
                        "market_return": result.market_return,
                        "rs": result.rs,
                    }
                    for ticker, name, result in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"output={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
