from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from lat5.backtest import (
    BacktestConfig,
    run_hourly_abc_support_baseline,
    run_hourly_breakout_baseline,
    run_hourly_pullback_reversal_baseline,
    run_technical_baseline,
)
from lat5.collector import collect_watchlist
from lat5.collector_store import CollectorStore
from lat5.data import KiwoomDataStore, parse_watchlist
from lat5.data_health import build_data_health, write_data_health
from lat5.kiwoom_client import KiwoomClient, KiwoomTokenError
from lat5.lat_credentials import CredentialsError, load_credentials
from lat5.lat_token_provider import LatTokenError, get_lat_token
from lat5.location_decision import LocationScoreConfig


ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lat5")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--source-db", required=True)
    backtest.add_argument("--watchlist", required=True)
    backtest.add_argument("--output-dir", required=True)
    backtest.add_argument("--start")
    backtest.add_argument("--end")
    backtest.add_argument("--max-symbols", type=int)
    backtest.add_argument("--ticker")
    backtest.add_argument(
        "--strategy",
        choices=("abc", "hourly-ma-or", "hourly-abc-support", "hourly-pullback-reversal"),
        default="hourly-pullback-reversal",
    )
    backtest.add_argument("--commission-bps", type=float, default=1.5)
    backtest.add_argument("--sell-tax-bps", type=float, default=20.0)
    backtest.add_argument("--slippage-bps", type=float, default=5.0)
    backtest.add_argument("--overwrite", action="store_true")
    backtest.add_argument(
        "--location-filter",
        action="store_true",
        help="gate hourly-pullback-reversal candidates through the Location Score "
        "upstream filter (see docs/superpowers/plans/"
        "LAT_SIMPLE_v1_Watchlist_Position_Finder_Refactoring.md section 15)",
    )
    collect = subparsers.add_parser("collect")
    collect.add_argument("--db", required=True)
    collect.add_argument("--watchlist", required=True)
    collect.add_argument("--env", default=str(ROOT / ".env"))
    collect.add_argument("--token-cache", default=str(ROOT / "data" / "kiwoom_token_cache.json"))
    collect.add_argument("--base-date")
    collect_scope = collect.add_mutually_exclusive_group()
    collect_scope.add_argument("--probe", action="store_true")
    collect_scope.add_argument("--ticker")
    health = subparsers.add_parser("data-health")
    health.add_argument("--db", required=True)
    health.add_argument("--watchlist", required=True)
    health.add_argument("--output-dir", default=".")
    return parser


def _number(value: object, digits: int = 2) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def render_report(
    summary: dict[str, object],
    diagnostics: dict[str, object],
    config: BacktestConfig,
    source_db: str,
    start: str | None,
    end: str | None,
) -> str:
    reason_counts = diagnostics.get("reason_counts", {})
    reason_lines = "\n".join(
        f"| {reason} | {count} |" for reason, count in sorted(reason_counts.items())
    ) or "| 없음 | 0 |"
    return f"""# LAT 5.0 TECHNICAL BASELINE Backtest

## 판정

**전체 전략 검증: 실패**

과거 체결강도(`ka10046`)와 시장/섹터의 완전한 시점 데이터가 없어 이 결과는
60분 채널과 5분 Anchor/ABC 진입·손절·목표가만 검증한 기술 베이스라인이다.

## 실행 범위

| 항목 | 값 |
|---|---:|
| 소스 DB | `{source_db}` |
| 시작일 | {start or '전체'} |
| 종료일 | {end or '전체'} |
| Watchlist 종목 | {diagnostics['universe_symbols']} |
| 일봉 커버 종목 | {diagnostics['daily_covered_symbols']} |
| 5분봉 커버 종목 | {diagnostics['minute_covered_symbols']} |
| Anchor | {diagnostics['anchor_count']} |
| 유효 ABC | {diagnostics['abc_count']} |

## 성과

| 지표 | 값 |
|---|---:|
| 거래 수 | {summary['trades']} |
| 승률 | {_number(float(summary['win_rate']) * 100)}% |
| Profit Factor | {_number(summary['profit_factor'], 3)} |
| 기대손익/거래 | {_number(summary['expectancy'])}원 |
| 순손익 | {_number(summary['net_pnl'])}원 |
| 초기자본 대비 수익률 | {_number(summary['return_pct'])}% |
| 최대 낙폭 | {_number(summary['max_drawdown'])}원 |

## 비용 가정

| 항목 | 값 |
|---|---:|
| 매수/매도 수수료 | {config.commission_bps} bps/side |
| 매도 세금 | {config.sell_tax_bps} bps |
| 체결 슬리피지 | {config.slippage_bps} bps |
| 당일 미청산 | 종가 강제청산 |

## 차단 사유

| 사유 | 건수 |
|---|---:|
{reason_lines}

## 남은 필수 게이트

- 키움 `ka10046` 체결강도 시계열 수집 및 응답 필드 라이브 검증
- KOSPI/KOSDAQ 10·20EMA의 point-in-time 시장 게이트 저장
- 동일 시각 거래대금과 외국인 수급을 포함한 섹터 점수 원장
- 시간순 포트폴리오 동시보유·섹터노출·일일손실 게이트 검증
"""


def render_hourly_breakout_report(
    summary: dict[str, object],
    diagnostics: dict[str, object],
    config: BacktestConfig,
    source_db: str,
    start: str | None,
    end: str | None,
    ticker: str | None,
) -> str:
    reason_counts = diagnostics.get("reason_counts", {})
    reason_lines = "\n".join(
        f"| {reason} | {count} |" for reason, count in sorted(reason_counts.items())
    ) or "| 없음 | 0 |"
    return f"""# LAT 5.0 60분봉 이평 돌파 백테스트

## 확정 조건

- 완성된 60분봉 종가가 MA60 또는 MA120을 상향 돌파
- 돌파봉 종가는 MA60과 MA120 모두 위
- 돌파봉 거래량은 직전 20개 60분봉 평균 거래량 {diagnostics['volume_multiple']}배 이상
- 다음 5분봉 시가 진입
- 돌파봉 저가 1틱 아래 손절
- 목표 {diagnostics['target_r']}R

## 실행 범위

| 항목 | 값 |
|---|---:|
| 종목 | {ticker or 'Core Watchlist'} |
| 소스 DB | `{source_db}` |
| 기간 | {start or '전체'} ~ {end or '전체'} |
| 대상 종목 | {diagnostics['universe_symbols']} |
| 5분봉 보유 종목 | {diagnostics['minute_covered_symbols']} |
| 60분봉 충족 종목 | {diagnostics['hourly_covered_symbols']} |
| 돌파 신호 | {diagnostics['breakout_count']} |

## 성과

| 지표 | 값 |
|---|---:|
| 거래 수 | {summary['trades']} |
| 승률 | {_number(float(summary['win_rate']) * 100)}% |
| Profit Factor | {_number(summary['profit_factor'], 3)} |
| 기대수익/거래 | {_number(summary['expectancy'])}원 |
| 순손익 | {_number(summary['net_pnl'])}원 |
| 초기자본 대비 수익률 | {_number(summary['return_pct'])}% |
| 최대 낙폭 | {_number(summary['max_drawdown'])}원 |

## 판정 내역

| 사유 | 건수 |
|---|---:|
{reason_lines}

비용 가정: 수수료 {config.commission_bps} bps/side, 매도세금 {config.sell_tax_bps} bps,
슬리피지 {config.slippage_bps} bps.
"""


def render_hourly_abc_support_report(
    summary: dict[str, object],
    diagnostics: dict[str, object],
    config: BacktestConfig,
    source_db: str,
    start: str | None,
    end: str | None,
    ticker: str | None,
) -> str:
    reason_counts = diagnostics.get("reason_counts", {})
    reason_lines = "\n".join(
        f"| {reason} | {count} |" for reason, count in sorted(reason_counts.items())
    ) or "| 없음 | 0 |"
    return f"""# LAT 5.0 60분봉 ABC·MA60 지지 백테스트

## 확정 조건

- MA60 또는 MA120 강한 60분봉 돌파
- 이평선 위 0.5%, 양봉 몸통 ATR20의 0.8배, 상단 25% 종가, 거래량 2배
- 돌파 후 60분봉 ABC 조정과 C > A higher-low 확인
- C 저가가 MA60 ±0.5%에 닿고 C 종가는 MA60 위
- C 고가를 5분봉 종가가 돌파하면 다음 5분봉 시가 진입
- C 저가 이탈 또는 새로운 강한 돌파가 먼저 나오면 기존 구조 무효
- 손절 C 저가 1틱 아래, 목표 {diagnostics['target_r']}R

## 실행 범위

| 항목 | 값 |
|---|---:|
| 종목 | {ticker or 'Core Watchlist'} |
| 소스 DB | `{source_db}` |
| 기간 | {start or '전체'} ~ {end or '전체'} |
| 대상 종목 | {diagnostics['universe_symbols']} |
| 5분봉 보유 종목 | {diagnostics['minute_covered_symbols']} |
| 60분봉 충족 종목 | {diagnostics['hourly_covered_symbols']} |
| 강한 돌파 | {diagnostics['strong_breakout_count']} |
| ABC·MA60 지지 | {diagnostics['abc_support_count']} |

## 성과

| 지표 | 값 |
|---|---:|
| 거래 수 | {summary['trades']} |
| 승률 | {_number(float(summary['win_rate']) * 100)}% |
| Profit Factor | {_number(summary['profit_factor'], 3)} |
| 기대수익/거래 | {_number(summary['expectancy'])}원 |
| 순손익 | {_number(summary['net_pnl'])}원 |
| 초기자본 대비 수익률 | {_number(summary['return_pct'])}% |
| 최대 낙폭 | {_number(summary['max_drawdown'])}원 |

## 판정 내역

| 사유 | 건수 |
|---|---:|
{reason_lines}

비용 가정: 수수료 {config.commission_bps} bps/side, 매도세금 {config.sell_tax_bps} bps,
슬리피지 {config.slippage_bps} bps.
"""


def render_hourly_pullback_reversal_report(
    summary: dict[str, object],
    diagnostics: dict[str, object],
    config: BacktestConfig,
    source_db: str,
    start: str | None,
    end: str | None,
    ticker: str | None,
) -> str:
    reason_counts = diagnostics.get("reason_counts", {})
    reason_lines = "\n".join(
        f"| {reason} | {count} |" for reason, count in sorted(reason_counts.items())
    ) or "| 없음 | 0 |"
    return f"""# LAT 5.0 60분봉 눌림·5분봉 반전 백테스트

## 확정 조건

- MA60 또는 MA120 강한 60분봉 돌파
- 돌파 후 2~6번째 60분봉에서 EMA60 ±1% 눌림과 종가 지지
- 눌림봉 거래량은 돌파봉보다 감소
- 5분봉 종가가 직전 3개 5분봉 최고가 돌파
- 5분봉 양봉과 직전 20개 평균 거래량의 1.5배 이상 동반
- 확인봉 다음 5분봉 시가 진입, 14:30 이후 신규 진입 금지
- 최초 손절은 눌림 저가 1틱 아래, 거래당 계좌 위험 0.5%
- 1R에서 절반 청산 후 잔여 손절을 진입가로 이동
- 잔여 물량은 2R, 5분봉 EMA20 종가 이탈, 60분 시간청산 또는 장마감 청산

## 실행 범위

| 항목 | 값 |
|---|---:|
| 종목 | {ticker or 'Core Watchlist'} |
| 소스 DB | `{source_db}` |
| 기간 | {start or '전체'} ~ {end or '전체'} |
| 대상 종목 | {diagnostics['universe_symbols']} |
| 5분봉 보유 종목 | {diagnostics['minute_covered_symbols']} |
| 60분봉 충족 종목 | {diagnostics['hourly_covered_symbols']} |
| 강한 돌파 | {diagnostics['strong_breakout_count']} |
| EMA60 눌림 | {diagnostics['pullback_count']} |
| 5분봉 반전 트리거 | {diagnostics['reversal_trigger_count']} |

## 성과

| 지표 | 값 |
|---|---:|
| 거래 수 | {summary['trades']} |
| 승률 | {_number(float(summary['win_rate']) * 100)}% |
| Profit Factor | {_number(summary['profit_factor'], 3)} |
| 기대수익/거래 | {_number(summary['expectancy'])}원 |
| 순손익 | {_number(summary['net_pnl'])}원 |
| 초기자본 대비 수익률 | {_number(summary['return_pct'])}% |
| 최대 낙폭 | {_number(summary['max_drawdown'])}원 |

## 판정 내역

| 사유 | 건수 |
|---|---:|
{reason_lines}

비용 가정: 수수료 {config.commission_bps} bps/side, 매도세금 {config.sell_tax_bps} bps,
슬리피지 {config.slippage_bps} bps. 체결강도와 외국인 수급의 과거 시계열이 없으므로
이 결과는 가격·거래량 기반 기술 베이스라인이다.
"""


def _run_backtest(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_db = output_dir / "lat5_paper.db"
    trades_csv = output_dir / "backtest_trades.csv"
    diagnostics_json = output_dir / "backtest_diagnostics.json"
    report_md = output_dir / "backtest_technical_baseline.md"
    outputs = (output_db, trades_csv, diagnostics_json, report_md)
    existing = [path for path in outputs if path.exists()]
    if existing and not args.overwrite:
        names = ", ".join(path.name for path in existing)
        raise SystemExit(f"output exists; use --overwrite: {names}")
    if args.overwrite:
        for path in existing:
            path.unlink()

    config = BacktestConfig(
        commission_bps=args.commission_bps,
        sell_tax_bps=args.sell_tax_bps,
        slippage_bps=args.slippage_bps,
    )
    items = parse_watchlist(args.watchlist)
    if args.ticker:
        items = [item for item in items if item.ticker == args.ticker]
        if not items:
            raise SystemExit(f"ticker not found in Core Watchlist: {args.ticker}")
    with KiwoomDataStore(args.source_db) as store:
        runner = {
            "abc": run_technical_baseline,
            "hourly-ma-or": run_hourly_breakout_baseline,
            "hourly-abc-support": run_hourly_abc_support_baseline,
            "hourly-pullback-reversal": run_hourly_pullback_reversal_baseline,
        }[args.strategy]
        runner_kwargs: dict[str, object] = {
            "start": args.start, "end": args.end, "max_symbols": args.max_symbols,
        }
        if args.strategy == "hourly-pullback-reversal" and args.location_filter:
            runner_kwargs["location_cfg"] = LocationScoreConfig()
        trades, summary, diagnostics = runner(store, items, output_db, config, **runner_kwargs)
    trades.to_csv(trades_csv, index=False, encoding="utf-8-sig")
    diagnostics_json.write_text(
        json.dumps(
            {"summary": summary, "diagnostics": diagnostics},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.strategy == "hourly-pullback-reversal":
        report_text = render_hourly_pullback_reversal_report(
            summary, diagnostics, config, args.source_db, args.start, args.end,
            args.ticker,
        )
    elif args.strategy == "hourly-abc-support":
        report_text = render_hourly_abc_support_report(
            summary, diagnostics, config, args.source_db, args.start, args.end,
            args.ticker,
        )
    elif args.strategy == "hourly-ma-or":
        report_text = render_hourly_breakout_report(
            summary, diagnostics, config, args.source_db, args.start, args.end,
            args.ticker,
        )
    else:
        report_text = render_report(
            summary, diagnostics, config, args.source_db, args.start, args.end
        )
    report_md.write_text(report_text, encoding="utf-8")
    print(json.dumps({"summary": summary, "output_dir": str(output_dir)}, ensure_ascii=False))
    return 0


def _run_collect(args: argparse.Namespace) -> int:
    try:
        credentials = load_credentials(args.env)
        token = get_lat_token(credentials, args.token_cache)
    except (CredentialsError, LatTokenError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False))
        return 2

    items = parse_watchlist(args.watchlist)
    core_symbols = list(dict.fromkeys(item.ticker for item in items))
    if args.ticker:
        if args.ticker not in core_symbols:
            raise SystemExit(f"ticker not found in Core Watchlist: {args.ticker}")
        symbols = [args.ticker]
    else:
        symbols = ["005930"] if args.probe else core_symbols
    base_date = args.base_date or datetime.now().strftime("%Y%m%d")
    with CollectorStore(args.db) as store:
        run_id = store.start_run(len(symbols), token.cached_at)
        client = KiwoomClient(token)
        try:
            result = collect_watchlist(client, store, run_id, symbols, base_date)
        except KiwoomTokenError as exc:
            store.record_error(run_id, "*", "TOKEN", "TOKEN_ERROR", str(exc))
            store.finish_run(run_id, "BLOCKED", 0, 1)
            print(json.dumps({"status": "BLOCKED", "run_id": run_id, "error": str(exc)}, ensure_ascii=False))
            return 2
        success_count = result["success_symbols"]
        error_count = result["api_errors"]
        status = "COMPLETE" if error_count == 0 else "PARTIAL"
        store.finish_run(run_id, status, success_count, error_count)
    print(
        json.dumps(
            {
                "status": status,
                "run_id": run_id,
                "symbols": len(symbols),
                "success_symbols": success_count,
                "api_errors": error_count,
            },
            ensure_ascii=False,
        )
    )
    return 0 if status == "COMPLETE" else 1


def _run_data_health(args: argparse.Namespace) -> int:
    health = build_data_health(args.db, parse_watchlist(args.watchlist))
    json_path, md_path = write_data_health(health, args.output_dir)
    print(
        json.dumps(
            {"status": health["status"], "json": str(json_path), "report": str(md_path)},
            ensure_ascii=False,
        )
    )
    return 0 if health["status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "backtest":
        return _run_backtest(args)
    if args.command == "collect":
        return _run_collect(args)
    if args.command == "data-health":
        return _run_data_health(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
