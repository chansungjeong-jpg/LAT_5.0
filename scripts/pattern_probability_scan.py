from __future__ import annotations

import argparse
from pathlib import Path

from lat5.data import KiwoomDataStore, parse_watchlist
from lat5.pattern_probability import evaluate_ticker


def _fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def build_report(rows: list[tuple[str, str, object]]) -> str:
    lines = [
        "| 코드 | 종목 | 판정 | n_train(5d) | n_test(5d) | t_train(5d) | t_test(5d) | "
        "n_train(10d) | n_test(10d) | t_train(10d) | t_test(10d) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ticker, name, verdict in rows:
        h5, h10 = verdict.hold_5, verdict.hold_10
        lines.append(
            f"| {ticker} | {name} | {verdict.verdict} | {h5.n_train} | {h5.n_test} | "
            f"{_fmt(h5.t_train)} | {_fmt(h5.t_test)} | {h10.n_train} | {h10.n_test} | "
            f"{_fmt(h10.t_train)} | {_fmt(h10.t_test)} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--watchlist", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()

    items = parse_watchlist(args.watchlist)
    rows = []
    with KiwoomDataStore(args.db) as store:
        for item in items:
            daily = store.load_daily(item.ticker)
            if daily.empty:
                continue
            verdict = evaluate_ticker(daily.sort_index())
            rows.append((item.ticker, item.name, verdict))

    out_dir = Path("reports") / "pattern_probability"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.as_of}.md"
    out_path.write_text(
        f"# 패턴 확률 스캔 — {args.as_of}\n\n"
        f"패턴: 당일수익률>=+7% AND 거래량>=20일평균x2, 진입=돌파+3거래일 종가, "
        f"청산=진입+5일/+10일 종가. 판정 기준: 문서 "
        f"`docs/superpowers/specs/2026-08-18-pattern-probability-scan-design.md`.\n\n"
        + build_report(rows)
        + "\n",
        encoding="utf-8",
    )
    print(f"output={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
