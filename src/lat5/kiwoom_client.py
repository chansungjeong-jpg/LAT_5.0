from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping

import requests

from lat5.token_provider import TokenSnapshot


class KiwoomApiError(RuntimeError):
    pass


class KiwoomTokenError(KiwoomApiError):
    pass


@dataclass(frozen=True)
class ApiPage:
    api_id: str
    page_no: int
    payload: dict
    cont_yn: str
    next_key: str


def _payload_has_rows(payload: dict) -> bool:
    return any(isinstance(value, list) and value for value in payload.values())


class KiwoomClient:
    def __init__(
        self,
        token: TokenSnapshot,
        base_url: str = "https://api.kiwoom.com",
        session=None,
        min_interval: float = 0.35,
        max_pages: int = 20,
        max_pages_by_api: Mapping[str, int] | None = None,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self.max_pages = max_pages
        self.max_pages_by_api = {
            "ka10080": 100,
            "ka10059": 100,
            "ka10046": 100,
            **dict(max_pages_by_api or {}),
        }
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.clock = clock
        self._last_request_at: float | None = None

    def _rate_limit(self) -> None:
        if self._last_request_at is not None and self.min_interval > 0:
            remaining = self.min_interval - (self.clock() - self._last_request_at)
            if remaining > 0:
                self.sleep(remaining)

    def _post(self, api_id: str, path: str, body: dict, continuation: dict[str, str]) -> tuple[dict, dict]:
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.token.token}",
            "api-id": api_id,
            **continuation,
        }
        for attempt in range(1, self.max_attempts + 1):
            self._rate_limit()
            response = self.session.post(
                f"{self.base_url}{path}", headers=headers, json=body, timeout=15
            )
            self._last_request_at = self.clock()
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_attempts:
                    raise KiwoomApiError(f"HTTP {response.status_code} after {attempt} attempts")
                self.sleep(float(attempt))
                continue
            if response.status_code >= 400:
                raise KiwoomApiError(f"HTTP {response.status_code}")

            payload = response.json()
            return_code = payload.get("return_code")
            success = return_code is None or str(return_code).strip() in {"0", "0000"}
            if not success:
                message = str(payload.get("return_msg", ""))
                if "8005" in message or "token" in message.lower():
                    raise KiwoomTokenError(f"[{api_id}] {return_code}: {message}")
                raise KiwoomApiError(f"[{api_id}] {return_code}: {message}")
            return payload, dict(response.headers)
        raise KiwoomApiError("unreachable request state")

    def post_pages(
        self,
        api_id: str,
        path: str,
        body: dict,
        *,
        stop_after: Callable[[dict], bool] | None = None,
    ) -> Iterator[ApiPage]:
        continuation: dict[str, str] = {}
        page_limit = self.max_pages_by_api.get(api_id, self.max_pages)
        for page_no in range(1, page_limit + 1):
            payload, response_headers = self._post(api_id, path, body, continuation)
            cont_yn = response_headers.get("cont-yn", "N")
            next_key = response_headers.get("next-key", "")
            yield ApiPage(api_id, page_no, payload, cont_yn, next_key)
            if stop_after is not None and stop_after(payload):
                return
            if cont_yn.upper() != "Y":
                return
            if not _payload_has_rows(payload):
                # Some TRs (observed: ka10046) keep answering cont-yn=Y with
                # empty pages forever once real data is exhausted instead of
                # switching to N. Trust the data, not the server's flag.
                return
            if page_no == page_limit:
                raise KiwoomApiError(f"page limit exceeded for {api_id}: {page_limit}")
            continuation = {"cont-yn": "Y", "next-key": next_key}
