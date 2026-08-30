"""The riftools snapshot source.

Nothing here touches the network. A fake client serves the snapshot shapes the live
service publishes, so the tests pin the *contract* -- which files are read, how a deck
becomes a payload, what happens when one is half-published -- rather than whatever the
archive happens to hold today.
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
    strip_code,
)

BASE = "https://riftools.test"
DECK_URL = "wechat://riftbound-china/cardGroup/249742"
EVENT_URL = "wechat://riftbound-china/activityShop/178961"


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


def card_row(name: str, code: str, card_type: str, count: int) -> dict[str, object]:
    return {
        "card_key": name.lower(),
        "card_name": name,
        "card_type": card_type,
        "count": count,
        "public_code": code,
    }


def snapshot(
    *,
    parse_status: str = "parsed",
    cards: list[dict[str, object]] | None = None,
    rank: int = 1,
) -> dict[str, object]:
    return {
        "deck": {
            "deck_name": "Irelia, Blade Dancer",
            "deck_url": DECK_URL,
            "event_date": "2026-08-29",
            "parse_status": parse_status,
            "placement": str(rank),
            "player_name": "adtoll",
            "rank": rank,
            "record": None,
            "region": "China",
            "tournament_name": "S4 Wuhan Regional Open 2026-08-29",
            "tournament_url": EVENT_URL,
        },
        "cards": cards
        if cards is not None
        else [
            card_row("Irelia - Blade Dancer", "SFD-195", "Legend", 1),
            card_row("Irelia - Fervent", "SFD-057/221", "Champion", 1),
            card_row("Scuttle Crab", "UNL-053/219", "Unit", 3),
            card_row("Calm Rune", "OGN-042/298", "Runes", 12),
            card_row("Targon's Peak", "OGN-289/298", "Battlefield", 3),
            card_row("Abandon", "UNL-131/219", "Sideboard", 2),
        ],
    }


def routes(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "/public-snapshots/manifest.current.json": {
            "deck_details": {"count": 1, "index_url": "/public-snapshots/deck-details/index.json"},
            "snapshots": {
                "tournaments-set4": {
                    "chunked": {
                        "chunks": [{"url": "/public-snapshots/t/0001.json"}],
                    }
                }
            },
        },
        "/public-snapshots/deck-details/index.json": {
            "details": {DECK_URL: "/public-snapshots/deck-details/abc.json"}
        },
        "/public-snapshots/t/0001.json": {
            "tournaments": {
                "items": [
                    {
                        "tournament_url": EVENT_URL,
                        "name": "S4 Wuhan Regional Open 2026-08-29",
                        "event_date": "2026-08-29",
                        "players": 1280,
                        "region": "China",
                    }
                ]
            }
        },
        "/public-snapshots/deck-details/abc.json": snapshot(),
    }
    base.update(overrides)
    return base


def harvest(**overrides: object) -> tuple[RiftoolsSource, object]:
    client = FakeClient(routes(**overrides))
    source = RiftoolsSource(base_url=BASE, client=client)  # type: ignore[arg-type]
    return source, source.fetch()


# -- the shape it produces ----------------------------------------------------


def test_a_snapshot_becomes_a_deck_payload():
    _, result = harvest()
    assert result.ok, result.error
    assert len(result.decks) == 1
    zones = result.decks[0]["_zones"]
    # Suffixes stripped, and the champion in a zone of its own so the normaliser can
    # take the source's word rather than inferring the nomination.
    assert zones["legend"] == {"SFD-195": 1}
    assert zones["champion"] == {"SFD-057": 1}
    assert zones["main"] == {"UNL-053": 3}
    assert zones["runes"] == {"OGN-042": 12}
    assert zones["battlefields"] == {"OGN-289": 3}
    assert zones["sideboard"] == {"UNL-131": 2}


def test_it_normalises_into_a_deck():
    """The payload has to survive the normaliser the other sources go through."""
    from riftbound.domain.cards import build_catalog

    legend = make_card(
        "vi-piltover-enforcer", "Vi - Piltover Enforcer",
        card_type="Legend", champion_tags=("Vi",), number="0101",
    )
    champion = make_card(
        "vi-relentless", "Vi - Relentless",
        super_type="Champion", champion_tags=("Vi",), number="0102",
    )
    filler = make_card("filler-one", "Filler One", number="0103")
    catalog = build_catalog([legend, champion, filler])

    def code(card_id: str) -> str:
        return catalog.get(card_id).printings[0].code

    cards = [
        card_row("Vi - Piltover Enforcer", code("vi-piltover-enforcer"), "Legend", 1),
        card_row("Vi - Relentless", code("vi-relentless"), "Champion", 1),
        card_row("Filler One", code("filler-one"), "Unit", 3),
    ]
    _, result = harvest(
        **{"/public-snapshots/deck-details/abc.json": snapshot(cards=cards)}
    )
    deck, unresolved = deck_from_payload(
        result.decks[0], catalog=catalog, main_deck_size=40
    )
    assert unresolved == ()
    assert deck.legend_id == "vi-piltover-enforcer"
    # The source states the nomination; the normaliser takes its word rather than
    # inferring one from champion tags.
    assert deck.champion_id == "vi-relentless"
    # The champion's copy folds into the main deck, as it does for every source.
    assert deck.main_total == 4


def test_standing_carries_the_placement():
    _, result = harvest()
    assert len(result.standings) == 1
    standing = result.standings[0]
    assert standing["place"] == 1
    assert standing["player_name"] == "adtoll"
    assert standing["deck_slug"] == result.decks[0]["_slug"]


def test_event_row_gets_its_field_size():
    _, result = harvest()
    assert len(result.tournaments) == 1
    event = result.tournaments[0]
    assert event["players"] == 1280
    assert event["decks_published"] == 1
    assert event["name"] == "S4 Wuhan Regional Open 2026-08-29"
    assert event["slug"] == result.standings[0]["tournament_slug"]


# -- what it refuses ----------------------------------------------------------


def test_unparsed_decks_are_counted_not_emitted():
    """A half-published list is a gap upstream, not a deck with missing cards."""
    _, result = harvest(
        **{"/public-snapshots/deck-details/abc.json": snapshot(parse_status="queued")}
    )
    assert result.decks == []
    assert result.unparsed == 1
    assert result.ok


def test_a_deck_with_no_cards_is_skipped():
    _, result = harvest(**{"/public-snapshots/deck-details/abc.json": snapshot(cards=[])})
    assert result.decks == []
    assert result.unparsed == 1


def test_a_failed_deck_fetch_does_not_fail_the_harvest():
    """One missing file costs one deck, not the run."""
    bad = routes()
    del bad["/public-snapshots/deck-details/abc.json"]
    client = FakeClient(bad)
    result = RiftoolsSource(base_url=BASE, client=client).fetch()  # type: ignore[arg-type]
    assert result.ok
    assert result.decks == []


def test_a_missing_manifest_fails_the_source_without_raising():
    client = FakeClient({})
    result = RiftoolsSource(base_url=BASE, client=client).fetch()  # type: ignore[arg-type]
    assert not result.ok
    assert "404" in result.error


def test_a_manifest_without_a_deck_index_is_an_error():
    client = FakeClient(routes(**{"/public-snapshots/manifest.current.json": {"snapshots": {}}}))
    result = RiftoolsSource(base_url=BASE, client=client).fetch()  # type: ignore[arg-type]
    assert not result.ok
    assert "index_url" in result.error


# -- the cap and the cache ----------------------------------------------------


def test_max_decks_caps_the_harvest():
    index = {f"deck://{n}": f"/public-snapshots/deck-details/{n}.json" for n in range(5)}
    extra: dict[str, object] = {
        "/public-snapshots/deck-details/index.json": {"details": index}
    }
    for n in range(5):
        extra[f"/public-snapshots/deck-details/{n}.json"] = snapshot()
    client = FakeClient(routes(**extra))
    result = RiftoolsSource(base_url=BASE, max_decks=2, client=client).fetch()  # type: ignore[arg-type]
    assert result.requested == 5
    assert len(result.decks) == 2
    assert any("capped at 2 of 5" in note for note in result.notes)


def test_a_cached_deck_is_not_refetched(tmp_path):
    """A parsed snapshot describes a finished event, so the cache is authoritative."""
    client = FakeClient(routes())
    source = RiftoolsSource(base_url=BASE, cache_dir=tmp_path, client=client)  # type: ignore[arg-type]
    first = source.fetch()
    assert first.from_cache == 0
    assert len(first.decks) == 1

    again = FakeClient(routes())
    warm = RiftoolsSource(base_url=BASE, cache_dir=tmp_path, client=again)  # type: ignore[arg-type]
    second = warm.fetch()
    assert second.from_cache == 1
    assert len(second.decks) == 1
    assert not any("deck-details/abc.json" in call for call in again.calls)


def test_a_corrupt_cache_entry_is_refetched(tmp_path):
    client = FakeClient(routes())
    source = RiftoolsSource(base_url=BASE, cache_dir=tmp_path, client=client)  # type: ignore[arg-type]
    source.fetch()
    for path in (tmp_path / "riftools" / "decks").glob("*.json"):
        path.write_text("{not json", encoding="utf-8")
    again = FakeClient(routes())
    result = RiftoolsSource(base_url=BASE, cache_dir=tmp_path, client=again).fetch()  # type: ignore[arg-type]
    assert len(result.decks) == 1
    assert result.from_cache == 0


# -- the small pieces ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OGN-042/298", "OGN-042"),
        ("SFD-057/221", "SFD-057"),
        ("UNL-145a/219", "UNL-145a"),
        ("SFD-195", "SFD-195"),
        ("", ""),
        (None, ""),
    ],
)
def test_strip_code(raw, expected):
    assert strip_code(raw) == expected


def test_two_events_sharing_a_name_do_not_share_a_slug():
    """"S4 Guangzhou City Challenge" happens more than once."""
    a = event_slug("wechat://riftbound-china/activityShop/1", "S4 Guangzhou City Challenge")
    b = event_slug("wechat://riftbound-china/activityShop/2", "S4 Guangzhou City Challenge")
    assert a != b


def test_an_all_chinese_event_name_still_gets_a_slug():
    """Slugifying the name alone would leave nothing at all."""
    slug = event_slug("wechat://riftbound-china/activityShop/178961", "武汉大区赛")
    assert slug
    assert "178961" in slug


def test_cards_without_a_code_fall_back_to_their_name():
    cards = [card_row("Scuttle Crab", "", "Unit", 3)]
    _, result = harvest(
        **{"/public-snapshots/deck-details/abc.json": snapshot(cards=cards)}
    )
    assert result.decks[0]["_named_zones"] == {"main": {"Scuttle Crab": 3}}


def test_the_index_is_read_once_not_per_deck():
    source, result = harvest()
    client = source._http  # type: ignore[attr-defined]
    index_calls = [c for c in client.calls if c.endswith("deck-details/index.json")]
    assert len(index_calls) == 1
    assert json.dumps(result.decks[0])  # payload stays JSON-serialisable for the cache
