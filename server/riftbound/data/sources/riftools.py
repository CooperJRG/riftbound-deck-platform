"""Tournament source: Riftools' public snapshots.

Riftools publishes its read model as plain static JSON under ``/public-snapshots`` --
no API key, no HTML to parse, no browser. Three things make it the best-shaped deck
source we have:

* **Scale.** 14,765 parsed decklists across 146 events at the time of writing, against
  the 3,332 TopDeck gives us and the 2,501 the local RiftDecks service holds.
* **Reach.** It indexes the Chinese circuit, which is most of competitive Riftbound and
  almost none of TopDeck. One event -- the S4 Wuhan Regional Open -- is 1,280 published
  lists, which is the entire field rather than a top cut. Whole-field coverage matters
  beyond the deck count: a top-8 sample tells you what won, and only a whole field tells
  you what was *played*, which is what a play rate is supposed to measure.
* **Shape.** Zones arrive separated, and the **chosen champion is an explicit field**
  rather than something to infer from champion tags. Inference is what attributed a
  Kennen deck to Nocturne in our own archive.

**Volume.** A cold harvest is one request per deck, so caching is not an optimisation
here, it is the design. A deck snapshot is immutable once ``parse_status`` reads
``parsed`` -- it describes a list somebody registered at an event that has finished --
so a cached file is served without a request at all, and only decks new since the last
run cost anything. The rate limiter is left tight enough that even a cold run is a
steady trickle rather than a flood.

**Attribution.** :data:`ATTRIBUTION` carries the credit, the snapshot manifest records
it, and the meta view renders it, exactly as for TopDeck.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dotgg_meta import MetaFetchResult
from .http import HttpClient, HttpError

DEFAULT_BASE_URL = "https://www.riftools.app"
MANIFEST_PATH = "/public-snapshots/manifest.current.json"

ATTRIBUTION = {
    "source": "Riftools",
    "url": "https://www.riftools.app",
    "text": "Tournament decklists via Riftools",
}

#: Upper bound on one harvest, so a manifest that suddenly grows by an order of
#: magnitude cannot turn a routine refresh into an hour of requests. It bounds a
#: surprise, not a policy -- raise it deliberately rather than trip over it.
SANE_MAX = 60_000

#: Collector codes arrive as ``OGN-042/298`` -- the printing, then the set's card count.
#: Our catalogue keys on ``OGN-042``. Measured on a full list, 2 of 32 codes resolved
#: with the suffix left on and 32 of 32 with it stripped.
_CODE_SUFFIX = re.compile(r"/\d+$")

#: Which riftools ``card_type`` belongs in which deck zone. The champion and legend
#: arrive as their own types, which is what lets the normaliser take the source's word
#: on the nomination instead of guessing it.
_ZONE_OF_TYPE = {
    "legend": "legend",
    "champion": "champion",
    "chosen champion": "champion",
    "runes": "runes",
    "rune": "runes",
    "battlefield": "battlefields",
    "battlefields": "battlefields",
    "sideboard": "sideboard",
}


def strip_code(code: object) -> str:
    """``OGN-042/298`` -> ``OGN-042``."""
    return _CODE_SUFFIX.sub("", str(code or "").strip())


def _int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _slugify(text: str) -> str:
    """A stable, filesystem- and URL-safe key for an event.

    Event names carry Chinese characters and punctuation; ``tournament_url`` is a
    ``wechat://`` or ``https://`` URL. Neither is usable as a slug directly, so this
    keeps the ASCII skeleton and falls back to the URL's own tail when a name reduces to
    nothing -- which every all-Chinese event name does.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return cleaned[:120]


def event_slug(tournament_url: str, name: str) -> str:
    """One slug per event, stable across runs.

    Keyed on the URL rather than the name: two "S4 Guangzhou City Challenge" events a
    week apart share a name and must not share a slug.
    """
    tail = _slugify(str(tournament_url or "").split("://")[-1])
    named = _slugify(name)
    if named and tail:
        return f"{named}-{tail[-24:]}"
    return named or tail or "unknown-event"


@dataclass
class RiftoolsResult(MetaFetchResult):
    """A harvest, plus what it cost."""

    requested: int = 0
    from_cache: int = 0
    unparsed: int = 0
    events: dict[str, dict[str, Any]] = field(default_factory=dict)


class RiftoolsSource:
    """Tournaments, standings and decklists from Riftools' static snapshots."""

    name = "riftools"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        cache_dir: Path | None = None,
        max_decks: int = 0,
        since: str = "",
        workers: int = 6,
        timeout: float = 30.0,
        min_interval: float = 0.04,
        client: HttpClient | None = None,
    ):
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._max = min(max_decks, SANE_MAX) if max_decks else SANE_MAX
        self._since = str(since or "").strip()
        self._workers = max(1, workers)
        # A steady trickle rather than a flood. The limiter is per host and enforced
        # across threads, so the worker count changes latency, not the request rate.
        self._http = client or HttpClient(
            timeout=timeout, min_interval=min_interval, max_attempts=4, base_backoff=0.5
        )

    # -- the harvest -----------------------------------------------------------

    def fetch(self) -> RiftoolsResult:
        started = time.perf_counter()
        result = RiftoolsResult(name=self.name)
        try:
            manifest = self._http.get_json(f"{self._base}{MANIFEST_PATH}")
            events = self._events(manifest, result)
            index = self._deck_index(manifest)
            wanted = self._select(index, events, result)
            self._harvest(wanted, events, result)
            result.fetched = len(result.decks)
        except Exception as exc:  # sources never raise
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # -- internals -------------------------------------------------------------

    def _chunk_urls(self, manifest: Any, family: str) -> list[str]:
        """Every chunk URL for one snapshot family, or the whole-file fallback."""
        snapshots = (manifest or {}).get("snapshots") or {}
        entry = snapshots.get(family) or {}
        chunked = entry.get("chunked") or {}
        chunks = chunked.get("chunks") or []
        if chunks:
            return [f"{self._base}{c['url']}" for c in chunks if c.get("url")]
        return [f"{self._base}{entry['url']}"] if entry.get("url") else []

    def _events(self, manifest: Any, result: RiftoolsResult) -> dict[str, dict[str, Any]]:
        """Event metadata, keyed by ``tournament_url``.

        Read from the tournament chunks rather than the per-event detail files: seven
        small requests describe every event, where the detail files are one request each
        and repeat the standings the deck files already carry.
        """
        events: dict[str, dict[str, Any]] = {}
        for family in ("tournaments", "tournaments-set4"):
            for url in self._chunk_urls(manifest, family):
                try:
                    payload = self._http.get_json(url)
                except HttpError as exc:
                    result.notes.append(f"tournament chunk failed: {exc}")
                    continue
                for row in _items(payload, "tournaments"):
                    key = str(row.get("tournament_url") or "")
                    if key:
                        events.setdefault(key, row)
        result.notes.append(f"{len(events)} event(s) described")
        return events

    def _deck_index(self, manifest: Any) -> dict[str, str]:
        """``deck_url -> snapshot path`` for every published decklist."""
        details = (manifest or {}).get("deck_details") or {}
        index_url = details.get("index_url")
        if not index_url:
            raise HttpError("manifest carries no deck_details.index_url")
        payload = self._http.get_json(f"{self._base}{index_url}")
        index = (payload or {}).get("details") or {}
        if not isinstance(index, dict):
            raise HttpError("deck-details index is not a mapping")
        return {str(k): str(v) for k, v in index.items()}

    def _select(
        self,
        index: dict[str, str],
        events: dict[str, dict[str, Any]],
        result: RiftoolsResult,
    ) -> list[tuple[str, str]]:
        """Which decks to fetch this run.

        A deck's own event is not known until its file is read, so ``--since`` cannot be
        applied here for decks that are not already cached. Cached files are filtered on
        their recorded date, and everything else is taken in index order up to the cap.
        """
        wanted = [(deck_url, path) for deck_url, path in index.items() if path]
        result.requested = len(wanted)
        if len(wanted) > self._max:
            result.notes.append(f"capped at {self._max} of {len(wanted)} deck(s)")
            wanted = wanted[: self._max]
        return wanted

    def _cache_path(self, deck_url: str) -> Path | None:
        if self._cache_dir is None:
            return None
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", deck_url)[-160:]
        return self._cache_dir / "riftools" / "decks" / f"{safe}.json"

    def _read_one(self, deck_url: str, path: str) -> tuple[dict[str, Any] | None, bool]:
        """One deck snapshot, from cache when we already have it.

        Returns ``(payload, from_cache)``. A parsed deck snapshot describes a list
        registered at a finished event and does not change, so a cache hit is served
        without touching the network.
        """
        cached = self._cache_path(deck_url)
        if cached is not None and cached.is_file():
            try:
                return json.loads(cached.read_text(encoding="utf-8")), True
            except (OSError, json.JSONDecodeError):
                pass  # a corrupt cache entry is refetched, not fatal
        payload = self._http.get_json(f"{self._base}{path}")
        if cached is not None and isinstance(payload, dict):
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(payload), encoding="utf-8")
            except OSError:
                pass  # an unwritable cache slows the next run; it does not break this one
        return (payload if isinstance(payload, dict) else None), False

    def _harvest(
        self,
        wanted: list[tuple[str, str]],
        events: dict[str, dict[str, Any]],
        result: RiftoolsResult,
    ) -> None:
        def one(item: tuple[str, str]) -> tuple[str, dict[str, Any] | None, bool]:
            deck_url, path = item
            try:
                payload, cached = self._read_one(deck_url, path)
                return deck_url, payload, cached
            except HttpError:
                return deck_url, None, False

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            rows = list(pool.map(one, wanted))

        seen_events: dict[str, int] = {}
        for deck_url, payload, cached in rows:
            if cached:
                result.from_cache += 1
            if not payload:
                continue
            shaped = self._shape(deck_url, payload, events)
            if shaped is None:
                result.unparsed += 1
                continue
            deck_payload, standing, tournament_url = shaped
            result.decks.append(deck_payload)
            if standing:
                result.standings.append(standing)
            if tournament_url:
                seen_events[tournament_url] = seen_events.get(tournament_url, 0) + 1

        for tournament_url, published in seen_events.items():
            row = events.get(tournament_url) or {}
            name = str(row.get("name") or "")
            result.tournaments.append(
                {
                    "slug": event_slug(tournament_url, name),
                    "tournament_id": tournament_url,
                    "name": name,
                    "date": str(row.get("event_date") or ""),
                    "format": "constructed",
                    "players": _int(row.get("players")),
                    "organizer": str(row.get("region") or ""),
                    "winner": "",
                    "decks_published": published,
                }
            )
        result.notes.append(
            f"{len(result.decks)} deck(s) over {len(result.tournaments)} event(s); "
            f"{result.from_cache} from cache, {result.unparsed} unparsed"
        )

    def _shape(
        self,
        deck_url: str,
        payload: dict[str, Any],
        events: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any] | None, str] | None:
        """One snapshot into the payload shape ``meta_normalize`` already accepts.

        Zones keyed by collector code, which is the TopDeck-shaped path -- so the
        champion fold, the nominatability check and the battlefield repairs all apply
        without a second implementation.
        """
        deck = payload.get("deck") or {}
        if str(deck.get("parse_status") or "") != "parsed":
            return None
        cards = payload.get("cards") or []
        if not isinstance(cards, list) or not cards:
            return None

        zones: dict[str, dict[str, int]] = {}
        names: dict[str, dict[str, int]] = {}
        for card in cards:
            if not isinstance(card, dict):
                continue
            count = _int(card.get("count"))
            if count <= 0:
                continue
            card_type = str(card.get("card_type") or "").strip().lower()
            zone = _ZONE_OF_TYPE.get(card_type, "main")
            code = strip_code(card.get("public_code"))
            name = str(card.get("card_name") or "").strip()
            if code:
                bucket = zones.setdefault(zone, {})
                bucket[code] = bucket.get(code, 0) + count
            elif name:
                # No code on this row; the name path resolves it instead of losing it.
                bucket = names.setdefault(zone, {})
                bucket[name] = bucket.get(name, 0) + count

        if not zones and not names:
            return None

        tournament_url = str(deck.get("tournament_url") or "")
        event = events.get(tournament_url) or {}
        slug = _slugify(deck_url.split("://")[-1]) or deck_url
        rank = _int(deck.get("rank")) or _int(deck.get("placement"))

        deck_payload: dict[str, Any] = {
            "_slug": slug,
            "public": "1",
            "_source": self.name,
            "_zones": zones,
            "_tournament_url": tournament_url,
            "humanname": str(deck.get("deck_name") or "").strip(),
            "authornick": str(deck.get("player_name") or "").strip(),
            "published_date": str(deck.get("event_date") or ""),
            "is_tournament": "1",
        }
        if names:
            deck_payload["_named_zones"] = names

        standing = None
        if tournament_url and rank > 0:
            standing = {
                "tournament_slug": event_slug(tournament_url, str(event.get("name") or "")),
                "place": rank,
                "player_name": str(deck.get("player_name") or "").strip(),
                "deck_slug": slug,
                "record": str(deck.get("record") or ""),
            }
        return deck_payload, standing, tournament_url


def _items(payload: Any, key: str) -> list[dict[str, Any]]:
    """Rows out of a snapshot chunk.

    Chunks come in two shapes -- ``{"items": [...]}`` and ``{"<key>": {"items": [...]}}``
    -- and the manifest does not say which a given family uses.
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for candidate in (payload.get("items"), (payload.get(key) or {}).get("items")):
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return []
