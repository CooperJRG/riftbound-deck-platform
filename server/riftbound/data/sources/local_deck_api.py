"""Community decks from a local Riftbound Deck API.

Fills the gap TopDeck cannot: TopDeck carries tournament results, this carries the
curated community pool — quality-scored, normalised card-by-card, and refreshed on its
own schedule.

Two things make it a good fit:

* **It is already quality-filtered.** The crawl-and-guess problem on the community side
  was that ~86% of published decks are abandoned scratch saves. This service scores
  decks and exposes ``min_quality``, so the filtering happens before we ever see them.
* **Names resolve cleanly.** Cards arrive by *name*, not collector code — and the names
  use commas ("Irelia, Blade Dancer") where the card catalogue uses dashes
  ("Irelia - Blade Dancer"). Because ``card_id`` is punctuation-insensitive by design,
  all 758 card lines in a sample resolved without a single miss.

**Provenance.** The service mirrors RiftDecks; each deck keeps its ``source_url``, and
the snapshot records the attribution owed. Note that RiftDecks' own ``robots.txt``
objects to competing services crawling it — this adapter reads a *local* service the
operator runs, and does not crawl riftdecks.com. Redistributing this data is a decision
for whoever runs that service.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .http import HttpClient, HttpError

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
#: Upper bound on a single harvest, so a runaway response cannot exhaust memory. Far
#: above any plausible local library; it exists to bound a bug, not to shape a harvest.
SANE_MAX = 20_000

#: The service caps a page at 100.
PAGE_SIZE = 100

ATTRIBUTION = {
    "source": "RiftDecks",
    "url": "https://riftdecks.com",
    "text": "Community decks via RiftDecks",
}

#: Card sections, mapped onto our zones. The champion is *also* part of the main deck
#: under Riftbound's rules, which :func:`section_zones` handles.
SECTION_ZONES = {
    "legend": "legend",
    "champion": "champion",
    "unit": "main",
    "gear": "main",
    "spell": "main",
    "battlefields": "battlefields",
    "battlefield": "battlefields",
    "runes": "runes",
    "rune": "runes",
    "sideboard": "sideboard",
}


def base_url_from_env() -> str:
    return str(os.getenv("RB_LOCAL_DECK_API", "") or DEFAULT_BASE_URL).strip().rstrip("/")


@dataclass
class LocalDeckResult:
    name: str = "local-deck-api"
    tournaments: list[dict[str, Any]] = field(default_factory=list)
    standings: list[dict[str, Any]] = field(default_factory=list)
    decks: list[dict[str, Any]] = field(default_factory=list)
    fetched: int = 0
    ok: bool = True
    error: str = ""
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)


def _int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


#: "1st", "2nd", "T8", "3rd-4th" -> a number. 0 when there is no usable finish.
def parse_placement(value: object) -> int:
    text = str(value or "").strip().lower()
    if not text:
        return 0
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    return int(digits) if digits else 0


def section_zones(cards: Sequence[dict[str, Any]]) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Group card lines by zone, keyed by card *name*.

    Returns ``(zones, unknown_sections)``. An unrecognised section is reported rather
    than dropped, so a new one appearing upstream cannot quietly remove cards.
    """
    zones: dict[str, dict[str, int]] = {}
    unknown: list[str] = []
    for line in cards:
        if not isinstance(line, dict):
            continue
        section = str(line.get("section") or "").strip().casefold()
        zone = SECTION_ZONES.get(section)
        if zone is None:
            if section:
                unknown.append(section)
            continue
        name = str(line.get("card_name") or "").strip()
        qty = _int(line.get("quantity"), 0)
        if not name or qty <= 0:
            continue
        bucket = zones.setdefault(zone, {})
        bucket[name] = bucket.get(name, 0) + qty
    return zones, sorted(set(unknown))


class LocalDeckApiSource:
    """Community decks from the local Riftbound Deck API."""

    name = "local-deck-api"

    def __init__(
        self,
        *,
        base_url: str = "",
        min_quality: int = 0,
        since: str = "",
        limit: int = 0,
        workers: int = 8,
        timeout: float = 30.0,
        cache_dir: Path | None = None,
        client: HttpClient | None = None,
    ):
        self._base = (base_url or base_url_from_env()).rstrip("/")
        self._min_quality = max(0, min_quality)
        self._since = since
        # 0 means "whatever the service has". This is a local process on the same
        # machine with no rate limit to respect, so a fixed cap buys nothing and costs
        # data: the service grows every few hours and a cap silently drops the newest
        # decks off the end of a quality sort. A ceiling still exists (SANE_MAX) to
        # bound a pathological response.
        self._limit = max(1, limit) if limit else 0
        self._workers = max(1, workers)
        self._cache_dir = cache_dir
        # A local service: no throttle needed, but retries still cover a restart mid-run.
        self._http = client or HttpClient(
            timeout=timeout, min_interval=0.0, max_attempts=3, base_backoff=0.25
        )

    def fetch(self) -> LocalDeckResult:
        started = time.perf_counter()
        result = LocalDeckResult(name=self.name)
        try:
            summaries = self._list(result)
            payloads = self._hydrate(summaries, result)
            self._shape(payloads, result)
            result.fetched = len(result.decks)
            self._cache(payloads)
        except Exception as exc:  # sources never raise
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
            if "could not reach" in result.error or "urlopen" in result.error:
                result.error += (
                    f" — is the deck API running at {self._base}? "
                    f"Set RB_LOCAL_DECK_API to point elsewhere."
                )
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # -- internals -------------------------------------------------------------

    def _query(self, offset: int, limit: int) -> str:
        # Sent even when it is 0. Omitting it does not mean "no floor" to the service --
        # it means "use your own default", which is 60. A harvest configured for no
        # floor was therefore receiving 1133 of the service's 2501 decks, and the 45
        # complete lists from a 1280-player regional, scoring 57-62, were nearly all
        # dropped before this code ever saw them.
        parts = [
            f"limit={limit}",
            f"offset={offset}",
            "sort=quality",
            f"min_quality={self._min_quality}",
        ]
        if self._since:
            parts.append(f"since={self._since}")
        return f"{self._base}/v1/decks?" + "&".join(parts)

    def _list(self, result: LocalDeckResult) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        offset = 0
        total = 0
        ceiling = self._limit or SANE_MAX

        while len(summaries) < ceiling:
            page = self._http.get_json(self._query(offset, min(PAGE_SIZE, ceiling - offset)))
            if not isinstance(page, dict):
                raise HttpError(f"unexpected response from {self._base}/v1/decks")
            rows = page.get("decks") or []
            summaries.extend(r for r in rows if isinstance(r, dict))
            total = _int(page.get("total")) or total
            offset += len(rows)
            if not rows or offset >= total:
                break

        kept = summaries[:ceiling]
        result.notes.append(
            f"{len(kept)} of {total} deck summaries from {self._base}"
            if total
            else f"{len(kept)} deck summaries from {self._base}"
        )
        # Never drop decks quietly. A harvest that silently returns less than the
        # service holds is the exact failure this project was rebuilt to avoid, and it
        # gets worse on its own as the service grows.
        if total and len(kept) < total:
            result.notes.append(
                f"TRUNCATED: {total - len(kept)} decks not fetched (limit {ceiling}). "
                f"Raise --local-limit, or leave it at 0 to take everything."
            )
        return kept

    def _hydrate(
        self, summaries: Sequence[dict[str, Any]], result: LocalDeckResult
    ) -> list[dict[str, Any]]:
        """Fetch each deck's card list. Local, so parallel and unthrottled."""
        missing = 0

        def one(summary: dict[str, Any]) -> dict[str, Any] | None:
            deck_id = summary.get("id")
            if deck_id is None:
                return None
            try:
                full = self._http.get_json(f"{self._base}/v1/decks/{deck_id}")
            except HttpError:
                return None
            return full if isinstance(full, dict) else None

        out: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            for payload in pool.map(one, summaries):
                if payload is None:
                    missing += 1
                else:
                    out.append(payload)
        if missing:
            result.notes.append(f"{missing} deck(s) could not be fetched")
        return out

    def _shape(self, payloads: Sequence[dict[str, Any]], result: LocalDeckResult) -> None:
        unknown_sections: set[str] = set()
        events: dict[str, dict[str, Any]] = {}
        no_cards = 0

        for payload in payloads:
            deck_id = str(payload.get("id") or "").strip()
            if not deck_id:
                continue
            zones, unknown = section_zones(payload.get("cards") or [])
            unknown_sections.update(unknown)
            if not zones:
                no_cards += 1
                continue

            slug = f"riftdecks::{deck_id}"
            place = parse_placement(payload.get("placement"))
            event_name = str(payload.get("event") or "").strip()
            players = _int(payload.get("event_players"))
            published = str(payload.get("published_date") or "").strip()

            # An event only becomes a tournament for our purposes when it is named and
            # this deck actually finished somewhere in it.
            event_slug = ""
            if event_name and place > 0:
                event_slug = f"riftdecks::{_slugify(event_name)}"
                events.setdefault(event_slug, {
                    "tournament_id": event_slug,
                    "slug": event_slug,
                    "name": event_name,
                    "date": published,
                    "format": str(payload.get("metagame") or "").strip(),
                    "players": players,
                    "organizer": str(payload.get("venue") or "").strip(),
                    "winner": "",
                    "decks_published": 0,
                })
                events[event_slug]["decks_published"] += 1
                events[event_slug]["players"] = max(events[event_slug]["players"], players)
                if place == 1:
                    events[event_slug]["winner"] = str(payload.get("player") or "").strip()
                result.standings.append({
                    "tournament_slug": event_slug,
                    "tournament_name": event_name,
                    "tournament_date": published,
                    "field_size": players,
                    "place": place,
                    "player_name": str(payload.get("player") or "").strip(),
                    "record": str(payload.get("record") or "").strip(),
                    "deck_slug": slug,
                })

            result.decks.append({
                "_slug": slug,
                "_named_zones": zones,
                "_source": "riftdecks",
                "_tournament_url": str(payload.get("source_url") or ""),
                "_quality": _float(payload.get("quality_score")),
                "humanname": str(payload.get("deck_name") or "").strip(),
                "public": "1",
                "is_tournament": "1" if event_slug else "0",
                "authornick": str(payload.get("player") or "").strip(),
                "published_date": published,
                "format": str(payload.get("metagame") or "").strip(),
                "views": 0,
            })

        result.tournaments = list(events.values())
        result.notes.append(
            f"{len(result.decks)} decks, {len(result.tournaments)} events, "
            f"{len(result.standings)} placed"
            + (f", {no_cards} with no card list" if no_cards else "")
        )
        if unknown_sections:
            result.notes.append(
                f"unrecognised card section(s) {sorted(unknown_sections)} — those cards "
                f"were skipped; add them to SECTION_ZONES"
            )

    def _cache(self, payload: object) -> None:
        if self._cache_dir is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
            (self._cache_dir / f"riftdecks-decks-{stamp}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError:
            pass


def _slugify(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
