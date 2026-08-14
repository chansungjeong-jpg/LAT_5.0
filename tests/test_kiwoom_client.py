from datetime import datetime
from pathlib import Path

import pytest

from lat5.kiwoom_client import KiwoomApiError, KiwoomClient, KiwoomTokenError
from lat5.token_provider import TokenSnapshot


class FakeResponse:
    def __init__(self, payload, headers=None, status_code=200):
        self._payload = payload
        self.headers = headers or {}
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _token():
    return TokenSnapshot("abc", datetime(2026, 8, 9, 7, 0), Path("token.json"))


def test_post_pages_propagates_continuation_headers():
    session = FakeSession(
        [
            FakeResponse({"return_code": 0, "rows": [1]}, {"cont-yn": "Y", "next-key": "NEXT"}),
            FakeResponse({"return_code": 0, "rows": [2]}, {"cont-yn": "N"}),
        ]
    )
    client = KiwoomClient(_token(), session=session, min_interval=0, sleep=lambda _: None)

    pages = list(client.post_pages("ka10080", "/api/dostk/chart", {"stk_cd": "005930"}))

    assert [page.page_no for page in pages] == [1, 2]
    assert session.calls[0][1]["headers"]["authorization"] == "Bearer abc"
    assert session.calls[0][1]["headers"]["api-id"] == "ka10080"
    assert session.calls[1][1]["headers"]["cont-yn"] == "Y"
    assert session.calls[1][1]["headers"]["next-key"] == "NEXT"


def test_post_pages_retries_429_then_returns_success():
    session = FakeSession(
        [
            FakeResponse({}, status_code=429),
            FakeResponse({"return_code": 0}, {"cont-yn": "N"}),
        ]
    )
    sleeps = []
    client = KiwoomClient(_token(), session=session, min_interval=0, sleep=sleeps.append)

    assert len(list(client.post_pages("ka10081", "/api/dostk/chart", {}))) == 1
    assert len(session.calls) == 2
    assert sleeps == [1.0]


def test_post_pages_never_retries_token_error():
    session = FakeSession(
        [FakeResponse({"return_code": 3, "return_msg": "8005 Token invalid"})]
    )
    client = KiwoomClient(_token(), session=session, min_interval=0, sleep=lambda _: None)

    with pytest.raises(KiwoomTokenError):
        list(client.post_pages("ka10046", "/api/dostk/mrkcond", {}))
    assert len(session.calls) == 1


def test_post_pages_fails_when_continuation_exceeds_page_limit():
    session = FakeSession(
        [FakeResponse({"return_code": 0}, {"cont-yn": "Y", "next-key": "NEXT"})]
    )
    client = KiwoomClient(
        _token(),
        session=session,
        min_interval=0,
        max_pages=1,
        max_pages_by_api={"ka10080": 1},
        sleep=lambda _: None,
    )

    with pytest.raises(KiwoomApiError, match="page limit"):
        list(client.post_pages("ka10080", "/api/dostk/chart", {}))


def test_post_pages_uses_api_specific_page_limit():
    session = FakeSession(
        [
            FakeResponse({"return_code": 0}, {"cont-yn": "Y", "next-key": "NEXT"}),
            FakeResponse({"return_code": 0}, {"cont-yn": "N"}),
        ]
    )
    client = KiwoomClient(
        _token(),
        session=session,
        min_interval=0,
        max_pages=1,
        max_pages_by_api={"ka10080": 2},
        sleep=lambda _: None,
    )

    pages = list(client.post_pages("ka10080", "/api/dostk/chart", {}))

    assert [page.page_no for page in pages] == [1, 2]
