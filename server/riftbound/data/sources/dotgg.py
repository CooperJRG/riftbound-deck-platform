"""Card source: the dotgg community card API.

The primary source. Returns every printing as one JSON row, including sets released
after this code was written -- which is the point. Nothing here enumerates known sets;
a new set arrives as new rows and flows through normalisation untouched.

Uses only the standard library, so the base install stays `fastapi` + `uvicorn` +
`pydantic` and a user who never refreshes card data pays nothing for this.

Per the adapter contract in `base`, this never raises: a failed fetch comes back as
``FetchResult(ok=False, error=...)`` and is recorded in the bundle manifest, so one
source going down is visible rather than silently shrinking the card pool.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .base import CardSource, FetchResult, RawCard
from .http import HttpClient

DEFAULT_URL = "https://api.dotgg.gg/cgfw/getcards?game=riftbound"
DEFAULT_TIMEOUT = 45.0
USER_AGENT = "riftbound-deck-builder/0.1 (+local deck building tool)"

#: Below this, assume the response is an error page or a partial answer rather than the
#: card database. The gate applies the authoritative check against the previous bundle;
#: this is just an early, clearer failure.
MIN_PLAUSIBLE_ROWS = 200


class DotGGSource(CardSource):
    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        name: str = "dotgg",
        timeout: float = DEFAULT_TIMEOUT,
        cache_dir: Path | None = None,
        client: HttpClient | None = None,
    ):
        self.name = name
        self._url = url
        self._cache_dir = cache_dir
        self._http = client or HttpClient(
            timeout=timeout, min_interval=0.25, referer="https://riftbound.gg/"
        )

    def fetch(self) -> FetchResult:
        started = time.perf_counter()
        result = FetchResult(name=self.name)
        try:
            payload = self._download()
            if not isinstance(payload, list):
                raise ValueError(
                    f"expected a JSON array of cards, got {type(payload).__name__}"
                )
            if len(payload) < MIN_PLAUSIBLE_ROWS:
                raise ValueError(
                    f"only {len(payload)} rows returned, below the plausibility floor of "
                    f"{MIN_PLAUSIBLE_ROWS} — treating as a failed fetch rather than a "
                    f"shrunken card pool"
                )
            for row in payload:
                if not isinstance(row, dict):
                    continue
                result.fetched += 1
                card = self._to_raw(row)
                if card is not None:
                    result.cards.append(card)
        except Exception as exc:  # adapters never raise -- see base.CardSource
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # -- internals --------------------------------------------------------------

    def _download(self) -> Any:
        raw = self._http.get(self._url)
        self._cache(raw)
        if raw[:1] not in (b"{", b"["):
            raise RuntimeError(f"non-JSON response from {self._url}: {raw[:40]!r}")
        return json.loads(raw.decode("utf-8"))

    def _cache(self, raw: bytes) -> None:
        """Keep the raw response for replay and diffing. Never read back automatically.

        Silently serving a stale cache when a fetch fails is how data problems hide;
        the cache is for a human debugging a bad ingest.
        """
        if self._cache_dir is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
            (self._cache_dir / f"{self.name}-{stamp}.json").write_bytes(raw)
        except OSError:
            pass  # caching is a convenience, never a reason to fail an ingest

    @staticmethod
    def _to_raw(row: dict[str, Any]) -> RawCard | None:
        card_code = str(row.get("id") or "").strip()
        # "VEN-150" -> number "150". Upstream sometimes pads the set code ("SGN ").
        number = card_code.split("-", 1)[1].strip() if "-" in card_code else ""

        return RawCard(
            source="dotgg",
            slug=str(row.get("slug") or "").strip(),
            title=str(row.get("name") or "").strip(),
            set_name=str(row.get("set_name") or "").strip(),
            card_number=number,
            rarity=str(row.get("rarity") or "").strip(),
            promo=str(row.get("promo") or "0").strip() not in {"", "0", "false", "False"},
            image_url=str(row.get("image") or "").strip(),
            card_type=str(row.get("type") or "").strip(),
            super_type=str(row.get("supertype") or "").strip(),
            # Already a list here; older exports pack it as "FuryChaos".
            color=row.get("color") or "",
            cost=row.get("cost"),
            might=row.get("might"),
            tags=tuple(str(t).strip() for t in (row.get("tags") or []) if str(t).strip()),
            effect=str(row.get("effect") or ""),
            flavor=str(row.get("flavor") or ""),
            banned=str(row.get("banned") or "0").strip() not in {"", "0", "false", "False"},
        )
