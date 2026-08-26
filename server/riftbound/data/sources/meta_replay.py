"""Rebuild a meta harvest from cached raw responses, with no network at all.

Every harvest writes the raw upstream payloads to ``var/ingest``. Replaying them is
useful three ways:

* **Re-normalise without re-fetching.** A fix to the normaliser — the collector-code
  case bug, say — can be applied to an existing harvest immediately, instead of waiting
  out a rate limit to prove it.
* **Work offline**, and reproduce a bad harvest exactly while debugging it.
* **Be a good citizen.** The upstream API is community-run and rate-limits hard;
  iterating on parsing code should not cost it thousands of requests.

The cache is only ever read when explicitly asked for. A failed live fetch never
silently falls back to it — that is how stale data becomes invisible.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from .dotgg_meta import MetaFetchResult


def _newest(cache_dir: Path, prefix: str) -> Path | None:
    matches = sorted(cache_dir.glob(f"{prefix}-*.json"))
    return matches[-1] if matches else None


def _load(path: Path | None) -> Any:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class MetaReplaySource:
    """Replays the newest cached harvest from ``var/ingest``."""

    name = "dotgg-meta (replay)"

    def __init__(self, cache_dir: Path):
        self._cache_dir = Path(cache_dir)

    def fetch(self) -> MetaFetchResult:
        started = time.perf_counter()
        result = MetaFetchResult(name=self.name)

        decks = _load(_newest(self._cache_dir, "dotgg-meta-decks"))
        tournaments = _load(_newest(self._cache_dir, "dotgg-meta-tournaments"))
        standings = _load(_newest(self._cache_dir, "dotgg-meta-standings"))

        if not isinstance(decks, list) or not decks:
            result.ok = False
            result.error = (
                f"no cached deck payloads in {self._cache_dir}. "
                f"Run a live build once before replaying."
            )
            result.duration_ms = int((time.perf_counter() - started) * 1000)
            return result

        result.decks = [d for d in decks if isinstance(d, dict)]
        result.fetched = len(result.decks)

        if isinstance(tournaments, list):
            result.tournaments = [t for t in tournaments if isinstance(t, dict)]
        if isinstance(standings, list):
            result.standings = [s for s in standings if isinstance(s, dict)]
        else:
            result.notes.append(
                "no cached standings - decks will lose their tournament placements. "
                "Re-run a live build to restore placement evidence."
            )

        result.notes.append(
            f"replayed {len(result.decks)} deck payload(s) from {self._cache_dir}"
        )
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result
