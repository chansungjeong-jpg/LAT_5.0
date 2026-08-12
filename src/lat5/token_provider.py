from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class TokenError(RuntimeError):
    """Base class for non-refreshing shared-token failures."""


class TokenMissing(TokenError):
    pass


class TokenStale(TokenError):
    pass


class TokenInvalid(TokenError):
    pass


@dataclass(frozen=True)
class TokenSnapshot:
    token: str
    cached_at: datetime
    source: Path


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def read_shared_token(
    path: str | Path,
    max_age_hours: float = 12,
    now: datetime | None = None,
) -> TokenSnapshot:
    source = Path(path).resolve()
    if not source.is_file():
        raise TokenMissing(f"token cache missing: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TokenMissing(f"token cache unreadable: {source}") from exc

    token = payload.get("token") or payload.get("access_token")
    cached_at_raw = payload.get("cached_at")
    if not isinstance(token, str) or not token.strip() or not isinstance(cached_at_raw, str):
        raise TokenMissing("token or cached_at missing")
    try:
        cached_at = datetime.fromisoformat(cached_at_raw)
    except ValueError as exc:
        raise TokenMissing("cached_at is not ISO-8601") from exc

    checked_at = _utc_naive(now or datetime.now())
    cached_at_cmp = _utc_naive(cached_at)
    age_hours = (checked_at - cached_at_cmp).total_seconds() / 3600
    if age_hours < 0 or age_hours >= max_age_hours:
        raise TokenStale(f"token cache age out of range: {age_hours:.2f}h")
    return TokenSnapshot(token.strip(), cached_at, source)
