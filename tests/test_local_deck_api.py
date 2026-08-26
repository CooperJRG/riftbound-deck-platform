"""The local Riftbound Deck API source (RiftDecks community decks).

Shapes copied from real responses. The important differences from TopDeck: cards arrive
by *name* rather than collector code, sections are gameplay types rather than zones, and
placements are free text ("1st", "Top256", "111th").
"""

from __future__ import annotations

import json

import pytest

from riftbound.data.meta_normalize import deck_from_payload, normalize_meta_decks
from riftbound.data.sources.http import HttpClient
from riftbound.data.sources.local_deck_api import (
    ATTRIBUTION,
    LocalDeckApiSource,
    parse_placement,
    section_zones,
)
from tests.test_sources import FakeResponse


def card(name, section, quantity=1):
    return {"card_name": name, "section": section, "quantity": quantity, "line_no": 1}


def deck_detail(catalog, deck_id=260368, **overrides):
    n = lambda cid: catalog.get(cid).name  # noqa: E731
    detail = {
        "id": deck_id,
        "deck_name": "Vi Aggro",
        "player": "someone",
        "legend": n("vi-piltover-enforcer"),
        "metagame": "VENDETTA",
        "placement": "1st",
        "record": "3-0-1",
        "event": "Sunday Evening Vendetta Skirmish",
        "venue": "Taverna di Sans - Genova",
        "event_players": 12,
        "published_date": "2026-08-24",
        "quality_score": 87.8,
        "quality_tier": "elite",
        "source_url": "https://riftdecks.com/riftbound-metagame/deck-vi-aggro-260368",
        "cards": [
            card(n("vi-piltover-enforcer"), "legend", 1),
            card(n("vi-destructive"), "champion", 3),
            card(n("brazen-buccaneer"), "unit", 3),
            card(n("singular-relic"), "gear", 1),
            card(n("harpoon-squad"), "spell", 3),
            card(n("fury-rune"), "runes", 12),
            card(n("the-arena"), "battlefields", 3),
            card(n("showcase-only"), "sideboard", 10),
        ],
    }
    detail.update(overrides)
    return detail


def fake_api(catalog, details=None, total=None):
    """Serve /v1/decks and /v1/decks/{id} from in-memory fixtures."""
    details = details or [deck_detail(catalog)]
    by_id = {str(d["id"]): d for d in details}

    def opener(request, timeout=None):  # noqa: ARG001
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/v1/decks/" in url:
            deck_id = url.rsplit("/", 1)[-1]
            body = by_id.get(deck_id)
            return FakeResponse(json.dumps(body or {}).encode("utf-8"))
        payload = {
            "total": total if total is not None else len(details),
            "limit": 100,
            "offset": 0,
            "decks": [{"id": d["id"]} for d in details],
        }
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    return opener


def quiet() -> HttpClient:
    return HttpClient(max_attempts=1, min_interval=0.0, base_backoff=0.0)


# -- placements ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("1st", 1), ("2nd", 2), ("3rd", 3), ("9th", 9), ("111th", 111), ("443rd", 443)],
)
def test_ordinal_placements_parse(text, expected):
    assert parse_placement(text) == expected


@pytest.mark.parametrize("text,expected", [("Top8", 8), ("Top4", 4), ("Top256", 256)])
def test_bracket_placements_take_the_worst_case_in_the_bracket(text, expected):
    """"Top256" means somewhere in 129-256; reading it as 256 is the safe end."""
    assert parse_placement(text) == expected


def test_a_missing_placement_is_not_a_finish():
    assert parse_placement("") == 0
    assert parse_placement(None) == 0
    assert parse_placement("dropped") == 0


# -- sections -> zones --------------------------------------------------------


def test_gameplay_sections_collapse_into_the_main_deck():
    zones, unknown = section_zones([
        card("A", "unit", 3), card("B", "gear", 2), card("C", "spell", 1),
    ])
    assert zones["main"] == {"A": 3, "B": 2, "C": 1}
    assert unknown == []


def test_each_zone_is_kept_separate():
    zones, _ = section_zones([
        card("L", "legend"), card("C", "champion"),
        card("R", "runes", 12), card("B", "battlefields", 3), card("S", "sideboard", 10),
    ])
    assert set(zones) == {"legend", "champion", "runes", "battlefields", "sideboard"}


def test_an_unrecognised_section_is_reported():
    zones, unknown = section_zones([card("X", "command-zone", 1)])
    assert zones == {}
    assert unknown == ["command-zone"]


def test_repeated_names_in_one_section_are_summed():
    zones, _ = section_zones([card("A", "unit", 2), card("A", "unit", 1)])
    assert zones["main"] == {"A": 3}


# -- name resolution ----------------------------------------------------------


def test_card_names_resolve_even_with_different_punctuation(catalog):
    """RiftDecks writes "Irelia, Blade Dancer" where the catalogue has a dash.

    All 758 card lines in a live sample resolved, because card_id is
    punctuation-insensitive by design.
    """
    real = catalog.get("vi-destructive").name           # "Vi - Destructive"
    comma = real.replace(" - ", ", ")                    # "Vi, Destructive"
    payload = {"_slug": "riftdecks::1", "_named_zones": {"main": {comma: 3}}}
    deck, unresolved = deck_from_payload(payload, catalog=catalog)
    assert unresolved == ()
    assert deck.main == {"vi-destructive": 3}


def test_an_unknown_name_is_reported_not_dropped(catalog):
    payload = {
        "_slug": "riftdecks::1",
        "_named_zones": {"main": {"No Such Card": 2, catalog.get("brazen-buccaneer").name: 3}},
    }
    deck, unresolved = deck_from_payload(payload, catalog=catalog)
    assert unresolved == ("No Such Card",)
    assert deck.main == {"brazen-buccaneer": 3}


def test_a_full_deck_normalises_to_legal_zone_counts(catalog):
    zones, _ = section_zones(deck_detail(catalog)["cards"])
    payload = {"_slug": "riftdecks::1", "_named_zones": zones}
    deck, unresolved = deck_from_payload(payload, catalog=catalog)
    assert unresolved == ()
    assert deck.legend_id == "vi-piltover-enforcer"
    assert deck.champion_id == "vi-destructive"
    assert deck.rune_total == 12
    assert len(deck.battlefields) == 3
    assert deck.sideboard_total == 10, "the field plays 10-card sideboards"
    assert deck.main["vi-destructive"] == 3, "the champion counts toward the main deck"


# -- the source ---------------------------------------------------------------


def test_a_harvest_yields_decks_events_and_standings(catalog, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_api(catalog))
    result = LocalDeckApiSource(client=quiet()).fetch()
    assert result.ok
    assert len(result.decks) == 1
    assert len(result.tournaments) == 1
    assert len(result.standings) == 1
    assert result.standings[0]["place"] == 1
    assert result.standings[0]["field_size"] == 12


def test_a_deck_with_no_finish_is_not_given_an_event(catalog, monkeypatch):
    """Without a placement there is no tournament evidence to claim."""
    detail = deck_detail(catalog, placement="", event="")
    monkeypatch.setattr("urllib.request.urlopen", fake_api(catalog, [detail]))
    result = LocalDeckApiSource(client=quiet()).fetch()
    assert result.tournaments == []
    assert result.standings == []
    assert result.decks[0]["is_tournament"] == "0"


def test_quality_is_carried_through_to_provenance(catalog, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", fake_api(catalog))
    result = LocalDeckApiSource(client=quiet()).fetch()
    decks = normalize_meta_decks(result.decks, catalog=catalog)
    assert decks[0].provenance.quality == pytest.approx(87.8)
    assert decks[0].provenance.source == "riftdecks"
    assert decks[0].provenance.url.startswith("https://riftdecks.com/")


def test_quality_stands_in_for_a_view_count(catalog):
    """A curated score answers "how good is this" better than views do."""
    from riftbound.domain.meta_scoring import popularity_score

    assert popularity_score(views=0, quality=90.0) == pytest.approx(0.9)
    assert popularity_score(views=1000, quality=0.0) > 0
    # A quality score beats a view count for the same deck.
    assert popularity_score(views=10, quality=90.0) > popularity_score(views=10, quality=0.0)


def test_quality_cannot_outrank_real_evidence(catalog):
    """The popularity term is 5% of the score; it must not reorder the tiers."""
    from datetime import datetime, timezone
    from riftbound.domain.meta import Standing, Tournament
    from riftbound.domain.meta_scoring import score_deck

    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    zones, _ = section_zones(deck_detail(catalog)["cards"])
    base = {"_named_zones": zones, "_source": "riftdecks", "public": "1"}

    top_quality = normalize_meta_decks(
        [{**base, "_slug": "riftdecks::a", "_quality": 100.0,
          "published_date": "2026-08-25"}],
        catalog=catalog,
    )[0]
    placed = normalize_meta_decks(
        [{**base, "_slug": "riftdecks::b", "_quality": 0.0, "published_date": "2026-07-01"}],
        catalog=catalog,
        standings=[Standing("e", 1, "A", "riftdecks::b")],
        tournaments=[Tournament("1", "e", "Big", "2026-07-01", "Constructed", 200)],
    )[0]
    assert score_deck(placed, now=now).total > score_deck(top_quality, now=now).total


def test_the_source_reports_an_unreachable_service(monkeypatch):
    import urllib.error

    def refused(request, timeout=None):  # noqa: ARG001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", refused)
    result = LocalDeckApiSource(client=quiet()).fetch()
    assert result.ok is False
    assert "RB_LOCAL_DECK_API" in result.error, "tells the operator how to point elsewhere"


def test_the_base_url_is_configurable(monkeypatch):
    monkeypatch.setenv("RB_LOCAL_DECK_API", "http://example.test:9999/")
    from riftbound.data.sources.local_deck_api import base_url_from_env

    assert base_url_from_env() == "http://example.test:9999"


def test_attribution_is_declared():
    assert ATTRIBUTION["url"] == "https://riftdecks.com"
    assert ATTRIBUTION["text"]


def test_a_source_without_a_popularity_signal_is_not_penalised():
    """Absence of evidence must not be scored as evidence of absence.

    Scoring "no signal" as zero gave every deck from a source that publishes a quality
    score a systematic edge over one that does not — a difference between sources, not
    between decks.
    """
    from riftbound.domain.meta_scoring import NO_POPULARITY_SIGNAL, popularity_score

    assert popularity_score(views=0, quality=0.0) == NO_POPULARITY_SIGNAL
    assert 0 < NO_POPULARITY_SIGNAL < 1


def test_winning_a_major_still_beats_a_top_five_percent_finish(catalog):
    """1st of 257 should outrank 111th of 2224 once source bias is removed."""
    from datetime import datetime, timezone
    from riftbound.domain.meta import Standing, Tournament
    from riftbound.domain.meta_scoring import score_deck

    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    zones, _ = section_zones(deck_detail(catalog)["cards"])
    base = {"_named_zones": zones, "public": "1", "published_date": "2026-08-20"}

    winner = normalize_meta_decks(
        [{**base, "_slug": "a", "_source": "topdeck"}], catalog=catalog,
        standings=[Standing("e1", 1, "A", "a")],
        tournaments=[Tournament("1", "e1", "Convergence", "2026-08-20", "Constructed", 257)],
    )[0]
    deep_run = normalize_meta_decks(
        [{**base, "_slug": "b", "_source": "riftdecks", "_quality": 95.0}], catalog=catalog,
        standings=[Standing("e2", 111, "B", "b")],
        tournaments=[Tournament("2", "e2", "Regional", "2026-08-20", "Constructed", 2224)],
    )[0]
    assert score_deck(winner, now=now).total > score_deck(deep_run, now=now).total
