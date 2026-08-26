"""Tournament source: the TopDeck.gg v2 API.

The primary source for competitive decks, and the reason a meta refresh is now seconds
rather than minutes. One `POST /v2/tournaments` returns every event in a window *with
its decklists attached*, where the previous approach needed one HTTP request per deck
and could only reach the ~1% of standings that published a slug.

Measured against the live API:

===========================  ======  =========  =========  ======
window                       events  standings  decklists  time
===========================  ======  =========  =========  ======
180 days                        172       4421       2861   4.7 s
14 days (routine refresh)        20        557        391   0.9 s
180 days, 32+ players            27       2999       2538   2.9 s
===========================  ======  =========  =========  ======

The payload is also better shaped than anything scraped: ``deckObj`` arrives with zones
already separated — including the **chosen champion**, which otherwise has to be
inferred from champion tags — and every entry carries a collector code, which is our
join key onto the catalogue.

**Attribution.** TopDeck's terms require a visible credit and link back on any project
using the API. :data:`ATTRIBUTION` carries it, the snapshot manifest records it, and the
meta view renders it.

**Credentials.** The key is read from ``RB_TOPDECK_API_KEY`` and never written to disk,
logged, or included in a cached response.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any

from .http import HttpClient, HttpError

API_URL = "https://topdeck.gg/api/v2/tournaments"
GAME = "Riftbound"
DEFAULT_FORMAT = "Constructed"

#: Required by the TopDeck.gg API terms of use.
ATTRIBUTION = {
    "source": "TopDeck.gg",
    "url": "https://topdeck.gg",
    "text": "Tournament data from TopDeck.gg",
}

#: Fields to request. Asking for `decklist` also returns the structured `deckObj`.
COLUMNS = ("name", "decklist", "wins", "losses", "draws", "winRate")

#: Upstream zone labels, mapped onto ours. Nearly every deck uses the first spelling,
#: but a handful use these variants, and a zone we do not recognise would otherwise be
#: silently dropped from an imported list.
ZONE_ALIASES = {
    "legend": "legend",
    "champion": "champion",
    "runes": "runes",
    "rune pool": "runes",
    "battlefields": "battlefields",
    "battlefield": "battlefields",
    "mainboard": "main",
    "main deck": "main",
    "maindeck": "main",
    "sideboard": "sideboard",
}

#: Not a zone — upstream stores provenance under this key inside the deck object.
METADATA_KEY = "metadata"


class MissingApiKey(RuntimeError):
    pass


def api_key_from_env() -> str:
    key = str(os.getenv("RB_TOPDECK_API_KEY", "") or "").strip()
    if not key:
        raise MissingApiKey(
            "RB_TOPDECK_API_KEY is not set. Get a key from https://topdeck.gg and put it "
            "in your environment or .env (which is gitignored) — never in tracked source."
        )
    return key


@dataclass
class TopDeckResult:
    """One harvest from TopDeck."""
    name: str = "topdeck"
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


def _iso_from_epoch(value: object) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_deck_object(raw: object) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Split a ``deckObj`` into our zones, keyed by collector code.

    Returns ``(zones, unknown_zone_labels)``. Unrecognised zone labels are reported
    rather than dropped, so a new zone appearing upstream is visible instead of quietly
    removing cards from every imported list.
    """
    if not isinstance(raw, dict):
        return {}, []

    zones: dict[str, dict[str, int]] = {}
    unknown: list[str] = []
    for label, entries in raw.items():
        key = str(label).strip().casefold()
        if key == METADATA_KEY:
            continue
        zone = ZONE_ALIASES.get(key)
        if zone is None:
            unknown.append(str(label))
            continue
        if not isinstance(entries, dict):
            continue
        bucket = zones.setdefault(zone, {})
        for _name, detail in entries.items():
            if not isinstance(detail, dict):
                continue
            code = str(detail.get("id") or "").strip().upper()
            count = _int(detail.get("count"), 0)
            if code and count > 0:
                bucket[code] = bucket.get(code, 0) + count
    return zones, unknown


class TopDeckSource:
    """Bulk tournament + decklist harvesting from TopDeck.gg."""

    name = "topdeck"

    def __init__(
        self,
        *,
        api_key: str = "",
        days: int = 180,
        game: str = GAME,
        deck_format: str = DEFAULT_FORMAT,
        min_players: int = 0,
        timeout: float = 120.0,
        cache_dir: Path | None = None,
        client: HttpClient | None = None,
    ):
        self._api_key = api_key or ""
        self._days = max(1, days)
        self._game = game
        self._format = deck_format
        self._min_players = max(0, min_players)
        self._cache_dir = cache_dir
        # 100 requests/minute upstream, and we make one. Retries still matter for 429.
        self._http = client or HttpClient(timeout=timeout, min_interval=0.6)

    def fetch(self) -> TopDeckResult:
        started = time.perf_counter()
        result = TopDeckResult(name=self.name)
        try:
            key = self._api_key or api_key_from_env()
            payload = self._query(key)
            if not isinstance(payload, list):
                raise HttpError(f"expected a JSON array of tournaments, got {type(payload).__name__}")
            self._shape(payload, result)
            result.fetched = len(result.decks)
        except Exception as exc:  # sources never raise
            result.ok = False
            # Never let a key reach a log line or a manifest.
            result.error = _redact(f"{type(exc).__name__}: {exc}", self._api_key)
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # -- internals -------------------------------------------------------------

    def _query(self, key: str) -> Any:
        body: dict[str, Any] = {
            "game": self._game,
            "format": self._format,
            "last": self._days,
            "columns": list(COLUMNS),
        }
        if self._min_players:
            body["participantMin"] = self._min_players
        raw = self._http.post_json(API_URL, body, headers={"Authorization": key})
        self._cache(raw)
        return raw

    def _cache(self, payload: object) -> None:
        """Keep the raw response for replay. Contains no credentials."""
        if self._cache_dir is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
            (self._cache_dir / f"topdeck-tournaments-{stamp}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError:
            pass

    def _shape(self, payload: Sequence[dict[str, Any]], result: TopDeckResult) -> None:
        unknown_zones: set[str] = set()
        no_decklist = 0

        for event in payload:
            if not isinstance(event, dict):
                continue
            tid = str(event.get("TID") or "").strip()
            if not tid:
                continue
            standings = event.get("standings") or []
            record = {
                "tournament_id": tid,
                "slug": tid,
                "name": str(event.get("tournamentName") or "").strip(),
                "date": _iso_from_epoch(event.get("startDate")),
                "format": str(event.get("format") or "").strip(),
                "players": len(standings),
                "organizer": "",
                "winner": _winner_of(standings),
                "decks_published": sum(1 for s in standings if s.get("deckObj")),
            }
            result.tournaments.append(record)

            # The standings array is returned in finishing order; there is no explicit
            # place field, so position is the placement. Verified against a 359-player
            # event where the first row was 11-0 and the last were 0-0.
            for index, standing in enumerate(standings, start=1):
                if not isinstance(standing, dict):
                    continue
                player = str(standing.get("name") or "").strip()
                deck_slug = f"{tid}::{index}"
                result.standings.append({
                    "tournament_slug": tid,
                    "tournament_name": record["name"],
                    "tournament_date": record["date"],
                    "field_size": record["players"],
                    "place": index,
                    "player_name": player,
                    "record": _record_of(standing),
                    "deck_slug": deck_slug,
                })

                zones, unknown = parse_deck_object(standing.get("deckObj"))
                unknown_zones.update(unknown)
                if not zones:
                    no_decklist += 1
                    continue
                result.decks.append({
                    "_slug": deck_slug,
                    "_zones": zones,
                    "_source": "topdeck",
                    "humanname": _deck_name(standing, record["name"], player),
                    "public": "1",
                    "is_tournament": "1",
                    "authornick": player,
                    "date_edited": str(event.get("startDate") or ""),
                    "format": record["format"],
                    "views": 0,
                    "_tournament_url": f"https://topdeck.gg/event/{tid}",
                })

        result.notes.append(
            f"{len(result.tournaments)} events, {len(result.standings)} standings, "
            f"{len(result.decks)} decklists ({no_decklist} players published none)"
        )
        if unknown_zones:
            result.notes.append(
                f"unrecognised deck zone(s) {sorted(unknown_zones)} — cards in them were "
                f"skipped; add them to ZONE_ALIASES"
            )


def _winner_of(standings: Sequence[Any]) -> str:
    if standings and isinstance(standings[0], dict):
        return str(standings[0].get("name") or "").strip()
    return ""


def _record_of(standing: dict[str, Any]) -> str:
    wins, losses = _int(standing.get("wins")), _int(standing.get("losses"))
    draws = _int(standing.get("draws"))
    return f"{wins}-{losses}-{draws}" if draws else f"{wins}-{losses}"


def _deck_name(standing: dict[str, Any], event: str, player: str) -> str:
    leader = str(standing.get("leader") or "").strip()
    if leader:
        return f"{leader} — {player}" if player else leader
    return f"{player} — {event}" if player else event


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text



