from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _subprocess_env(root: Path) -> dict[str, str]:
    """`-m lat5.cli` needs `src` on PYTHONPATH; the Task Scheduler process
    that launches this script never sets it, so add it explicitly rather
    than relying on an ambient environment variable.
    """
    env = dict(os.environ)
    src = str(root / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src}{os.pathsep}{existing}" if existing else src
    return env


DASHBOARD_LOOKBACK_DAYS = 60


def build_pipeline_commands(
    *, python: str, root: Path, as_of: str
) -> list[list[str]]:
    db = root / "data" / "lat5_market.db"
    watchlist = root / "LAT_SIMPLE_v1.0_Watchlist.md"
    scoring_dir = root / "artifacts" / "latest_scoring"
    backtest_start = (
        datetime.strptime(as_of, "%Y-%m-%d") - timedelta(days=DASHBOARD_LOOKBACK_DAYS)
    ).strftime("%Y-%m-%d")
    return [
        [
            python, "-m", "lat5.cli", "collect",
            "--db", str(db), "--watchlist", str(watchlist),
            "--env", str(root / ".env"),
            "--token-cache", str(root / "data" / "kiwoom_token_cache.json"),
            "--base-date", as_of.replace("-", ""),
        ],
        [
            python, "-m", "lat5.cli", "data-health",
            "--db", str(db), "--watchlist", str(watchlist),
            "--output-dir", str(root),
        ],
        [
            python, str(root / "scripts" / "filter_monthly10_weekly5.py"),
            "--db", str(db), "--watchlist", str(watchlist), "--as-of", as_of,
        ],
        [
            python, str(root / "scripts" / "scan_trendline_rank.py"),
            "--db", str(db), "--watchlist", str(watchlist), "--as-of", as_of,
        ],
        [
            python, "-m", "lat5.cli", "backtest",
            "--source-db", str(db), "--watchlist", str(watchlist),
            "--output-dir", str(scoring_dir),
            "--strategy", "hourly-pullback-reversal", "--location-filter",
            "--start", backtest_start, "--end", as_of, "--overwrite",
        ],
        [
            python, str(root / "scripts" / "build_dashboard.py"),
        ],
    ]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--skip-collect", action="store_true")
    args = parser.parse_args()
    commands = build_pipeline_commands(python=sys.executable, root=ROOT, as_of=args.as_of)
    if args.skip_collect:
        commands = commands[1:]

    log_dir = ROOT / "reports" / "daily_pipeline"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{args.as_of}.log"
    run_started_at = datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"=== run started_at={run_started_at} ===\n")
        log.flush()
        env = _subprocess_env(ROOT)
        for command in commands:
            completed = subprocess.run(
                command, cwd=ROOT, check=False, capture_output=True, text=True, env=env
            )
            log.write(f"$ {' '.join(command)}\n")
            log.write(completed.stdout or "")
            log.write(completed.stderr or "")
            log.flush()
            if completed.returncode != 0:
                log.write(f"=== run result=BLOCKED command_exit={completed.returncode} ===\n")
                log.flush()
                print(f"BLOCKED command_exit={completed.returncode} log={log_path}")
                return completed.returncode
        log.write("=== run result=COMPLETE ===\n")
    print(f"COMPLETE log={log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
