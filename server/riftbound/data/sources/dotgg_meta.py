"""Meta sources: tournaments, standings, and published decklists.

Three upstream endpoints, discovered by probing (several neighbouring ones are
WAF-blocked, so this is the working set):

``gettournaments?game=riftbound``       every event: date, format, players, winner
``gettournament?game=riftbound&slug=``  one event's full standings
``getdeck?game=riftbound&slug=``        one decklist, keyed by collector code

Deck *slugs* come from riftbound.gg's sitemap shards (``decks-latest-sitemap.xml`` plus
numbered archives), which carry ``lastmod`` timestamps. That makes refreshes
incremental: only slugs modified since the last snapshot need hydrating, which matters
because a full crawl is 5,000+ requests.

Two upstream behaviours worth knowing, both verified:

* A missing or private deck returns an **empty body**, not a 404. Treated as "not
  available", never as an error.
* Several endpoint names return the string ``Hacker! Go home!``. Any non-JSON body is
  therefore treated as a failure rather than parsed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Sequence

from .http import HttpClient, HttpError

API_BASE = "https://api.dotgg.gg/cgfw"
SITE_BASE = "https://riftbound.gg"
DECK_URL = f"{SITE_BASE}/decks/{{slug}}/"
USER_AGENT = "riftbound-deck-builder/0.1 (+local deck building tool)"
DEFAULT_TIMEOUT = 45.0

#: Sitemap shards holding deck URLs. "latest" first — an incremental refresh usually
#: needs nothing else.
DECK_SITEMAPS = ("decks-latest-sitemap.xml",) + tuple(
    f"decks{i}-sitemap.xml" for i in range(1, 12)
) + ("decks-sitemap.xml",)

#: Prefix upstream gives a deck the moment someone clicks "new deck"; most are never
#: filled in. Not excluded, only deprioritised.
SCRATCH_PREFIX = "new-deck-"

_LOC_LASTMOD = re.compile(
    r"<loc>\s*([^<]+?)\s*</loc>\s*(?:<lastmod>\s*([^<]+?)\s*</lastmod>)?", re.IGNORECASE
)


@dataclass
class MetaFetchResult:
    """What one meta ingest run produced."""
    name: str
    tournaments: list[dict[str, Any]] = field(default_factory=list)
    standings: list[dict[str, Any]] = field(default_factory=list)
    decks: list[dict[str, Any]] = field(default_factory=list)
    fetched: int = 0
    ok: bool = True
    error: str = ""
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)


def _iso_from_epoch(value: object) -> str:
    try:
        return datetime.fromtimestamp(int(str(value)), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class DotGGMetaSource:
    """Tournaments, standings and decklists from the dotgg API + riftbound.gg sitemaps."""

    name = "dotgg-meta"

    def __init__(
        self,
        *,
        max_tournaments: int = 30,
        max_decks: int = 400,
        since: str = "",
        workers: int = 4,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = 0.35,
        budget_seconds: float = 240.0,
        progress: "Callable[[str], None] | None" = None,
        cache_dir: Path | None = None,
        client: HttpClient | None = None,
    ):
        self._max_tournaments = max_tournaments
        self._max_decks = max_decks
        self._since = since
        self._workers = max(1, workers)
        self._cache_dir = cache_dir
        # A harvest is a routine, repeated operation, so it gets a wall-clock budget.
        # Running out of time yields a smaller but usable snapshot rather than an
        # unbounded crawl; the gate still decides whether it is good enough to promote.
        self._budget = budget_seconds
        self._started = 0.0
        self._progress = progress or (lambda _msg: None)
        # One throttled, retrying client shared by every request this source makes,
        # so concurrent deck hydration cannot outrun the rate limit.
        self._http = client or HttpClient(
            timeout=timeout, min_interval=min_interval, referer=f"{SITE_BASE}/"
        )

    # -- public ----------------------------------------------------------------

    def _out_of_time(self) -> bool:
        return (time.perf_counter() - self._started) > self._budget

    def _elapsed(self) -> str:
        return f"{time.perf_counter() - self._started:5.1f}s"

    def fetch(self) -> MetaFetchResult:
        started = self._started = time.perf_counter()
        result = MetaFetchResult(name=self.name)
        try:
            self._progress("fetching tournament list")
            tournaments, standings = self._fetch_tournaments(result)
            result.tournaments = tournaments
            result.standings = standings

            # Decks reachable two ways, in priority order:
            #   1. slugs named in standings — these carry a real finish
            #   2. the sitemap — everything else people have published
            placed = [s["deck_slug"] for s in standings if s.get("deck_slug")]
            self._progress(f"{len(tournaments)} tournaments read; discovering deck slugs")
            discovered = self._discover_deck_slugs(result)
            ordered = list(dict.fromkeys(placed + discovered))[: self._max_decks]
            result.notes.append(
                f"{len(placed)} slug(s) from standings, {len(discovered)} from sitemaps"
            )
            self._progress(f"hydrating {len(ordered)} decklists")
            result.decks = self._hydrate_decks(ordered, result)
            result.fetched = len(result.decks)
        except Exception as exc:  # sources never raise
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # -- tournaments -----------------------------------------------------------

    def _fetch_tournaments(
        self, result: MetaFetchResult
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        listing = self._http.get_json(f"{API_BASE}/gettournaments?game=riftbound")
        if not isinstance(listing, list):
            raise HttpError("tournament listing was not a JSON array")

        rows = sorted(listing, key=lambda r: _int(r.get("date")), reverse=True)
        rows = rows[: self._max_tournaments]

        tournaments: list[dict[str, Any]] = []
        standings: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            if self._out_of_time():
                result.notes.append(
                    f"time budget reached after {index - 1}/{len(rows)} tournaments"
                )
                break
            record = {
                "tournament_id": str(row.get("id") or slug),
                "slug": slug,
                "name": str(row.get("name") or "").strip(),
                "date": _iso_from_epoch(row.get("date")),
                "format": str(row.get("format") or "").strip(),
                "players": _int(row.get("players_count")),
                "organizer": str(row.get("organizer_name") or "").strip(),
                "winner": str(row.get("winner_name") or "").strip(),
            }
            try:
                detail = self._http.get_json(
                    f"{API_BASE}/gettournament?game=riftbound&slug={slug}"
                )
            except HttpError as exc:
                result.notes.append(f"standings unavailable for {slug}: {exc}")
                tournaments.append(record)
                continue

            published = 0
            for standing in (detail or {}).get("standings") or []:
                deck_slug = str(standing.get("slug") or "").strip()
                if deck_slug:
                    published += 1
                standings.append({
                    "tournament_slug": slug,
                    "tournament_name": record["name"],
                    "tournament_date": record["date"],
                    "field_size": record["players"],
                    "place": _int(standing.get("standing_place")),
                    "player_name": str(standing.get("player_name") or "").strip(),
                    "record": str(standing.get("standing_record") or "").strip(),
                    "deck_slug": deck_slug,
                })
            record["decks_published"] = published
            tournaments.append(record)
            self._progress(
                f"  [{self._elapsed()}] {index}/{len(rows)} {record['name'][:38]:<40} "
                f"{len(detail.get('standings') or []) if detail else 0:>4} standings, "
                f"{published} with lists"
            )
        # Cached in normalised form so a replay reproduces the harvest exactly,
        # including the placement evidence that only standings carry.
        self._cache("tournaments", tournaments)
        self._cache("standings", standings)
        return tournaments, standings

    # -- deck discovery --------------------------------------------------------

    def _discover_deck_slugs(self, result: MetaFetchResult) -> list[str]:
        """Deck slugs from the sitemap shards, newest first.

        ``since`` prunes by ``lastmod`` so a routine refresh does not re-crawl
        thousands of unchanged decks.
        """
        slugs: list[str] = []
        seen: set[str] = set()
        for shard in DECK_SITEMAPS:
            if len(slugs) >= self._max_decks * 3:
                break
            try:
                body = self._http.get_text(f"{SITE_BASE}/{shard}")
            except HttpError as exc:
                result.notes.append(f"sitemap {shard} unavailable: {exc}")
                continue
            for url, lastmod in _LOC_LASTMOD.findall(body):
                if "/decks/" not in url:
                    continue
                if self._since and lastmod and lastmod[:10] < self._since:
                    continue
                slug = url.rstrip("/").rsplit("/", 1)[-1]
                if slug and slug not in seen:
                    seen.add(slug)
                    slugs.append(slug)
        # Named decks first. Roughly half of all slugs are untouched "new-deck-xxxxx"
        # scratch saves, and sampling showed only ~14% of the raw sitemap is a public,
        # complete list — so spending a limited request budget on named decks roughly
        # doubles the usable yield. Scratch slugs still follow, just last.
        slugs.sort(key=lambda s: s.startswith(SCRATCH_PREFIX))
        return slugs

    # -- deck hydration --------------------------------------------------------

    def _hydrate_decks(
        self, slugs: Sequence[str], result: MetaFetchResult
    ) -> list[dict[str, Any]]:
        missing = 0
        skipped = 0
        decks: list[dict[str, Any]] = []

        # Sentinel distinguishing "we ran out of time" from "upstream has no such deck".
        # Conflating them made a truncated harvest look like 108 private decks.
        SKIPPED: dict[str, Any] = {"_skipped": True}

        def one(slug: str) -> dict[str, Any] | None:
            if self._out_of_time():
                return SKIPPED
            try:
                payload = self._http.get_json(
                    f"{API_BASE}/getdeck?game=riftbound&slug={slug}"
                )
            except HttpError:
                return None
            if not isinstance(payload, dict):
                return None
            payload["_slug"] = slug
            return payload

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            for index, payload in enumerate(pool.map(one, slugs), start=1):
                if payload is SKIPPED:
                    skipped += 1
                elif payload is None:
                    missing += 1
                else:
                    decks.append(payload)
                if index % 25 == 0 or index == len(slugs):
                    self._progress(
                        f"  [{self._elapsed()}] {index}/{len(slugs)} decks "
                        f"({len(decks)} usable, {missing} unavailable"
                        + (f", {skipped} skipped" if skipped else "")
                        + ")"
                    )

        if missing:
            result.notes.append(f"{missing} slug(s) returned nothing (private or removed)")
        if skipped:
            result.notes.append(
                f"{skipped} slug(s) not attempted - time budget reached "
                f"(raise --budget or lower --decks for a complete pass)"
            )
        self._cache("decks", decks)
        return decks

    # -- caching ---------------------------------------------------------------

    def _cache(self, label: str, payload: object) -> None:
        """Keep raw responses for replay. Never read back automatically."""
        if self._cache_dir is None:
            return
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
            (self._cache_dir / f"{self.name}-{label}-{stamp}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError:
            pass


def deck_url(slug: str) -> str:
    return DECK_URL.format(slug=slug)


def iter_board_entries(payload: dict[str, Any]) -> Iterable[tuple[str, int]]:
    """Every (collector code, quantity) pair in a deck payload.

    Upstream exposes both a flat ``deck`` map and a ``boards`` list; the flat map is the
    complete list, so boards are only consulted when it is absent.
    """
    flat = payload.get("deck")
    if isinstance(flat, dict) and flat:
        for code, qty in flat.items():
            yield str(code).strip().upper(), _int(qty)
        return
    for board in payload.get("boards") or []:
        if isinstance(board, dict):
            for code, qty in board.items():
                yield str(code).strip().upper(), _int(qty)
