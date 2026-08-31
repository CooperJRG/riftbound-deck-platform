"""Matchup source: Riftools' published win-rate table.

Every other module under ``data/`` normalises a *primary* record — a decklist somebody
registered, a standing an organiser published. This one does not, and the difference
matters enough to state at the top: what arrives here is an **aggregate someone else
computed**, from match records we cannot see. Riftools labels its own source
``"Official UVS match records"``, the pairing system the events actually ran on.

We ingest it anyway, because the thing it carries is one our own data cannot produce at
all. ``domain/meta_trends/performance.py`` computes a win rate from the match records on
our standings, and says plainly what it cannot do:

    "What is genuinely unavailable: the opponent. Matchup tables are out of scope
    permanently unless a source begins publishing pairings, and no model manufactures
    them."

A source began publishing pairings. 48 legends, 1,740 ordered matchup cells over 25,622
non-mirror matches — who beat whom, not merely who won.

**It is one request.** The whole table is a single static JSON file, unlike the deck
harvest next door which is one request per decklist. Refreshing it is nearly free, so it
rides along with the ordinary meta build rather than needing a schedule of its own.

**The set window is discovered, not hardcoded.** The manifest tags each win-rate family
with ``query.set``, so a set 5 table is picked up by the same code that found set 4 —
the same discipline ``normalize.set_code_for`` follows for card sets. Families carrying
``top_players_only`` are skipped: a top-table-only sample is a different population, not
a fresher view of this one.

**Attribution travels with the data**, exactly as for the decklist source next door.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .http import HttpClient, HttpError
from .riftools import ATTRIBUTION, DEFAULT_BASE_URL, MANIFEST_PATH

#: Snapshot families that carry a matchup table. Matched rather than listed, so a new
#: set window needs no code change.
_WINRATE_FAMILY = re.compile(r"^winrates(-set\d+)?$")

#: Pull a comparable integer out of ``{"set": "set4"}`` so "newest" has a meaning.
#: A family whose set cannot be read sorts last rather than being dropped -- it is still
#: a real table, it just cannot win the comparison.
_SET_NUMBER = re.compile(r"(\d+)")


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


@dataclass
class MatchupFetchResult:
    """One harvest of the matchup table, in the shape the normaliser accepts."""

    name: str = "riftools-winrates"
    ok: bool = True
    error: str = ""
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    #: ``{"legend": ..., "opponent": ..., "wins": ..., ...}`` -- names, not ids. The
    #: normaliser resolves them against the catalogue, which is where every other
    #: name-to-id decision in this package is made.
    cells: list[dict[str, Any]] = field(default_factory=list)
    #: One row per legend: its overall record across the same events.
    legends: list[dict[str, Any]] = field(default_factory=list)
    set_window: str = ""
    source_label: str = ""
    event_count: int = 0
    eligible_matches: int = 0
    matrix_matches: int = 0
    published_at: str = ""


class RiftoolsWinratesSource:
    """The legend matchup matrix, from Riftools' static snapshots."""

    name = "riftools-winrates"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        min_interval: float = 0.04,
        client: HttpClient | None = None,
    ):
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._http = client or HttpClient(
            timeout=timeout, min_interval=min_interval, max_attempts=4, base_backoff=0.5
        )

    # -- the harvest -----------------------------------------------------------

    def fetch(self) -> MatchupFetchResult:
        result = MatchupFetchResult(name=self.name)
        started = time.perf_counter()
        try:
            manifest = self._http.get_json(f"{self._base}{MANIFEST_PATH}")
            entry = self._newest_family(manifest)
            if entry is None:
                raise HttpError("manifest carries no win-rate snapshot family")
            url = entry.get("url")
            if not url:
                raise HttpError("win-rate snapshot family carries no url")
            payload = self._http.get_json(f"{self._base}{url}")
            self._shape(payload, entry, result)
        except Exception as exc:  # sources never raise
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    # -- internals -------------------------------------------------------------

    def _newest_family(self, manifest: Any) -> dict[str, Any] | None:
        """The matchup table for the newest set window the manifest offers."""
        snapshots = (manifest or {}).get("snapshots") or {}
        best: tuple[int, dict[str, Any]] | None = None
        for key, entry in snapshots.items():
            if not isinstance(entry, dict) or not _WINRATE_FAMILY.match(str(key)):
                continue
            query = entry.get("query") or {}
            # A top-table-only table answers a different question about a different
            # population. Taking it as "the" matchup table would silently narrow the
            # field to the players who made day two.
            if query.get("top_players_only"):
                continue
            if not entry.get("available", True):
                continue
            found = _SET_NUMBER.search(str(query.get("set") or ""))
            rank = int(found.group(1)) if found else -1
            if best is None or rank > best[0]:
                best = (rank, entry)
        return best[1] if best else None

    def _shape(
        self, payload: Any, entry: dict[str, Any], result: MatchupFetchResult
    ) -> None:
        if not isinstance(payload, dict) or not payload.get("available", True):
            raise HttpError("win-rate snapshot is not available")

        summary = payload.get("summary") or {}
        result.set_window = str((entry.get("query") or {}).get("set") or "")
        result.published_at = str(entry.get("published_at") or "")
        result.source_label = str(payload.get("source") or "")
        result.eligible_matches = _int(summary.get("eligible_matches"))
        result.matrix_matches = _int(summary.get("matrix_matches"))
        result.event_count = len(payload.get("tournaments") or [])

        for row in payload.get("legends") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            overall = row.get("overall") or {}
            if not name or not overall:
                continue
            result.legends.append(
                {
                    "legend": name,
                    "wins": _int(overall.get("wins")),
                    "losses": _int(overall.get("losses")),
                    "matches": _int(overall.get("matches")),
                    "gamesWon": _int(overall.get("games_won")),
                    "gamesLost": _int(overall.get("games_lost")),
                    "gameWinRate": _float(overall.get("game_winrate")),
                    "players": _int(row.get("players")),
                    "mirrorMatches": _int(row.get("mirror_matches")),
                }
            )

        cells = payload.get("cells") or {}
        if not isinstance(cells, dict):
            raise HttpError("win-rate snapshot carries no cells")
        events = self._events_per_cell(payload)
        for legend, opponents in cells.items():
            if not isinstance(opponents, dict):
                continue
            for opponent, cell in opponents.items():
                if not isinstance(cell, dict):
                    continue
                key = (str(legend).strip(), str(opponent).strip())
                result.cells.append(
                    {
                        "legend": key[0],
                        "opponent": key[1],
                        "wins": _int(cell.get("wins")),
                        "losses": _int(cell.get("losses")),
                        "matches": _int(cell.get("matches")),
                        "gamesWon": _int(cell.get("games_won")),
                        "gamesLost": _int(cell.get("games_lost")),
                        "gameWinRate": _float(cell.get("game_winrate")),
                        "events": events.get(key, 0),
                    }
                )

        result.notes.append(
            f"{len(result.cells)} matchup cell(s) over {len(result.legends)} legend(s), "
            f"{result.matrix_matches} non-mirror matches, {result.event_count} event(s)"
            + (f", set window {result.set_window}" if result.set_window else "")
        )

    @staticmethod
    def _events_per_cell(payload: dict[str, Any]) -> dict[tuple[str, str], int]:
        """How many distinct events each matchup was actually seen at.

        The aggregate table reports only a total, and a total cannot distinguish forty
        matches spread over ten events from forty played at one -- which is the
        difference between a matchup and an anecdote about a Saturday.
        ``performance.py`` gates on the same distinction for the same reason; the
        per-tournament payloads ride along in this file, so counting is free.

        Absent payloads yield an empty map rather than an error: the cell counts are
        still real, and the event gate degrades to "unknown" rather than taking the
        whole table down.
        """
        out: dict[tuple[str, str], int] = {}
        payloads = payload.get("tournament_payloads")
        if not isinstance(payloads, dict):
            return out
        for one in payloads.values():
            if not isinstance(one, dict):
                continue
            for legend, opponents in (one.get("cells") or {}).items():
                if not isinstance(opponents, dict):
                    continue
                for opponent, cell in opponents.items():
                    if not isinstance(cell, dict) or _int(cell.get("matches")) <= 0:
                        continue
                    key = (str(legend).strip(), str(opponent).strip())
                    out[key] = out.get(key, 0) + 1
        return out


def attribution() -> dict[str, str]:
    """The credit this data travels with. Same project as the decklist source."""
    return dict(ATTRIBUTION)
