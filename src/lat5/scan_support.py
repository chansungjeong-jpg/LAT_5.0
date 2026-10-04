"""Shared helpers for the dated scan scripts (RS / recovery filter)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def truncate_daily_as_of(daily: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Rows dated on or before ``as_of``. A scan labelled with a past date
    must not see later bars (look-ahead), so every scan truncates its daily
    input with this before computing anything."""
    if daily.empty:
        return daily
    cutoff = pd.Timestamp(as_of).normalize()
    return daily.loc[daily.index.normalize() <= cutoff]


def should_update_latest(path: Path, as_of: str) -> bool:
    """False only when ``path`` already holds a strictly newer ``as_of``.

    The ``latest_scoring`` JSONs feed the live dashboard. Re-running a scan
    for a past date (backfill) must still write its dated report but must not
    roll the "latest" snapshot back. Missing/corrupt files are replaced.
    """
    try:
        existing = json.loads(Path(path).read_text(encoding="utf-8")).get("as_of")
    except (OSError, ValueError, AttributeError):
        return True
    return not (existing and str(existing) > str(as_of))
