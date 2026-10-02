"""The Riftools release-store source.

Nothing here touches the network. A fake client serves the shapes the live store
publishes, so the tests pin the *contract* -- which objects are read, how a deck becomes
a payload, what happens when one is half-published -- rather than whatever the archive
happens to hold today.

Rewritten when Riftools retired ``/public-snapshots`` with a 410 and replaced it with a
content-addressed release store. The old tests passed against a store that no longer
exists, which is the failure mode worth naming: a green suite and a dead source.
"""

from __future__ import annotations

import json

import pytest
from tests.conftest import make_card

from riftbound.data.meta_normalize import deck_from_payload
from riftbound.data.sources.http import HttpError
from riftbound.data.sources.riftools import (
    RiftoolsSource,
    event_slug,
    parse_placement,
    strip_code,
)

BASE = "https://riftools.test"
CURRENT = "/release-v3/current.json"
EVENT_URL = "operator://riftools/piltoverarchive/spring-open-2026-07-25"


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
        value = self.routes[path]
        if isinstance(value, Exception):
            raise value
        return value


def obj(name: str) -> str:
    return f"objects/cd/{name}.json"


def card(name: str, code: str, count: int = 1) -> dict[str, object]:
    return {
        "card_name": name,
        "card_type": "Unit",
        "count": count,
        "image_public_code": code,
        "image_url": "",
    }


def deck_object(
    *,
    deck_id: str = "347564",
    parse_status: str = "parsed",
    placement: object = "Top 8",
    main: list | None = None,
    legend: str = "Irelia, Blade Dancer",
    champion: str = "Irelia, Fervent",
) -> dict[str, object]:
    return {
        "id": deck_id,
        "legend": legend,
        "champion": champion,
        "main_deck": main if main is not None else [card("Gust", "OGN-042/298", 3)],
        "runes": [{"card_name": "Calm Rune", "card_type": "Runes",
                   "count": 6, "image_public_code": "VEN-R02"}],
        "battlefields": [{"card_name": "Minefield", "card_type": "Battlefield",
                          "count": 1, "image_public_code": "UNL-208/242"}],
        "sideboard": [],
        "deck": {
            "parse_status": parse_status,
            "deck_name": "Irelia Fervent",
            "deck_url": f"{EVENT_URL}/deck/player-{deck_id}",
            "player_name": "A Player",
            "event_date": "2026-07-25",
            "placement": placement,
            "rank": None,
            "player_count": 32,
            "region": "Online",
            "tournament_name": "Spring Open",
            "tournament_url": EVENT_URL,
        },
    }


def routes_for(decks: dict[str, object], *, sets=("set4",), omit_index=False):
    """A whole fake release: pointer, core + details manifests, and deck objects."""
    out: dict[str, object] = {
        CURRENT: {
            "release_id": "r1",
            "generated_at": "2026-10-02T14:51:08Z",
            "sets": list(sets),
            "default_set": sets[-1],
            "client_manifests": {
                **{f"{s}__core": {"path": obj(f"{s}_core")} for s in sets},
                **{f"{s}__details": {"path": obj(f"{s}_details")} for s in sets},
            },
        }
    }
    for s in sets:
        out[f"/release-v3/{obj(f'{s}_core')}"] = {
            "artifacts": {f"{s}__decks": {"object_path": obj(f"{s}_decks")}}
        }
        out[f"/release-v3/{obj(f'{s}_decks')}"] = (
            {} if omit_index else {"deck_detail_ids": list(decks)}
        )
        out[f"/release-v3/{obj(f'{s}_details')}"] = {
            "artifacts": {
                f"{s}__deck_detail__{i}": {"object_path": obj(f"deck_{i}")}
                for i in decks
            }
        }
    for i, payload in decks.items():
        out[f"/release-v3/{obj(f'deck_{i}')}"] = payload
    return out


def harvest(routes, **kw):
    client = FakeClient(routes)
    return RiftoolsSource(base_url=BASE, client=client, **kw).fetch(), client


# -- shaping -------------------------------------------------------------------


def test_a_deck_object_becomes_a_deck_payload():
    result, _ = harvest(routes_for({"1": deck_object(deck_id="1")}))
    assert result.ok, result.error
    assert len(result.decks) == 1
    payload = result.decks[0]
    assert payload["_source"] == "riftools"
    # Cards by collector code, legend and champion by name -- the store gives the
    # identity as display names only.
    assert payload["_zones"]["main"] == {"OGN-042": 3}
    assert payload["_zones"]["runes"] == {"VEN-R02": 6}
    assert payload["_zones"]["battlefields"] == {"UNL-208": 1}
    assert payload["_named_zones"]["legend"] == {"Irelia, Blade Dancer": 1}
    assert payload["_named_zones"]["champion"] == {"Irelia, Fervent": 1}


def test_it_normalises_into_a_deck():
    """The coded zones and the named identity must survive together.

    They are merged rather than one replacing the other -- the bug that would otherwise
    keep the two names and silently drop all forty cards.
    """
    catalog_cards = [
        make_card("gust", "Gust", number="042", set_code="OGN"),
        make_card("calm-rune", "Calm Rune", card_type="Rune", number="R02", set_code="VEN"),
        make_card("minefield", "Minefield", card_type="Battlefield",
                  number="208", set_code="UNL"),
        make_card("irelia-blade-dancer", "Irelia - Blade Dancer", card_type="Legend"),
        make_card("irelia-fervent", "Irelia - Fervent", super_type="Champion"),
    ]
    from riftbound.domain.cards import build_catalog

    catalog = build_catalog(catalog_cards)
    result, _ = harvest(routes_for({"1": deck_object(deck_id="1")}))
    deck, unresolved = deck_from_payload(result.decks[0], catalog=catalog)

    assert not unresolved
    assert deck.legend_id == "irelia-blade-dancer"
    assert deck.champion_id == "irelia-fervent"
    assert deck.main.get("gust") == 3
    assert deck.runes.get("calm-rune") == 6
    assert "minefield" in deck.battlefields
    # The nominated champion is one of the main deck's cards, folded in by the
    # normaliser exactly as for every other source.
    assert deck.champion_id in deck.main


# -- placements ----------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [("1st", 1), ("2nd", 2), ("Top 4", 4), ("Top 32", 32), (3, 3), ("", 0),
     (None, 0), ("Winner", 0)],
)
def test_parse_placement(raw, expected):
    assert parse_placement(raw) == expected


def test_standing_carries_the_placement():
    result, _ = harvest(routes_for({"1": deck_object(deck_id="1", placement="Top 8")}))
    assert len(result.standings) == 1
    assert result.standings[0]["place"] == 8


def test_an_unreadable_placement_publishes_no_standing():
    """Zero means unknown, and a standing claiming an unplaced finish is worse than none."""
    result, _ = harvest(routes_for({"1": deck_object(deck_id="1", placement="DQ")}))
    assert result.decks and result.standings == []


def test_event_row_gets_its_field_size():
    result, _ = harvest(routes_for({"1": deck_object(deck_id="1")}))
    assert len(result.tournaments) == 1
    event = result.tournaments[0]
    assert event["players"] == 32
    assert event["name"] == "Spring Open"
    assert event["date"] == "2026-07-25"
    assert event["decks_published"] == 1


# -- partial data ---------------------------------------------------------------


def test_unparsed_decks_are_counted_not_emitted():
    routes = routes_for({"1": deck_object(deck_id="1", parse_status="pending")})
    result, _ = harvest(routes)
    assert result.ok and result.decks == []
    assert result.unparsed == 1


def test_a_deck_with_no_cards_is_skipped():
    empty = deck_object(deck_id="1", main=[])
    empty["runes"] = []
    empty["battlefields"] = []
    routes = routes_for({"1": empty})
    result, _ = harvest(routes)
    # A legend and a champion name alone are not a decklist. The emptiness check runs
    # before the identity is attached, precisely so a deck whose cards failed to publish
    # is dropped rather than emitted as a two-card list.
    assert result.decks == []
    assert result.unparsed == 1


def test_a_failed_deck_fetch_does_not_fail_the_harvest():
    routes = routes_for({"1": deck_object(deck_id="1"), "2": deck_object(deck_id="2")})
    del routes[f"/release-v3/{obj('deck_2')}"]
    result, _ = harvest(routes)
    assert result.ok
    assert len(result.decks) == 1


def test_a_missing_release_pointer_fails_the_source_without_raising():
    result, _ = harvest({})
    assert not result.ok and result.error
    assert result.decks == []


def test_a_release_without_a_deck_index_is_an_error():
    result, _ = harvest(routes_for({"1": deck_object()}, omit_index=True))
    assert not result.ok and "deck index" in result.error


def test_max_decks_caps_the_harvest():
    decks = {str(i): deck_object(deck_id=str(i)) for i in range(5)}
    result, client = harvest(routes_for(decks), max_decks=2)
    assert result.ok
    assert len(result.decks) == 2
    assert result.requested == 5
    fetched = [c for c in client.calls if "deck_" in c]
    assert len(fetched) == 2, "capped harvests must not fetch what they discard"


# -- every set, not just the newest ---------------------------------------------


def test_every_set_in_the_release_is_indexed():
    """An archive that dropped set 3 the day set 4 opened would lose two thirds of itself."""
    decks = {"1": deck_object(deck_id="1")}
    result, _ = harvest(routes_for(decks, sets=("set3", "set4")))
    assert result.ok
    assert any("set3" in n for n in result.notes)
    assert any("set4" in n for n in result.notes)


# -- caching --------------------------------------------------------------------


def test_a_deck_is_served_from_cache_on_the_second_run(tmp_path):
    routes = routes_for({"1": deck_object(deck_id="1")})
    first, client_a = harvest(routes, cache_dir=tmp_path)
    assert first.from_cache == 0

    second, client_b = harvest(routes, cache_dir=tmp_path)
    assert second.from_cache == 1
    assert not [c for c in client_b.calls if "deck_" in c], "a cache hit still fetched"
    assert second.decks and second.decks[0]["_zones"] == first.decks[0]["_zones"]


def test_the_cache_is_keyed_on_the_object_hash_so_it_cannot_go_stale(tmp_path):
    """A changed deck is a different object, so it is refetched rather than served stale."""
    routes = routes_for({"1": deck_object(deck_id="1")})
    harvest(routes, cache_dir=tmp_path)

    # Re-publish the deck under a new object name, as a content-addressed store does.
    changed = deck_object(deck_id="1", main=[card("Gust", "OGN-042/298", 1)])
    routes[f"/release-v3/{obj('set4_details')}"] = {
        "artifacts": {"set4__deck_detail__1": {"object_path": obj("deck_1_v2")}}
    }
    routes[f"/release-v3/{obj('deck_1_v2')}"] = changed

    result, _ = harvest(routes, cache_dir=tmp_path)
    assert result.from_cache == 0
    assert result.decks[0]["_zones"]["main"] == {"OGN-042": 1}


def test_a_corrupt_cache_entry_is_refetched(tmp_path):
    routes = routes_for({"1": deck_object(deck_id="1")})
    harvest(routes, cache_dir=tmp_path)
    for path in (tmp_path / "riftools" / "objects").glob("*.json"):
        path.write_text("{ not json", encoding="utf-8")
    result, _ = harvest(routes, cache_dir=tmp_path)
    assert result.ok and len(result.decks) == 1


def test_the_manifests_are_read_once_not_per_deck():
    decks = {str(i): deck_object(deck_id=str(i)) for i in range(6)}
    _, client = harvest(routes_for(decks))
    details = [c for c in client.calls if "set4_details" in c]
    assert len(details) == 1, f"details manifest fetched {len(details)} times"


# -- helpers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [("OGN-042/298", "OGN-042"), ("OGN-042", "OGN-042"), ("", ""), (None, "")],
)
def test_strip_code(raw, expected):
    assert strip_code(raw) == expected


def test_two_events_sharing_a_name_do_not_share_a_slug():
    a = event_slug("operator://riftools/x/spring-open-2026-07-25", "Spring Open")
    b = event_slug("operator://riftools/x/spring-open-2026-08-01", "Spring Open")
    assert a != b


def test_an_all_chinese_event_name_still_gets_a_slug():
    slug = event_slug("wechat://riftbound-china/activityShop/178961", "武汉公开赛")
    assert slug and slug.strip("-")


def test_cards_without_a_code_fall_back_to_their_name():
    nameless = deck_object(
        deck_id="1",
        main=[{"card_name": "Mystery Card", "card_type": "Unit", "count": 2,
               "image_public_code": ""}],
    )
    result, _ = harvest(routes_for({"1": nameless}))
    assert result.decks[0]["_named_zones"]["main"] == {"Mystery Card": 2}
