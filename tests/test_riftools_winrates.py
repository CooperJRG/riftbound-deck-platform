"""Harvesting the matchup table.

The source is thin on purpose -- one request, no pagination -- so what is worth pinning
is which table it picks and what it refuses to pick. Getting that wrong does not fail
loudly: it silently publishes last season's matrix, or a top-table-only sample labelled
as the whole field.
"""

from __future__ import annotations

from riftbound.data.sources.http import HttpError
from riftbound.data.sources.riftools_winrates import RiftoolsWinratesSource

BASE = "https://www.riftools.app"
MANIFEST = "/public-snapshots/manifest.current.json"


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


def table(cells=None, legends=None, payloads=None):
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
        "tournament_payloads": payloads or {},
    }


def source(routes):
    return RiftoolsWinratesSource(client=FakeClient(routes))


# -- which table -------------------------------------------------------------


def test_it_takes_the_newest_set_window():
    """A set 5 table must be picked up without a code change, as for card sets."""
    routes = {
        # Keyed as the live manifest keys them: the family name is what is matched.
        MANIFEST: {"snapshots": {
            "winrates": {"url": "/s3.json", "query": {"set": "set3"}, "available": True},
            "winrates-set4": {"url": "/s4.json", "query": {"set": "set4"}, "available": True},
        }},
        "/s3.json": table(),
        "/s4.json": table(),
    }
    result = source(routes).fetch()
    assert result.ok
    assert result.set_window == "set4"


def test_a_top_players_only_table_is_never_chosen():
    """It is a different population, not a fresher view of this one."""
    routes = {
        MANIFEST: {"snapshots": {
            "winrates-set4": {"url": "/s4.json", "query": {"set": "set4"}, "available": True},
            "winrates-top-player-set4": {
                "url": "/top.json",
                "query": {"set": "set4", "top_players_only": "1"},
                "available": True,
            },
        }},
        "/s4.json": table(),
    }
    client = FakeClient(routes)
    result = RiftoolsWinratesSource(client=client).fetch()
    assert result.ok and result.set_window == "set4"
    # Not merely unused -- never even requested.
    assert not any("top.json" in call for call in client.calls)


def test_an_unavailable_family_is_skipped():
    routes = {
        MANIFEST: {"snapshots": {
            "winrates-set4": {"url": "/s4.json", "query": {"set": "set4"}, "available": False},
            "winrates": {"url": "/s3.json", "query": {"set": "set3"}, "available": True},
        }},
        "/s3.json": table(),
    }
    result = source(routes).fetch()
    assert result.ok and result.set_window == "set3"


# -- failure is never fatal ---------------------------------------------------


def test_a_missing_manifest_fails_the_source_without_raising():
    result = source({}).fetch()
    assert not result.ok and result.error
    assert result.cells == []


def test_a_manifest_with_no_winrate_family_is_an_error_not_a_crash():
    result = source({MANIFEST: {"snapshots": {"card-explorer": {"url": "/c.json"}}}}).fetch()
    assert not result.ok and "win-rate" in result.error


def test_an_unavailable_snapshot_is_refused():
    routes = {
        MANIFEST: {"snapshots": {
            "winrates-set4": {"url": "/s4.json", "query": {"set": "set4"}, "available": True},
        }},
        "/s4.json": {"available": False},
    }
    result = source(routes).fetch()
    assert not result.ok


# -- shaping -------------------------------------------------------------------


def test_cells_and_legends_are_flattened_for_the_normaliser():
    routes = {
        MANIFEST: {"snapshots": {
            "winrates-set4": {"url": "/s4.json", "query": {"set": "set4"}, "available": True},
        }},
        "/s4.json": table(),
    }
    result = source(routes).fetch()
    assert result.ok
    assert result.matrix_matches == 25622
    assert result.event_count == 2
    assert result.source_label == "Official UVS match records"

    cell = result.cells[0]
    assert cell["legend"] == "Kennen, Heart of the Tempest"
    assert cell["opponent"] == "Irelia, Blade Dancer"
    assert cell["wins"] == 60 and cell["losses"] == 40

    legend = result.legends[0]
    assert legend["legend"] == "Kennen, Heart of the Tempest"
    assert legend["wins"] == 3662


def test_events_per_cell_are_counted_from_the_per_tournament_payloads():
    """The aggregate reports only a total; the event count has to be derived."""
    payloads = {
        "event-a": {"cells": {"Kennen, Heart of the Tempest": {
            "Irelia, Blade Dancer": {"matches": 4}}}},
        "event-b": {"cells": {"Kennen, Heart of the Tempest": {
            "Irelia, Blade Dancer": {"matches": 6}}}},
        # A zero-match entry is not an appearance.
        "event-c": {"cells": {"Kennen, Heart of the Tempest": {
            "Irelia, Blade Dancer": {"matches": 0}}}},
    }
    routes = {
        MANIFEST: {"snapshots": {
            "winrates-set4": {"url": "/s4.json", "query": {"set": "set4"}, "available": True},
        }},
        "/s4.json": table(payloads=payloads),
    }
    result = source(routes).fetch()
    assert result.cells[0]["events"] == 2


def test_absent_payloads_leave_events_unknown_rather_than_failing():
    routes = {
        MANIFEST: {"snapshots": {
            "winrates-set4": {"url": "/s4.json", "query": {"set": "set4"}, "available": True},
        }},
        "/s4.json": table(payloads={}),
    }
    result = source(routes).fetch()
    assert result.ok and result.cells[0]["events"] == 0
