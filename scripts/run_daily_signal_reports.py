from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_pipeline_commands(
    *, python: str, root: Path, as_of: str
) -> list[list[str]]:
    db = root / "data" / "lat5_market.db"
    watchlist = root / "LAT_SIMPLE_v1.0_Watchlist.md"
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
        for command in commands:
            completed = subprocess.run(
                command, cwd=ROOT, check=False, capture_output=True, text=True
            )
            log.write(f"$ {' '.join(command)}\n")
            log.write(completed.stdout or "")
            log.write(completed.stderr or "")
            if completed.returncode != 0:
                log.write(f"=== run result=BLOCKED command_exit={completed.returncode} ===\n")
                print(f"BLOCKED command_exit={completed.returncode} log={log_path}")
                return completed.returncode
        log.write("=== run result=COMPLETE ===\n")
    print(f"COMPLETE log={log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
