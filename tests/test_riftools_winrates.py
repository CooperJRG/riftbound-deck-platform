"""Harvesting the matchup table out of the release store.

The source is thin on purpose -- three hops and one object -- so what is worth pinning
is which table it picks and what it refuses to pick. Getting that wrong does not fail
loudly: it silently publishes last season's matrix, or an empty one.
"""

from __future__ import annotations

from riftbound.data.sources.http import HttpError
from riftbound.data.sources.riftools_winrates import RiftoolsWinratesSource

BASE = "https://www.riftools.app"
CURRENT = "/release-v3/current.json"


class FakeClient:
    """Serves canned JSON and records what was asked for."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[str] = []

    def get_json(self, url: str) -> object:
        self.calls.append(url)
        path = url[len(BASE):]
        if path not in self.routes:
            raise HttpError(f"404 {path}")
        return self.routes[path]


def obj(name: str) -> str:
    """A fake content-addressed object path."""
    return f"objects/ab/{name}.json"


def release(sets: list[str], *, default: str = "", generated: str = "2026-10-02T14:51:08Z"):
    return {
        "release_id": "20261002T145108Z-test",
        "generated_at": generated,
        "schema_version": "release-v3.1",
        "default_set": default or (sets[-1] if sets else ""),
        "sets": sets,
        "client_manifests": {
            f"{s}__core": {"path": obj(f"{s}_core_manifest")} for s in sets
        },
    }


def core_manifest(set_name: str, *, winrates: bool = True):
    artifacts = {}
    if winrates:
        artifacts[f"{set_name}__winrates"] = {"object_path": obj(f"{set_name}_winrates")}
    return {"artifacts": artifacts}


def table(cells=None, legends=None):
    return {
        "available": True,
        "source": "Official UVS match records",
        "summary": {"eligible_matches": 27361, "matrix_matches": 25622},
        "tournaments": [{"name": "One"}, {"name": "Two"}],
        "legends": legends
        if legends is not None
        else [
            {
                "name": "Kennen, Heart of the Tempest",
                "players": 1105,
                "mirror_matches": 445,
                "overall": {
                    "wins": 3662, "losses": 2797, "matches": 6459,
                    "games_won": 8712, "games_lost": 7306, "game_winrate": 54.4,
                },
            }
        ],
        "cells": cells
        if cells is not None
        else {
            "Kennen, Heart of the Tempest": {
                "Irelia, Blade Dancer": {
                    "wins": 60, "losses": 40, "matches": 100,
                    "games_won": 130, "games_lost": 110, "game_winrate": 54.2,
                }
            }
        },
    }


def routes_for(sets, *, tables=None, missing_core=()):
    """A whole fake release: pointer, per-set core manifests, and their tables."""
    out: dict[str, object] = {CURRENT: release(sets)}
    for s in sets:
        if s in missing_core:
            continue
        has = (tables or {}).get(s, "default")
        out[f"/release-v3/{obj(f'{s}_core_manifest')}"] = core_manifest(
            s, winrates=has is not None
        )
        if has is not None:
            out[f"/release-v3/{obj(f'{s}_winrates')}"] = (
                table() if has == "default" else has
            )
    return out


def source(routes):
    return RiftoolsWinratesSource(client=FakeClient(routes))


# -- which table -------------------------------------------------------------


def test_it_takes_the_newest_set():
    """A set 5 release must be picked up without a code change."""
    result = source(routes_for(["set3", "set4", "set5"])).fetch()
    assert result.ok
    assert result.set_window == "set5"


def test_an_older_set_is_used_when_the_newest_publishes_no_table():
    """A release cut the day a set opens has the family but nothing in it yet.

    An empty current table is a worse answer than last set's real one.
    """
    empty = {**table(), "cells": {}}
    result = source(routes_for(["set3", "set4"], tables={"set4": empty})).fetch()
    assert result.ok
    assert result.set_window == "set3"


def test_a_set_whose_core_manifest_is_missing_is_skipped_not_fatal():
    result = source(routes_for(["set3", "set4"], missing_core=("set4",))).fetch()
    assert result.ok and result.set_window == "set3"


# -- failure is never fatal ---------------------------------------------------


def test_a_missing_release_pointer_fails_the_source_without_raising():
    result = source({}).fetch()
    assert not result.ok and result.error
    assert result.cells == []


def test_a_release_with_no_table_anywhere_is_an_error_not_a_crash():
    empty = {**table(), "cells": {}}
    result = source(routes_for(["set4"], tables={"set4": empty})).fetch()
    assert not result.ok and "matchup table" in result.error


def test_an_unavailable_table_is_refused():
    result = source(
        routes_for(["set4"], tables={"set4": {"available": False, "cells": {"a": {}}}})
    ).fetch()
    assert not result.ok


# -- shaping -------------------------------------------------------------------


def test_cells_and_legends_are_flattened_for_the_normaliser():
    result = source(routes_for(["set4"])).fetch()
    assert result.ok
    assert result.matrix_matches == 25622
    assert result.event_count == 2
    assert result.source_label == "Official UVS match records"
    # The release's build time stands in for the per-family stamp the old store had.
    assert result.published_at == "2026-10-02T14:51:08Z"

    cell = result.cells[0]
    assert cell["legend"] == "Kennen, Heart of the Tempest"
    assert cell["opponent"] == "Irelia, Blade Dancer"
    assert cell["wins"] == 60 and cell["losses"] == 40

    legend = result.legends[0]
    assert legend["legend"] == "Kennen, Heart of the Tempest"
    assert legend["wins"] == 3662


def test_events_per_cell_are_unknown_when_the_store_omits_them():
    """`release-v3` publishes no per-event breakdown, so every cell reports 0.

    Zero means *unknown*, and `matchups._rate` declines to gate on it. The alternative
    readings are both wrong: treating it as "one event" would withhold the entire table,
    and dropping the field would quietly delete a guard that works whenever the source
    does publish the breakdown.
    """
    result = source(routes_for(["set4"])).fetch()
    assert result.ok
    assert all(cell["events"] == 0 for cell in result.cells)
