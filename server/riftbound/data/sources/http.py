"""Polite HTTP for source adapters.

Written after a real 429: harvesting the meta means thousands of requests against a
community-run API, and hammering it is both rude and self-defeating. Three behaviours,
shared by every adapter so none of them has to remember:

* **Throttle** — a floor on the gap between requests to one host.
* **Back off** — retry 429 and 5xx with exponential delay, honouring ``Retry-After``.
* **Fail honestly** — once retries are exhausted, raise. Serving stale cache in place of
  a failed fetch is how data problems hide.

Standard library only, so the base install stays small.
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

USER_AGENT = "riftbound-deck-builder/0.1 (+local deck building tool)"

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class HttpError(RuntimeError):
    """A request that could not be satisfied, after retries."""


@dataclass
class RateLimit:
    """Minimum seconds between requests to one host, enforced across threads."""
    min_interval: float = 0.25

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            earliest = self._next_allowed.get(host, 0.0)
            delay = max(0.0, earliest - now)
            self._next_allowed[host] = max(now, earliest) + self.min_interval
        if delay > 0:
            time.sleep(delay)

    def penalise(self, host: str, seconds: float) -> None:
        """Push back every pending request to a host after it rate-limits us."""
        with self._lock:
            self._next_allowed[host] = max(
                self._next_allowed.get(host, 0.0), time.monotonic() + seconds
            )


class HttpClient:
    """A small retrying, throttled fetcher."""

    def __init__(
        self,
        *,
        timeout: float = 45.0,
        min_interval: float = 0.25,
        max_attempts: int = 4,
        base_backoff: float = 1.5,
        max_backoff: float = 30.0,
        referer: str = "",
    ):
        self._timeout = timeout
        self._limiter = RateLimit(min_interval=min_interval)
        self._max_attempts = max(1, max_attempts)
        self._base_backoff = base_backoff
        self._max_backoff = max_backoff
        self._referer = referer

    def get(self, url: str) -> bytes:
        return self._send(url, method="GET", body=None, extra_headers=None)

    def post_json(
        self, url: str, payload: object, *, headers: dict[str, str] | None = None
    ) -> Any:
        """POST JSON and parse the JSON response.

        Extra headers carry credentials for APIs that need them. They are never logged:
        errors from :meth:`_send` mention only the URL.
        """
        body = json.dumps(payload).encode("utf-8")
        merged = {"Content-Type": "application/json", **(headers or {})}
        raw = self._send(url, method="POST", body=body, extra_headers=merged)
        if not raw.strip():
            return None
        if raw[:1] not in (b"{", b"["):
            raise HttpError(f"non-JSON response from {url}: {raw[:40]!r}")
        return json.loads(raw.decode("utf-8"))

    def _send(
        self,
        url: str,
        *,
        method: str,
        body: bytes | None,
        extra_headers: dict[str, str] | None,
    ) -> bytes:
        host = urllib.parse.urlparse(url).netloc
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if self._referer:
            headers["Referer"] = self._referer
        headers.update(extra_headers or {})

        last_error = ""
        for attempt in range(1, self._max_attempts + 1):
            self._limiter.wait(host)
            try:
                request = urllib.request.Request(
                    url, headers=headers, data=body, method=method
                )
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}"
                if exc.code not in RETRY_STATUSES or attempt == self._max_attempts:
                    raise HttpError(f"HTTP {exc.code} from {url}") from exc
                self._limiter.penalise(host, self._delay_for(exc, attempt))
            except urllib.error.URLError as exc:
                last_error = str(exc.reason)
                if attempt == self._max_attempts:
                    raise HttpError(f"could not reach {url}: {exc.reason}") from exc
                self._limiter.penalise(host, self._backoff(attempt))
            except TimeoutError as exc:
                last_error = "timed out"
                if attempt == self._max_attempts:
                    raise HttpError(f"timed out fetching {url}") from exc
                self._limiter.penalise(host, self._backoff(attempt))
        raise HttpError(f"{url} failed after {self._max_attempts} attempts ({last_error})")

    def get_json(self, url: str) -> Any:
        """Parse a JSON response.

        An empty body returns ``None`` — upstream's way of saying "no such record".
        A non-JSON body is an error: several endpoints answer with the string
        ``Hacker! Go home!`` rather than a status code, and parsing that as data would
        be worse than failing.
        """
        body = self.get(url)
        if not body.strip():
            return None
        if body[:1] not in (b"{", b"["):
            raise HttpError(f"non-JSON response from {url}: {body[:40]!r}")
        return json.loads(body.decode("utf-8"))

    def get_text(self, url: str) -> str:
        return self.get(url).decode("utf-8", errors="replace")

    # -- internals -------------------------------------------------------------

    def _delay_for(self, exc: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return min(self._max_backoff, float(retry_after))
            except ValueError:
                pass
        return self._backoff(attempt)

    def _backoff(self, attempt: int) -> float:
        # Exponential with jitter, so parallel workers do not retry in lockstep.
        delay = min(self._max_backoff, self._base_backoff * (2 ** (attempt - 1)))
        return delay * (0.7 + 0.6 * random.random())
