"""Tournament source: Riftools' published release store.

Riftools publishes its read model as plain static JSON -- no API key, no HTML to parse,
no browser. Three things make it the best-shaped deck source we have:

* **Scale.** 25,336 parsed decklists across two set windows at the time of writing,
  against the 3,332 TopDeck gives us and the 2,501 the local RiftDecks service holds.
* **Reach.** It indexes the Chinese circuit, which is most of competitive Riftbound and
  almost none of TopDeck. Whole-field coverage matters beyond the deck count: a top-8
  sample tells you what won, and only a whole field tells you what was *played*, which
  is what a play rate is supposed to measure.
* **Shape.** Zones arrive separated and the **chosen champion is an explicit field**
  rather than something to infer from champion tags. Inference is what attributed a
  Kennen deck to Nocturne in our own archive.

**The store moved, and the old one is gone.** Until 2026 this read ``/public-snapshots``;
that path now answers **410 Gone**, not a redirect, so every harvest failed from the day
it was retired. Discovery now goes through ``riftools_release`` -- the pointer, the
manifest, the object -- and this module is only about turning a deck object into the
payload shape ``meta_normalize`` already accepts.

**Volume.** A cold harvest is one request per deck, so caching is not an optimisation
here, it is the design. The new store names every object by its own SHA-256, so the
cache is keyed on that hash: an unchanged deck is the same object and is served from
disk without a request, and a deck whose contents change gets a new hash and is
refetched. The cache can no longer go stale, which the old url-keyed one could.

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
from .riftools_release import DEFAULT_BASE_URL, ReleaseReader

#: Artifacts inside a set's manifests that this source reads.
DECKS_ARTIFACT = "{set}__decks"
DECK_DETAIL_ARTIFACT = "{set}__deck_detail__{deck}"

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

#: Zone name in the deck object -> zone name `meta_normalize` expects. The new payload
#: separates the zones itself, so nothing is inferred from a card's type any more -- the
#: old map existed only because every card used to arrive in one flat list.
_ZONES = {
    "main_deck": "main",
    "runes": "runes",
    "battlefields": "battlefields",
    "sideboard": "sideboard",
}

#: Placements arrive as text: "1st", "2nd", "Top 8". A bracket is not a finish, so
#: "Top 8" is recorded as 8 -- the conservative bound, meaning "no worse than 8th" --
#: rather than inventing a precision the source does not have.
_PLACEMENT = re.compile(r"(\d+)")


def parse_placement(value: object) -> int:
    """``"1st"`` -> 1, ``"Top 8"`` -> 8, anything unreadable -> 0.

    Zero means *unknown*, which downgrades a deck from "placed" to "entered" rather than
    claiming a finish nobody recorded.
    """
    text = str(value or "").strip()
    if not text:
        return 0
    found = _PLACEMENT.search(text)
    return int(found.group(1)) if found else 0


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
            reader = ReleaseReader(base_url=self._base, client=self._http)
            release = reader.current()
            result.notes.append(
                f"release {release.release_id or '?'} "
                f"({', '.join(release.ordered_sets()) or 'no sets'})"
            )
            index = self._deck_index(reader, release, result)
            wanted = self._select(index, result)
            self._harvest(wanted, result)
            result.fetched = len(result.decks)
        except Exception as exc:  # sources never raise
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # -- internals -------------------------------------------------------------

    def _deck_index(
        self, reader: ReleaseReader, release, result: RiftoolsResult
    ) -> dict[str, str]:
        """``deck id -> object path`` across every set the release publishes.

        Every set, not just the newest: this is an archive, and dropping set 3 the day
        set 4 opens would throw away two thirds of it. The ids are globally unique, so
        the sets merge into one index.
        """
        index: dict[str, str] = {}
        for set_name in release.ordered_sets():
            core_path = release.manifest_path(set_name, "core")
            details_path = release.manifest_path(set_name, "details")
            if not core_path or not details_path:
                result.notes.append(f"{set_name}: no core/details manifest")
                continue
            try:
                core = reader.manifest(core_path)
                decks = reader.artifact(core, DECKS_ARTIFACT.format(set=set_name))
                details = reader.manifest(details_path)
            except HttpError as exc:
                result.notes.append(f"{set_name}: {exc}")
                continue

            ids = (decks or {}).get("deck_detail_ids") or []
            found = 0
            for deck_id in ids:
                key = DECK_DETAIL_ARTIFACT.format(set=set_name, deck=deck_id)
                path = reader.object_path(details, key)
                if path:
                    index[str(deck_id)] = path
                    found += 1
            result.notes.append(f"{set_name}: {found} decklist(s) indexed")
        if not index:
            raise HttpError("no set in this release publishes a deck index")
        return index

    def _select(
        self, index: dict[str, str], result: RiftoolsResult
    ) -> list[tuple[str, str]]:
        """Which decks to fetch this run.

        A deck's own event is not known until its object is read, so ``--since`` cannot
        be applied here; the cap is the only filter, and a cached object costs nothing.
        """
        wanted = [(deck_id, path) for deck_id, path in index.items() if path]
        result.requested = len(wanted)
        if len(wanted) > self._max:
            result.notes.append(f"capped at {self._max} of {len(wanted)} deck(s)")
            wanted = wanted[: self._max]
        return wanted

    def _cache_path(self, object_path: str) -> Path | None:
        """Keyed on the object's own hash, which the store puts in its path.

        Content-addressed, so the cache cannot go stale: a deck that changed is a
        different object with a different name, and an unchanged one is the same file
        for ever. The old cache keyed on the deck's URL and had to assume a parsed deck
        never changed.
        """
        if self._cache_dir is None:
            return None
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", object_path)[-160:]
        return self._cache_dir / "riftools" / "objects" / f"{safe}.json"

    def _read_one(self, path: str) -> tuple[dict[str, Any] | None, bool]:
        """One deck snapshot, from cache when we already have it.

        Returns ``(payload, from_cache)``. A parsed deck snapshot describes a list
        registered at a finished event and does not change, so a cache hit is served
        without touching the network.
        """
        cached = self._cache_path(path)
        if cached is not None and cached.is_file():
            try:
                return json.loads(cached.read_text(encoding="utf-8")), True
            except (OSError, json.JSONDecodeError):
                pass  # a corrupt cache entry is refetched, not fatal
        payload = self._http.get_json(f"{self._base}/release-v3/{path.lstrip('/')}")
        if cached is not None and isinstance(payload, dict):
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(payload), encoding="utf-8")
            except OSError:
                pass  # an unwritable cache slows the next run; it does not break this one
        return (payload if isinstance(payload, dict) else None), False

    def _harvest(self, wanted: list[tuple[str, str]], result: RiftoolsResult) -> None:
        def one(item: tuple[str, str]) -> tuple[str, dict[str, Any] | None, bool]:
            deck_id, path = item
            try:
                payload, cached = self._read_one(path)
                return deck_id, payload, cached
            except HttpError:
                return deck_id, None, False

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            rows = list(pool.map(one, wanted))

        # Event rows are built from the decks themselves. The deck object carries its
        # own event's name, date, size and region, so a separate tournament index would
        # be a second request and a second shape to keep in step for no new fact.
        events: dict[str, dict[str, Any]] = {}
        published: dict[str, int] = {}
        for deck_id, payload, cached in rows:
            if cached:
                result.from_cache += 1
            if not payload:
                continue
            shaped = self._shape(deck_id, payload)
            if shaped is None:
                result.unparsed += 1
                continue
            deck_payload, standing, event = shaped
            result.decks.append(deck_payload)
            if standing:
                result.standings.append(standing)
            url = str(event.get("tournament_url") or "")
            if url:
                events.setdefault(url, event)
                published[url] = published.get(url, 0) + 1

        for url, event in events.items():
            name = str(event.get("name") or "")
            result.tournaments.append(
                {
                    "slug": event_slug(url, name),
                    "tournament_id": url,
                    "name": name,
                    "date": str(event.get("date") or ""),
                    "format": "constructed",
                    "players": _int(event.get("players")),
                    "organizer": str(event.get("region") or ""),
                    "winner": "",
                    "decks_published": published.get(url, 0),
                }
            )
        result.notes.append(
            f"{len(result.decks)} deck(s) over {len(result.tournaments)} event(s); "
            f"{result.from_cache} from cache, {result.unparsed} unparsed"
        )

    def _shape(
        self, deck_id: str, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]] | None:
        """One deck object into the payload shape ``meta_normalize`` already accepts.

        The store separates the zones itself, so each one is read straight across rather
        than inferred from card types. Cards are keyed by collector code where they have
        one -- the TopDeck-shaped path, so the champion fold, the nominatability check
        and the battlefield repairs all apply without a second implementation -- and the
        legend and chosen champion arrive as *names*, which is what ``_named_zones`` is
        for.
        """
        deck = payload.get("deck") or {}
        if str(deck.get("parse_status") or "") != "parsed":
            return None

        zones: dict[str, dict[str, int]] = {}
        names: dict[str, dict[str, int]] = {}
        for source_zone, zone in _ZONES.items():
            for card in payload.get(source_zone) or []:
                if not isinstance(card, dict):
                    continue
                count = _int(card.get("count"))
                if count <= 0:
                    continue
                code = strip_code(card.get("image_public_code"))
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

        # Named, not coded: the store gives these as display names only. Taking the
        # source's word on the champion is the whole reason this source is preferred --
        # inference is what once attributed a Kennen deck to Nocturne.
        for key, zone in (("legend", "legend"), ("champion", "champion")):
            value = str(payload.get(key) or deck.get(key) or "").strip()
            if value:
                names.setdefault(zone, {})[value] = 1

        tournament_url = str(deck.get("tournament_url") or "")
        slug = _slugify(str(deck.get("deck_url") or deck_id)) or str(deck_id)
        place = parse_placement(deck.get("rank") or deck.get("placement"))

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
        if tournament_url and place > 0:
            standing = {
                "tournament_slug": event_slug(
                    tournament_url, str(deck.get("tournament_name") or "")
                ),
                "place": place,
                "player_name": str(deck.get("player_name") or "").strip(),
                "deck_slug": slug,
                "record": str(deck.get("record") or ""),
            }

        event = {
            "tournament_url": tournament_url,
            "name": str(deck.get("tournament_name") or ""),
            "date": str(deck.get("event_date") or ""),
            "players": deck.get("player_count"),
            "region": str(deck.get("region") or ""),
        }
        return deck_payload, standing, event
