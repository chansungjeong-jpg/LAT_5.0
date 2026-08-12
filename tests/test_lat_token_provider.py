import json
from datetime import datetime

from lat5.lat_credentials import KiwoomCredentials
from lat5.lat_token_provider import get_lat_token


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "return_code": 0,
            "token": "new-token",
            "expires_dt": "20260810160000",
        }

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append((url, headers, json, timeout))
        return FakeResponse()


def test_get_lat_token_issues_and_caches_dedicated_token(tmp_path):
    cache = tmp_path / "token.json"
    session = FakeSession()

    snapshot = get_lat_token(
        KiwoomCredentials("app", "secret"),
        cache,
        session=session,
        now=datetime(2026, 8, 9, 16, 0, 0),
    )

    assert snapshot.token == "new-token"
    assert session.calls[0][0].endswith("/oauth2/token")
    assert session.calls[0][2] == {
        "grant_type": "client_credentials",
        "appkey": "app",
        "secretkey": "secret",
    }
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["token"] == "new-token"
    assert saved["expires_dt"] == "20260810160000"


def test_get_lat_token_reuses_unexpired_cache_without_http(tmp_path):
    cache = tmp_path / "token.json"
    cache.write_text(
        json.dumps(
            {
                "token": "cached-token",
                "cached_at": "2026-08-09T15:00:00",
                "expires_dt": "20260810150000",
            }
        ),
        encoding="utf-8",
    )
    session = FakeSession()

    snapshot = get_lat_token(
        KiwoomCredentials("app", "secret"),
        cache,
        session=session,
        now=datetime(2026, 8, 9, 16, 0, 0),
    )

    assert snapshot.token == "cached-token"
    assert session.calls == []
