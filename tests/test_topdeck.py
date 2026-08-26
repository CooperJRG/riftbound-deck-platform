"""The TopDeck.gg tournament source.

Shapes are copied from real API responses. The awkward ones are deliberate: standings
carry no explicit place field (position *is* the finish), a player who published no list
still appears in standings, and a couple of decks in the wild use alternate zone labels.
"""

from __future__ import annotations

import json

import pytest

from riftbound.data.meta_normalize import deck_from_payload, normalize_meta_decks
from riftbound.data.sources.http import HttpClient, HttpError
from riftbound.data.sources.topdeck import (
    ATTRIBUTION,
    MissingApiKey,
    TopDeckSource,
    api_key_from_env,
    parse_deck_object,
)
from tests.test_sources import FakeResponse


def deck_obj(**overrides):
    obj = {
        "Legend": {"Lillia, Bashful Bloom": {"id": "UNL-189", "count": 1}},
        "Champion": {"Lillia, Fae Fawn": {"id": "UNL-082", "count": 1}},
        "Runes": {
            "Calm Rune": {"id": "OGN-042", "count": 6},
            "Mind Rune": {"id": "OGN-089", "count": 6},
        },
        "Battlefields": {"Dusk Rose Lab": {"id": "UNL-209", "count": 3}},
        "Mainboard": {"Brutalizer": {"id": "SFD-042", "count": 2}},
        "Sideboard": {"Charm": {"id": "OGN-043", "count": 1}},
        "metadata": {"game": "Riftbound", "format": "Constructed"},
    }
    obj.update(overrides)
    return obj


def event(**overrides):
    ev = {
        "TID": "convergence-2",
        "tournamentName": "Convergence #2",
        "startDate": 1786806000,
        "game": "Riftbound",
        "format": "Constructed",
        "standings": [
            {"name": "Winner", "wins": 11, "losses": 0, "leader": "Lillia, Bashful Bloom",
             "deckObj": deck_obj(), "decklist": "..."},
            {"name": "Runner Up", "wins": 8, "losses": 2, "leader": "Lillia, Bashful Bloom",
             "deckObj": deck_obj(), "decklist": "..."},
            {"name": "No List", "wins": 4, "losses": 4, "deckObj": None},
        ],
    }
    ev.update(overrides)
    return ev


def fake_post(payload):
    def opener(request, timeout=None):  # noqa: ARG001
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    return opener


def quiet() -> HttpClient:
    return HttpClient(max_attempts=1, min_interval=0.0, base_backoff=0.0)


# -- deck object parsing ------------------------------------------------------


def test_zones_arrive_already_separated():
    """Unlike a flat decklist, TopDeck states the zones — including the champion."""
    zones, unknown = parse_deck_object(deck_obj())
    assert unknown == []
    assert zones["legend"] == {"UNL-189": 1}
    assert zones["champion"] == {"UNL-082": 1}
    assert zones["runes"] == {"OGN-042": 6, "OGN-089": 6}
    assert zones["main"] == {"SFD-042": 2}
    assert zones["sideboard"] == {"OGN-043": 1}


def test_metadata_is_not_treated_as_a_zone():
    zones, unknown = parse_deck_object(deck_obj())
    assert "metadata" not in zones
    assert unknown == []


@pytest.mark.parametrize("label,zone", [("Main Deck", "main"), ("Rune Pool", "runes")])
def test_alternate_zone_labels_are_understood(label, zone):
    """Two decks in the live data use these spellings."""
    zones, unknown = parse_deck_object({label: {"X": {"id": "OGN-001", "count": 2}}})
    assert zones[zone] == {"OGN-001": 2}
    assert unknown == []


def test_an_unrecognised_zone_is_reported_not_silently_dropped():
    """A new zone upstream must be visible, not quietly remove cards from every list."""
    zones, unknown = parse_deck_object({"Command Zone": {"X": {"id": "OGN-001", "count": 1}}})
    assert zones == {}
    assert unknown == ["Command Zone"]


def test_collector_codes_are_upper_cased():
    zones, _ = parse_deck_object({"Runes": {"r": {"id": "ven-r02a", "count": 6}}})
    assert zones["runes"] == {"VEN-R02A": 6}


def test_a_missing_deck_object_yields_nothing():
    assert parse_deck_object(None) == ({}, [])
    assert parse_deck_object("not a dict") == ({}, [])


# -- shaping ------------------------------------------------------------------


def test_a_bulk_response_becomes_tournaments_standings_and_decks(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_post([event()]))
    result = TopDeckSource(api_key="k", client=quiet()).fetch()
    assert result.ok
    assert len(result.tournaments) == 1
    assert len(result.standings) == 3
    assert len(result.decks) == 2, "the player with no list still gets a standing"


def test_standing_position_is_the_finish(monkeypatch):
    """There is no explicit place field; the array is returned in finishing order."""
    monkeypatch.setattr("urllib.request.urlopen", fake_post([event()]))
    result = TopDeckSource(api_key="k", client=quiet()).fetch()
    assert [s["place"] for s in result.standings] == [1, 2, 3]
    assert result.standings[0]["player_name"] == "Winner"


def test_win_loss_records_are_carried(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_post([event()]))
    result = TopDeckSource(api_key="k", client=quiet()).fetch()
    assert result.standings[0]["record"] == "11-0"


def test_field_size_comes_from_the_standings(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_post([event()]))
    result = TopDeckSource(api_key="k", client=quiet()).fetch()
    assert result.tournaments[0]["players"] == 3
    assert result.tournaments[0]["winner"] == "Winner"


def test_every_topdeck_deck_is_tournament_evidence(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_post([event()]))
    result = TopDeckSource(api_key="k", client=quiet()).fetch()
    assert all(d["is_tournament"] == "1" for d in result.decks)


# -- normalisation ------------------------------------------------------------


def test_a_topdeck_deck_normalises_without_inferring_the_champion(catalog):
    """The flat-map path guesses the champion; here the source states it."""
    payload = {
        "_slug": "e::1",
        "_zones": {
            "legend": {catalog.get("vi-piltover-enforcer").printings[0].code: 1},
            "champion": {catalog.get("vi-destructive").printings[0].code: 3},
            "main": {catalog.get("brazen-buccaneer").printings[0].code: 3},
            "runes": {catalog.get("fury-rune").printings[0].code: 12},
            "battlefields": {catalog.get("the-arena").printings[0].code: 3},
            "sideboard": {catalog.get("harpoon-squad").printings[0].code: 2},
        },
        "humanname": "Vi",
    }
    deck, unresolved = deck_from_payload(payload, catalog=catalog)
    assert unresolved == ()
    assert deck.legend_id == "vi-piltover-enforcer"
    assert deck.champion_id == "vi-destructive"
    assert deck.runes == {"fury-rune": 12}
    assert deck.sideboard == {"harpoon-squad": 2}
    assert len(deck.battlefields) == 3, "a count of 3 means three battlefields"


def test_unknown_codes_in_a_topdeck_deck_are_reported(catalog):
    payload = {
        "_slug": "e::1",
        "_zones": {"main": {"ZZZ-999": 2, catalog.get("brazen-buccaneer").printings[0].code: 3}},
    }
    deck, unresolved = deck_from_payload(payload, catalog=catalog)
    assert unresolved == ("ZZZ-999",)
    assert deck.main == {"brazen-buccaneer": 3}


def test_provenance_points_at_the_event(catalog):
    from riftbound.domain.meta import Standing, Tournament

    payload = {
        "_slug": "conv::1", "_source": "topdeck", "public": "1", "is_tournament": "1",
        "_tournament_url": "https://topdeck.gg/event/conv",
        "_zones": {"main": {catalog.get("brazen-buccaneer").printings[0].code: 3}},
    }
    decks = normalize_meta_decks(
        [payload], catalog=catalog,
        standings=[Standing("conv", 1, "Champ", "conv::1")],
        tournaments=[Tournament("1", "conv", "Convergence #2", "2026-08-15", "Constructed", 257)],
    )
    prov = decks[0].provenance
    assert prov.source == "topdeck"
    assert prov.url == "https://topdeck.gg/event/conv"
    assert prov.describe() == "1st of 257 at Convergence #2"


# -- credentials and failure --------------------------------------------------


def test_a_missing_api_key_says_where_to_put_one(monkeypatch):
    monkeypatch.delenv("RB_TOPDECK_API_KEY", raising=False)
    with pytest.raises(MissingApiKey, match="RB_TOPDECK_API_KEY"):
        api_key_from_env()


def test_a_missing_key_fails_the_source_without_raising(monkeypatch):
    monkeypatch.delenv("RB_TOPDECK_API_KEY", raising=False)
    result = TopDeckSource(client=quiet()).fetch()
    assert result.ok is False
    assert "RB_TOPDECK_API_KEY" in result.error


def test_the_api_key_never_appears_in_an_error(monkeypatch):
    """An error string can reach a log line and a snapshot manifest."""
    import urllib.error

    def boom(request, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError("https://topdeck.gg/api/v2/tournaments?k=sekrit",
                                     401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    result = TopDeckSource(api_key="sekrit", client=quiet()).fetch()
    assert result.ok is False
    assert "sekrit" not in result.error
    assert "***" in result.error or "401" in result.error


def test_a_non_array_response_is_a_failure(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_post({"error": "bad request"}))
    result = TopDeckSource(api_key="k", client=quiet()).fetch()
    assert result.ok is False


def test_the_key_is_sent_as_the_authorization_header(monkeypatch):
    seen: dict[str, str] = {}

    def capture(request, timeout=None):  # noqa: ARG001
        seen.update(request.headers)
        return FakeResponse(b"[]")

    monkeypatch.setattr("urllib.request.urlopen", capture)
    TopDeckSource(api_key="my-key", client=quiet()).fetch()
    # urllib title-cases header names.
    assert seen.get("Authorization") == "my-key"


def test_attribution_is_declared():
    """TopDeck's terms require a visible credit and a link back."""
    assert ATTRIBUTION["url"] == "https://topdeck.gg"
    assert ATTRIBUTION["text"]


def test_a_snapshot_records_the_attribution_it_owes(tmp_path, catalog):
    from riftbound.data.meta_snapshot import read_snapshot, write_snapshot

    payload = {
        "_slug": "e::1", "_source": "topdeck", "public": "1", "is_tournament": "1",
        "_zones": {"main": {catalog.get("brazen-buccaneer").printings[0].code: 3}},
    }
    decks = normalize_meta_decks([payload] * 1, catalog=catalog)
    written = write_snapshot(tmp_path, decks, [], [], attribution=[dict(ATTRIBUTION)])
    assert read_snapshot(written.path).manifest.attribution[0]["url"] == "https://topdeck.gg"


def test_the_chosen_champion_counts_toward_the_main_deck(catalog):
    """TopDeck lists the champion in its own zone without repeating it in Mainboard.

    Riftbound's chosen champion is part of the 40-card main deck, so those copies have
    to be folded in — otherwise 1,384 of 2,861 live decks read as 39 cards and fail
    legality for a reason that is our parsing, not their deck.
    """
    code = lambda cid: catalog.get(cid).printings[0].code  # noqa: E731
    main = {code(f"filler-{i:02d}"): 3 for i in range(1, 10)}   # 27
    main[code("brazen-buccaneer")] = 3                          # 30
    main[code("harpoon-squad")] = 3                             # 33
    main[code("showcase-only")] = 3                             # 36
    main[code("singular-relic")] = 1                            # 37
    payload = {
        "_slug": "e::1",
        "_zones": {
            "legend": {code("vi-piltover-enforcer"): 1},
            "champion": {code("vi-destructive"): 3},             # 37 + 3 = 40
            "main": main,
            "runes": {code("fury-rune"): 12},
        },
    }
    deck, _ = deck_from_payload(payload, catalog=catalog)
    assert deck.champion_id == "vi-destructive"
    assert deck.main["vi-destructive"] == 3
    assert deck.main_total == 40


def test_a_champion_already_in_the_mainboard_is_not_double_counted(catalog):
    """106 live decks list the champion in both zones; adding twice would give 41."""
    code = lambda cid: catalog.get(cid).printings[0].code  # noqa: E731
    main = {code(f"filler-{i:02d}"): 3 for i in range(1, 10)}
    main[code("brazen-buccaneer")] = 3
    main[code("harpoon-squad")] = 3
    main[code("showcase-only")] = 3
    main[code("singular-relic")] = 1
    main[code("vi-destructive")] = 3       # already present -> 40
    payload = {
        "_slug": "e::2",
        "_zones": {
            "champion": {code("vi-destructive"): 3},
            "main": main,
            "runes": {code("fury-rune"): 12},
        },
    }
    deck, _ = deck_from_payload(payload, catalog=catalog)
    assert deck.main["vi-destructive"] == 3
    assert deck.main_total == 40


def test_the_champion_is_inferred_when_the_source_omits_one(catalog):
    """TopDeck records no champion for 1,371 of 2,861 live decks.

    Without a fallback those all fail legality for "no chosen champion" — a gap in the
    feed, not a fault in the deck.
    """
    code = lambda cid: catalog.get(cid).printings[0].code  # noqa: E731
    main = {code(f"filler-{i:02d}"): 3 for i in range(1, 10)}
    main[code("vi-destructive")] = 3
    main[code("brazen-buccaneer")] = 3
    main[code("harpoon-squad")] = 3
    main[code("showcase-only")] = 3
    main[code("singular-relic")] = 1
    payload = {
        "_slug": "e::3",
        "_zones": {
            "legend": {code("vi-piltover-enforcer"): 1},
            "main": main,                      # no champion zone at all
            "runes": {code("fury-rune"): 12},
        },
    }
    deck, _ = deck_from_payload(payload, catalog=catalog)
    assert deck.champion_id == "vi-destructive"
    assert deck.main_total == 40
