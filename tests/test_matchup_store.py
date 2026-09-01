"""The matchup store, and why it is not the meta snapshot.

The bug these tests exist to prevent was live: the matchup table shipped, the code was
deployed, and the site showed nothing. The table rode inside the meta snapshot, so it
could only update when the deck pipeline ran -- and hosted mode disables that pipeline
on purpose, because it is a crawl of one request per decklist.

So what is pinned here is the *decoupling*, not the serialisation:

* a table in the store is served even when the promoted snapshot has none, which is
  exactly the production state that showed an empty page;
* the store wins over the snapshot, so the faster cadence is the one that counts;
* the snapshot is still read when there is no store, so nothing already harvested is
  lost and an offline seed keeps working;
* every failure degrades to "no matchup data" instead of taking a boot down.
"""

from __future__ import annotations

import json

from riftbound.data.matchup_store import (
    age_hours,
    load_matchups,
    store_path,
    write_matchups,
)

CELLS = [
    {
        "legend": "Kennen, Heart of the Tempest",
        "opponent": "Irelia, Blade Dancer",
        "wins": 60, "losses": 40, "matches": 100,
        "gamesWon": 0, "gamesLost": 0, "events": 12,
    }
]
LEGENDS = [
    {
        "legend": "Kennen, Heart of the Tempest",
        "wins": 600, "losses": 400, "matches": 1000,
        "gamesWon": 0, "gamesLost": 0, "players": 50, "mirrorMatches": 0,
    }
]
META = {"setWindow": "set4", "events": 32, "matrixMatches": 25622}


# -- round trip ----------------------------------------------------------------


def test_a_written_table_reads_back(tmp_path):
    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    payload = load_matchups(tmp_path)
    assert payload is not None
    assert payload["cells"] == CELLS
    assert payload["legends"] == LEGENDS
    assert payload["meta"]["setWindow"] == "set4"
    assert payload["fetchedAt"]


def test_writing_twice_replaces_rather_than_accumulating(tmp_path):
    """No history on purpose: this is a cache of somebody else's aggregate."""
    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    write_matchups(tmp_path, cells=[], legends=LEGENDS, meta=META)
    # An empty table reads back as absent, and there is exactly one file either way.
    assert load_matchups(tmp_path) is None
    assert [p.name for p in tmp_path.iterdir()] == ["current.json"]


def test_a_write_leaves_no_temporary_files_behind(tmp_path):
    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


# -- failures degrade ------------------------------------------------------------


def test_a_missing_store_is_none_not_an_error(tmp_path):
    assert load_matchups(tmp_path) is None
    assert age_hours(tmp_path) == -1.0


def test_a_corrupt_store_is_none_not_an_exception(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    store_path(tmp_path).write_text("{ not json", encoding="utf-8")
    assert load_matchups(tmp_path) is None


def test_a_store_from_a_newer_build_is_refused(tmp_path):
    """Better to show nothing than to guess at a shape we do not understand."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    store_path(tmp_path).write_text(
        json.dumps({"formatVersion": 999, "cells": CELLS}), encoding="utf-8"
    )
    assert load_matchups(tmp_path) is None


def test_age_is_read_from_the_recorded_time_not_the_file(tmp_path):
    """A deploy that copies the volume resets mtimes; the recorded stamp survives it."""
    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    assert 0 <= age_hours(tmp_path) < 1

    payload = json.loads(store_path(tmp_path).read_text(encoding="utf-8"))
    payload["fetchedAt"] = "2020-01-01T00:00:00+00:00"
    store_path(tmp_path).write_text(json.dumps(payload), encoding="utf-8")
    assert age_hours(tmp_path) > 10_000


def test_an_unreadable_timestamp_reads_as_unknown_age(tmp_path):
    """Unknown must mean "refetch", not "fresh" -- the opposite would pin a stale table."""
    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    payload = json.loads(store_path(tmp_path).read_text(encoding="utf-8"))
    payload["fetchedAt"] = "not a date"
    store_path(tmp_path).write_text(json.dumps(payload), encoding="utf-8")
    assert age_hours(tmp_path) == -1.0


# -- precedence: the bug this whole module exists for ----------------------------


class _FakeSnapshot:
    """A promoted snapshot from before matchups existed -- production's actual state."""

    matchups: tuple = ()
    matchup_legends: tuple = ()
    matchup_meta: dict = {}

    class manifest:  # noqa: D106
        attribution: tuple = ()


def _services(tmp_path, snapshot):
    from riftbound.services import Services

    class _Config:
        matchups_dir = tmp_path
        matchup_refresh = False
        matchup_refresh_hours = 6.0

    class _Bundle:
        catalog = _catalog()

    services = Services(config=_Config())  # type: ignore[arg-type]
    # `meta` and `bundle` are cached_property, so seeding __dict__ stubs them. `catalog`
    # is a plain property reading `bundle.catalog`, which is why the bundle is what gets
    # stubbed rather than the catalogue.
    services.__dict__["meta"] = snapshot
    services.__dict__["bundle"] = _Bundle()
    return services


def _catalog():
    from conftest import make_card
    from riftbound.domain.cards import build_catalog

    return build_catalog(
        [
            make_card("kennen-heart-of-the-tempest", "Kennen - Heart of the Tempest",
                      card_type="Legend"),
            make_card("irelia-blade-dancer", "Irelia - Blade Dancer", card_type="Legend"),
        ]
    )


def test_the_store_is_served_when_the_snapshot_has_no_matchups(tmp_path):
    """The exact production failure: new code, old snapshot, empty page."""
    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    table = _services(tmp_path, _FakeSnapshot()).matchups
    assert table.available
    assert table.basis.set_window == "set4"


def test_the_store_wins_over_the_snapshot(tmp_path):
    """The store has the faster cadence, so it must be the one that counts."""
    stale = [{**CELLS[0], "wins": 1, "losses": 99, "matches": 100}]

    class _WithMatchups(_FakeSnapshot):
        matchups = tuple(stale)
        matchup_legends = tuple(LEGENDS)
        matchup_meta = {"setWindow": "set3"}

    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    table = _services(tmp_path, _WithMatchups()).matchups
    assert table.basis.set_window == "set4", "the snapshot's older table won"
    row = table.between("kennen-heart-of-the-tempest", "irelia-blade-dancer")
    assert row is not None and row.wins == 60


def test_the_snapshot_is_still_read_when_there_is_no_store(tmp_path):
    """Nothing already harvested is thrown away, and an offline seed keeps working."""

    class _WithMatchups(_FakeSnapshot):
        matchups = tuple(CELLS)
        matchup_legends = tuple(LEGENDS)
        matchup_meta = {"setWindow": "set4"}

    table = _services(tmp_path, _WithMatchups()).matchups
    assert table.available


def test_neither_source_is_an_empty_table_not_a_crash(tmp_path):
    table = _services(tmp_path, _FakeSnapshot()).matchups
    assert not table.available
    assert table.ranked() == ()


def test_no_snapshot_at_all_still_serves_the_store(tmp_path):
    """A cold volume has no promoted snapshot; the table must not need one."""
    write_matchups(tmp_path, cells=CELLS, legends=LEGENDS, meta=META)
    table = _services(tmp_path, None).matchups
    assert table.available
    # The credit still has to appear, even with no manifest to read it from.
    assert table.basis.attribution.get("source") == "Riftools"
