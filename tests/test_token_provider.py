import hashlib
import json
from datetime import datetime, timedelta

import pytest

from lat5.token_provider import TokenMissing, TokenStale, read_shared_token


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_shared_token_does_not_modify_cache(tmp_path):
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps({"token": "secret-token", "cached_at": "2026-08-09T07:14:34"}),
        encoding="utf-8",
    )
    before_hash = _sha256(cache)
    before_mtime = cache.stat().st_mtime_ns

    snapshot = read_shared_token(cache, now=datetime(2026, 8, 9, 15, 0, 0))

    assert snapshot.token == "secret-token"
    assert snapshot.cached_at == datetime(2026, 8, 9, 7, 14, 34)
    assert snapshot.source == cache.resolve()
    assert _sha256(cache) == before_hash
    assert cache.stat().st_mtime_ns == before_mtime


def test_read_shared_token_rejects_missing_token_key(tmp_path):
    cache = tmp_path / "token.json"
    cache.write_text(json.dumps({"cached_at": "2026-08-09T07:14:34"}), encoding="utf-8")
    with pytest.raises(TokenMissing):
        read_shared_token(cache, now=datetime(2026, 8, 9, 8, 0, 0))


def test_read_shared_token_rejects_cache_at_twelve_hour_boundary(tmp_path):
    now = datetime(2026, 8, 9, 19, 14, 34)
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps({"token": "secret-token", "cached_at": (now - timedelta(hours=12)).isoformat()}),
        encoding="utf-8",
    )
    with pytest.raises(TokenStale):
        read_shared_token(cache, now=now)
