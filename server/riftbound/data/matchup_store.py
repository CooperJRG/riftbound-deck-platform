"""Where the matchup table lives, and why it does not live in the meta snapshot.

It started inside the snapshot, alongside the decks, and that was wrong for a reason
worth writing down rather than quietly fixing.

A meta snapshot is an **archive**: 19,000 decklists, assembled by a crawl that costs one
request per deck, gated so it can never go backwards, promoted deliberately. Hosted mode
disables that harvest on purpose -- ``config.meta_refresh`` defaults off outside local,
because "the harvest belongs to whatever deploys the service, not to every process that
happens to be running".

The matchup table is none of those things. It is **one request for one static file**,
recomputed upstream on its own schedule, and it carries no provenance we could rebuild.
Riding inside the snapshot gave it the snapshot's lifecycle, and three consequences
followed, all of them observed on the live site rather than predicted:

* it could only update when the deck pipeline ran, which in production is never;
* a deck harvest that failed its gate would also withhold a matchup update that had
  nothing to do with decks;
* refreshing a 300 KB table meant rewriting a 40 MB archive.

So it gets its own store: one file, replaced whole, no dated history. History is
deliberately absent -- this is a **cache of somebody else's aggregate**, not a record we
are the custodian of. Keeping versions of it would imply we could reconstruct what it
said last week, and we cannot; only the upstream can.

The snapshot copy is still read as a fallback (see ``Services.matchups``), so a snapshot
built by the pipeline keeps working and nothing already harvested is thrown away.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: One file, not a directory of dated ones. See the module docstring.
STORE_NAME = "current.json"

FORMAT_VERSION = 1


def store_path(matchup_dir: Path) -> Path:
    return matchup_dir / STORE_NAME


def write_matchups(
    matchup_dir: Path,
    *,
    cells: list[dict[str, Any]],
    legends: list[dict[str, Any]],
    meta: dict[str, Any],
) -> Path:
    """Replace the stored table, atomically.

    Written to a temporary file and renamed, so a process reading the store never sees
    a half-written one -- the app reads this on demand, and a crash mid-write would
    otherwise leave unparseable JSON that looks exactly like a missing table.
    """
    matchup_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "formatVersion": FORMAT_VERSION,
        "fetchedAt": datetime.now(UTC).isoformat(),
        "meta": dict(meta),
        "legends": list(legends),
        "cells": list(cells),
    }
    target = store_path(matchup_dir)
    handle, temp_name = tempfile.mkstemp(dir=str(matchup_dir), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(payload, out, ensure_ascii=False)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return target


def load_matchups(matchup_dir: Path) -> dict[str, Any] | None:
    """The stored table, or None.

    None for every failure -- absent, unreadable, corrupt, or written by a newer build.
    The whole feature degrades to "no matchup data yet", which is a state every caller
    already handles, and an unreadable cache must never take the app down.
    """
    path = store_path(matchup_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("formatVersion") or 0) > FORMAT_VERSION:
        return None
    if not payload.get("cells"):
        return None
    return payload


def age_hours(matchup_dir: Path) -> float:
    """How old the stored table is. ``-1`` when there is none.

    Read from the recorded fetch time rather than the file's mtime: a deploy that copies
    the volume, or a restore, resets mtimes and would make a year-old table look minutes
    fresh.
    """
    payload = load_matchups(matchup_dir)
    if payload is None:
        return -1.0
    stamp = str(payload.get("fetchedAt") or "")
    try:
        fetched = datetime.fromisoformat(stamp)
    except ValueError:
        return -1.0
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return (datetime.now(UTC) - fetched).total_seconds() / 3600.0
