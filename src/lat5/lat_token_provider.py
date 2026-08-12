from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import requests

from lat5.lat_credentials import KiwoomCredentials
from lat5.token_provider import TokenSnapshot


class LatTokenError(RuntimeError):
    pass


def _read_valid_cache(path: Path, now: datetime) -> TokenSnapshot | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        token = payload["token"]
        cached_at = datetime.fromisoformat(payload["cached_at"])
        expires_at = datetime.strptime(payload["expires_dt"], "%Y%m%d%H%M%S")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(token, str) or not token.strip():
        return None
    if now < cached_at or now + timedelta(minutes=5) >= expires_at:
        return None
    return TokenSnapshot(token.strip(), cached_at, path)


def get_lat_token(
    credentials: KiwoomCredentials,
    cache_path: str | Path,
    *,
    session=None,
    now: datetime | None = None,
    force: bool = False,
    base_url: str = "https://api.kiwoom.com",
) -> TokenSnapshot:
    checked_at = now or datetime.now()
    cache = Path(cache_path).resolve()
    if not force:
        cached = _read_valid_cache(cache, checked_at)
        if cached is not None:
            return cached

    try:
        response = (session or requests.Session()).post(
            f"{base_url.rstrip('/')}/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={
                "grant_type": "client_credentials",
                "appkey": credentials.appkey,
                "secretkey": credentials.secretkey,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LatTokenError("token request failed") from exc
    if str(payload.get("return_code", "0")).strip() not in {"0", "0000"}:
        raise LatTokenError(str(payload.get("return_msg", "token issuance failed")))
    token = payload.get("token") or payload.get("access_token")
    expires_dt = payload.get("expires_dt")
    if not isinstance(token, str) or not token or not isinstance(expires_dt, str):
        raise LatTokenError("token response missing token or expires_dt")

    cache.parent.mkdir(parents=True, exist_ok=True)
    saved = {
        "token": token,
        "cached_at": checked_at.isoformat(),
        "expires_dt": expires_dt,
    }
    temporary = cache.with_suffix(cache.suffix + ".tmp")
    temporary.write_text(json.dumps(saved), encoding="utf-8")
    temporary.replace(cache)
    return TokenSnapshot(token, checked_at, cache)
