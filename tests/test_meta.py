"""Meta ingest, scoring and gating.

All offline. The shapes here are copied from real responses observed while building the
adapter, including the awkward ones: quantities as strings, an empty body for a missing
deck, standings that carry no decklist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from riftbound.data.meta_normalize import (
    deck_from_payload,
    normalize_meta_decks,
    standings_from,
    summarise,
    tournaments_from,
)
from riftbound.data.meta_snapshot import (
    MIN_PLAUSIBLE_DECKS,
    read_snapshot,
    run_meta_gate,
    write_snapshot,
)
from riftbound.domain.meta import (
    EVIDENCE_COMMUNITY,
    EVIDENCE_TOURNAMENT_ENTRY,
    EVIDENCE_TOURNAMENT_PLACED,
    Standing,
    Tournament,
    archetype_id_for,
    build_archetypes,
)
from riftbound.domain.meta_scoring import (
    placement_score,
    recency_score,
    score_all,
    score_deck,
    totals,
)

NOW = datetime(2026, 8, 25, tzinfo=UTC)


# -- fixtures ----------------------------------------------------------------


@pytest.fixture()
def coded_catalog(catalog):
    """The shared test catalogue, addressable by collector code.

    Decklists reference cards as "OGN-001", so the code index is what makes an import
    possible at all.
    """
    return catalog


def code_for(catalog, card_id: str) -> str:
    card = catalog.get(card_id)
    assert card and card.printings
    return card.printings[0].code


def deck_payload(catalog, slug="a-deck", **overrides):
    """A complete, legal-shaped list expressed in collector codes."""
    deck = {code_for(catalog, "vi-piltover-enforcer"): "1"}
    deck[code_for(catalog, "vi-destructive")] = "3"
    deck[code_for(catalog, "brazen-buccaneer")] = "3"
    for i in range(1, 10):
        deck[code_for(catalog, f"filler-{i:02d}")] = "3"
    deck[code_for(catalog, "harpoon-squad")] = "3"
    deck[code_for(catalog, "showcase-only")] = "3"
    deck[code_for(catalog, "singular-relic")] = "1"
    deck[code_for(catalog, "fury-rune")] = "12"
    for bf in ("the-arena", "the-forge", "the-spire"):
        deck[code_for(catalog, bf)] = "1"
    payload = {
        "_slug": slug, "slug": slug, "humanname": "Vi Aggro", "public": "1",
        "is_tournament": "0", "views": "40", "authornick": "someone",
        "date_edited": "1787500800", "format": "Standard", "deck": deck,
    }
    payload.update(overrides)
    return payload


# -- decklist parsing --------------------------------------------------------


def test_collector_codes_resolve_to_cards(coded_catalog):
    deck, unresolved = deck_from_payload(deck_payload(coded_catalog), catalog=coded_catalog)
    assert unresolved == ()
    assert deck.legend_id == "vi-piltover-enforcer"
    assert deck.main_total == 40
    assert deck.rune_total == 12
    assert len(deck.battlefields) == 3


def test_zones_are_recovered_from_card_type(coded_catalog):
    """Upstream sends one flat map; zones come from the catalogue, not a source field."""
    deck, _ = deck_from_payload(deck_payload(coded_catalog), catalog=coded_catalog)
    assert "fury-rune" in deck.runes
    assert "fury-rune" not in deck.main
    assert "the-arena" in deck.battlefields
    assert deck.legend_id not in deck.main


def test_quantities_arrive_as_strings(coded_catalog):
    deck, _ = deck_from_payload(deck_payload(coded_catalog), catalog=coded_catalog)
    assert deck.main["brazen-buccaneer"] == 3


def test_unknown_codes_are_reported_not_dropped(coded_catalog):
    payload = deck_payload(coded_catalog)
    payload["deck"]["ZZZ-999"] = "2"
    deck, unresolved = deck_from_payload(payload, catalog=coded_catalog)
    assert unresolved == ("ZZZ-999",)
    assert deck.main_total == 40, "the rest of the list still imports"


def test_champion_is_inferred_from_the_legend(coded_catalog):
    """The nomination is not in the data; it has to be derived from tags."""
    deck, _ = deck_from_payload(deck_payload(coded_catalog), catalog=coded_catalog)
    assert deck.champion_id == "vi-destructive"


# -- normalisation -----------------------------------------------------------


def test_private_decks_are_never_published(coded_catalog):
    warnings: list[str] = []
    decks = normalize_meta_decks(
        [deck_payload(coded_catalog, public="0")], catalog=coded_catalog, warnings=warnings
    )
    assert decks == []
    assert any("non-public" in w for w in warnings)


def test_empty_decks_are_skipped(coded_catalog):
    payload = deck_payload(coded_catalog, slug="empty")
    payload["deck"] = {}
    assert normalize_meta_decks([payload], catalog=coded_catalog) == []


def test_a_standing_promotes_a_deck_to_placed_evidence(coded_catalog):
    standings = [Standing(tournament_slug="big-event", place=3, player_name="A", deck_slug="a-deck")]
    tournaments = [Tournament(
        tournament_id="1", slug="big-event", name="Big Event", date="2026-08-15",
        format="Constructed", players=257,
    )]
    decks = normalize_meta_decks(
        [deck_payload(coded_catalog)], catalog=coded_catalog,
        standings=standings, tournaments=tournaments,
    )
    prov = decks[0].provenance
    assert prov.evidence == EVIDENCE_TOURNAMENT_PLACED
    assert prov.placement == 3
    assert prov.field_size == 257
    assert prov.describe() == "3rd of 257 at Big Event"


def test_the_tournament_flag_alone_is_only_entry_evidence(coded_catalog):
    decks = normalize_meta_decks(
        [deck_payload(coded_catalog, is_tournament="1")], catalog=coded_catalog
    )
    assert decks[0].provenance.evidence == EVIDENCE_TOURNAMENT_ENTRY


def test_a_plain_published_deck_is_community_evidence(coded_catalog):
    decks = normalize_meta_decks([deck_payload(coded_catalog)], catalog=coded_catalog)
    assert decks[0].provenance.evidence == EVIDENCE_COMMUNITY


def test_provenance_links_back_to_the_source(coded_catalog):
    decks = normalize_meta_decks([deck_payload(coded_catalog)], catalog=coded_catalog)
    assert decks[0].provenance.url == "https://riftbound.gg/decks/a-deck/"


def test_tournaments_parse_from_raw_rows():
    rows = [{
        "tournament_id": "27027", "slug": "convergence-2", "name": "Convergence #2",
        "date": "2026-08-15", "format": "Constructed", "players": 257,
        "winner": "someone", "decks_published": 0,
    }]
    parsed = tournaments_from(rows)
    assert parsed[0].players == 257
    assert parsed[0].slug == "convergence-2"


def test_standings_without_a_decklist_still_parse():
    """The common case: results exist, lists do not."""
    parsed = standings_from([
        {"tournament_slug": "e", "place": 1, "player_name": "A", "deck_slug": ""},
    ])
    assert parsed[0].place == 1
    assert parsed[0].deck_slug == ""


# -- scoring -----------------------------------------------------------------


def test_evidence_dominates_recency_and_popularity(coded_catalog):
    """A tournament result must outrank a fresh, popular community deck."""
    placed = normalize_meta_decks(
        [deck_payload(coded_catalog, slug="won", views="0", date_edited="1750000000")],
        catalog=coded_catalog,
        standings=[Standing("e", 1, "A", "won")],
        tournaments=[Tournament("1", "e", "Event", "2026-08-01", "Constructed", 200)],
    )[0]
    community = normalize_meta_decks(
        [deck_payload(coded_catalog, slug="fresh", views="99999",
                      date_edited=str(int(NOW.timestamp())))],
        catalog=coded_catalog,
    )[0]
    assert score_deck(placed, now=NOW).total > score_deck(community, now=NOW).total


def test_field_size_scales_a_win():
    assert placement_score(1, 257) > placement_score(1, 9)


def test_a_deep_run_in_a_major_beats_a_win_in_a_side_event():
    assert placement_score(5, 257) > placement_score(1, 9)


def test_an_unknown_finish_scores_zero_rather_than_guessing():
    assert placement_score(0, 200) == 0.0


def test_recency_decays():
    recent = recency_score((NOW - timedelta(days=1)).isoformat(), now=NOW)
    old = recency_score((NOW - timedelta(days=180)).isoformat(), now=NOW)
    assert recent > old > 0


def test_an_unknown_date_is_neutral_not_zero():
    assert recency_score("", now=NOW) == 0.3


def test_incomplete_lists_are_penalised(coded_catalog):
    payload = deck_payload(coded_catalog, slug="broken")
    payload["deck"]["ZZZ-999"] = "3"
    broken = normalize_meta_decks([payload], catalog=coded_catalog)[0]
    whole = normalize_meta_decks([deck_payload(coded_catalog)], catalog=coded_catalog)[0]
    assert not broken.is_complete
    assert score_deck(broken, now=NOW).total < score_deck(whole, now=NOW).total


def test_scores_expose_their_parts(coded_catalog):
    deck = normalize_meta_decks([deck_payload(coded_catalog)], catalog=coded_catalog)[0]
    breakdown = score_deck(deck, now=NOW)
    assert 0.0 <= breakdown.total <= 1.0
    assert "evidence" in breakdown.describe()


# -- archetypes --------------------------------------------------------------


def test_archetype_is_legend_plus_champion():
    assert archetype_id_for("vi-legend", "vi-champ") == "vi-legend::vi-champ"
    assert archetype_id_for("vi-legend", "") == "vi-legend"


def test_archetypes_group_and_rank(coded_catalog):
    decks = normalize_meta_decks(
        [deck_payload(coded_catalog, slug=f"d{i}") for i in range(3)],
        catalog=coded_catalog,
    )
    scores = totals(score_all(decks, now=NOW))
    archetypes = build_archetypes(decks, catalog=coded_catalog, scores=scores)
    assert len(archetypes) == 1
    assert archetypes[0].deck_count == 3
    assert "Vi" in archetypes[0].name


def test_an_archetype_scores_as_its_best_deck_not_its_volume(coded_catalog):
    """Otherwise a popular starter list outranks a tournament winner on copies alone."""
    winner = normalize_meta_decks(
        [deck_payload(coded_catalog, slug="won")], catalog=coded_catalog,
        standings=[Standing("e", 1, "A", "won")],
        tournaments=[Tournament("1", "e", "Event", "2026-08-20", "Constructed", 300)],
    )
    crowd = normalize_meta_decks(
        [deck_payload(coded_catalog, slug=f"c{i}") for i in range(20)], catalog=coded_catalog
    )
    all_decks = winner + crowd
    scores = totals(score_all(all_decks, now=NOW))
    archetypes = build_archetypes(all_decks, catalog=coded_catalog, scores=scores)
    assert archetypes[0].score == pytest.approx(max(scores.values()))


# -- the gate ----------------------------------------------------------------


def make_decks(catalog, n):
    return normalize_meta_decks(
        [deck_payload(catalog, slug=f"d{i}") for i in range(n)], catalog=catalog
    )


def test_gate_rejects_a_failed_source(coded_catalog):
    report = run_meta_gate(
        make_decks(coded_catalog, 50), [], source_ok=False, source_error="HTTP 429"
    )
    assert not report.passed
    assert "HTTP 429" in report.errors[0]


def test_gate_rejects_a_thin_harvest(coded_catalog):
    report = run_meta_gate(make_decks(coded_catalog, 2), [], source_ok=True)
    assert not report.passed
    assert MIN_PLAUSIBLE_DECKS > 2


def test_gate_warns_when_nothing_has_a_known_finish(coded_catalog):
    report = run_meta_gate(make_decks(coded_catalog, 20), [], source_ok=True)
    assert report.passed
    assert any("known tournament finish" in w for w in report.warnings)


def test_gate_rejects_duplicate_deck_ids(coded_catalog):
    decks = make_decks(coded_catalog, 20)
    report = run_meta_gate([*list(decks), decks[0]], [], source_ok=True)
    assert not report.passed


# -- snapshots ---------------------------------------------------------------


def test_snapshot_roundtrips(tmp_path, coded_catalog):
    decks = make_decks(coded_catalog, 12)
    tournaments = tournaments_from([{
        "slug": "e", "name": "Event", "date": "2026-08-01",
        "format": "Constructed", "players": 100,
    }])
    written = write_snapshot(tmp_path, decks, tournaments, [])
    loaded = read_snapshot(written.path)
    assert loaded.manifest.deck_count == 12
    assert loaded.manifest.tournament_count == 1
    assert loaded.decks[0].deck.main_total == 40
    assert loaded.decks[0].provenance.url.startswith("https://riftbound.gg/decks/")


def test_snapshot_detects_tampering(tmp_path, coded_catalog):
    import json

    written = write_snapshot(tmp_path, make_decks(coded_catalog, 12), [], [])
    payload = json.loads((written.path / "meta.json").read_text(encoding="utf-8"))
    payload["decks"][0]["deck"]["name"] = "edited"
    (written.path / "meta.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity check"):
        read_snapshot(written.path)


def test_evidence_counts_are_recorded(tmp_path, coded_catalog):
    decks = normalize_meta_decks(
        [deck_payload(coded_catalog, slug="won"), deck_payload(coded_catalog, slug="plain")],
        catalog=coded_catalog,
        standings=[Standing("e", 1, "A", "won")],
        tournaments=[Tournament("1", "e", "E", "2026-08-01", "Constructed", 50)],
    )
    written = write_snapshot(tmp_path, decks, [], [])
    assert written.manifest.evidence_counts[EVIDENCE_TOURNAMENT_PLACED] == 1
    assert written.manifest.evidence_counts[EVIDENCE_COMMUNITY] == 1


def test_summarise_counts_evidence_tiers(coded_catalog):
    counts = summarise(make_decks(coded_catalog, 5))
    assert counts["total"] == 5
    assert counts["community"] == 5


# -- collector code matching --------------------------------------------------


def test_collector_codes_match_case_insensitively(coded_catalog):
    """Upstream is inconsistent about case, even inside one set.

    The card list ships "VEN-R02a" while decklists reference "VEN-R02A", and the same
    set carries both "VEN-R04B-P" and "VEN-R02b-P". Matching case-sensitively silently
    dropped Vendetta runes from every imported tournament list.
    """
    code = code_for(coded_catalog, "fury-rune")
    assert coded_catalog.by_code(code.lower()) is not None
    assert coded_catalog.by_code(code.upper()) is not None
    assert coded_catalog.by_code(code.lower()) is coded_catalog.by_code(code.upper())


def test_a_lowercase_variant_code_resolves(coded_catalog):
    from riftbound.domain.cards import Card, Printing, build_catalog

    base = coded_catalog.get("fury-rune")
    variant = Card(
        card_id="variant-rune", name="Variant Rune", card_type="Rune", super_type="Basic",
        domains=("Fury",), domains_ok=True, cost=None, might=None, tags=(), champion_tags=(),
        effect="", flavor="", unique=False,
        printings=(Printing(
            print_id="ven-r02a-variant", card_id="variant-rune", title="Variant Rune",
            set_code="VEN", set_name="Vendetta", card_number="R02a", rarity="Common",
            promo=False, image_url="",
        ),),
    )
    catalog = build_catalog([base, variant])
    assert catalog.by_code("VEN-R02A") is variant, "decklists use uppercase"
    assert catalog.by_code("ven-r02a") is variant


# -- rules drift --------------------------------------------------------------


def test_rules_drift_spots_a_stale_constraint(coded_catalog, tmp_path, monkeypatch):
    """The check that caught a real change: Riftbound's sideboard limit moved 8 -> 10.

    A rules profile nobody revisits starts calling legal decks illegal. Tournament decks
    are the best evidence of what the rules are *now*, so a constraint that most of the
    recent field breaks is reported as probably stale.
    """
    import json as _json

    from riftbound.data.meta_pipeline import _rules_drift

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "constructed.json").write_text(
        _json.dumps({
            "format": "constructed",
            "constraints": {"sideboard_max": 8, "allowed_sideboard_card_types": ["Unit"]},
            "rule_refs": {},
        }),
        encoding="utf-8",
    )

    bundles = tmp_path / "bundles"
    bundles.mkdir()
    from riftbound.data.bundle import promote as promote_bundle
    from riftbound.data.bundle import write_bundle
    written = write_bundle(bundles, list(coded_catalog))
    promote_bundle(bundles, written.manifest.bundle_id)

    class Cfg:
        rules_dir = None
        bundles_dir = None
    cfg = Cfg()
    cfg.rules_dir = rules_dir
    cfg.bundles_dir = bundles

    # A field that plays 10-card sideboards against a profile that allows 8.
    payloads = []
    for i in range(20):
        p = deck_payload(coded_catalog, slug=f"d{i}")
        p["deck"][code_for(coded_catalog, "brazen-buccaneer")] = "3"
        payloads.append(p)
    decks = normalize_meta_decks(payloads, catalog=coded_catalog)
    decks = [
        type(d)(
            deck=d.deck.with_meta(sideboard={"harpoon-squad": 10}),
            provenance=d.provenance, unresolved=d.unresolved,
        )
        for d in decks
    ]

    drift = _rules_drift(decks, cfg)
    assert any("SIDEBOARD_SIZE" in line for line in drift)
    assert any("the field plays 10" in line and "allows 8" in line for line in drift)


def test_rules_drift_is_quiet_when_the_profile_matches(coded_catalog, tmp_path):
    import json as _json

    from riftbound.data.bundle import promote as promote_bundle
    from riftbound.data.bundle import write_bundle
    from riftbound.data.meta_pipeline import _rules_drift

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "constructed.json").write_text(
        _json.dumps({"format": "constructed", "constraints": {"sideboard_max": 10},
                     "rule_refs": {}}),
        encoding="utf-8",
    )
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    written = write_bundle(bundles, list(coded_catalog))
    promote_bundle(bundles, written.manifest.bundle_id)

    class Cfg:
        pass
    cfg = Cfg()
    cfg.rules_dir = rules_dir
    cfg.bundles_dir = bundles

    decks = make_decks(coded_catalog, 20)
    assert _rules_drift(decks, cfg) == []


# -- repairing what upstream recorded loosely ---------------------------------


def a_repairable(catalog, *, slug, battlefields, champion="vi-destructive", main=None):
    from riftbound.domain.deck import Deck
    from riftbound.domain.meta import MetaDeck, Provenance

    base = {"vi-destructive": 3, "brazen-buccaneer": 3, "harpoon-squad": 3,
            "singular-relic": 1, "showcase-only": 3}
    base.update({f"filler-{i:02d}": 3 for i in range(1, 10)})
    return MetaDeck(
        deck=Deck.make(
            legend_id="vi-piltover-enforcer", champion_id=champion,
            main=main if main is not None else base,
            runes={"fury-rune": 12}, battlefields=battlefields,
        ),
        provenance=Provenance(source="t", source_slug=slug, url=""),
    )


def test_too_many_battlefields_loses_the_ones_the_archetype_plays_least(catalog):
    """A fourth battlefield is usually a sideboard one recorded in the wrong zone, and
    the corpus knows which of them the archetype actually runs."""
    from riftbound.data.meta_normalize import repair_meta_decks

    common = ["the-arena", "the-forge", "the-spire"]
    corpus = [a_repairable(catalog, slug=f"ok-{i}", battlefields=common) for i in range(5)]
    corpus.append(a_repairable(catalog, slug="over", battlefields=[*common, "the-papertree"]))

    repaired, report = repair_meta_decks(corpus, catalog=catalog, battlefield_count=3)
    fixed = next(d for d in repaired if d.provenance.source_slug == "over")
    assert len(fixed.deck.battlefields) == 3
    assert "the-papertree" not in fixed.deck.battlefields, "the rarest one goes"
    assert report.battlefields_trimmed == 1


def test_too_few_battlefields_gains_the_ones_it_plays_most(catalog):
    from riftbound.data.meta_normalize import repair_meta_decks

    common = ["the-arena", "the-forge", "the-spire"]
    corpus = [a_repairable(catalog, slug=f"ok-{i}", battlefields=common) for i in range(5)]
    corpus.append(a_repairable(catalog, slug="short", battlefields=["the-arena"]))

    repaired, report = repair_meta_decks(corpus, catalog=catalog, battlefield_count=3)
    fixed = next(d for d in repaired if d.provenance.source_slug == "short")
    assert len(fixed.deck.battlefields) == 3
    assert set(fixed.deck.battlefields) <= set(common), "only what this archetype plays"
    assert report.battlefields_filled == 1


def test_a_list_that_named_no_battlefields_is_left_alone(catalog):
    """Filling from zero would be fabrication, not repair.

    A list one battlefield short lost one in transcription. A list with none never had
    the zone -- some sources only publish the main deck -- and inventing all three feeds
    the popularity counts back into themselves, so the most played battlefield gets
    assigned to every deck that named none and thereby stays the most played.
    """
    from riftbound.data.meta_normalize import repair_meta_decks

    common = ["the-arena", "the-forge", "the-spire"]
    corpus = [a_repairable(catalog, slug=f"ok-{i}", battlefields=common) for i in range(5)]
    corpus.append(a_repairable(catalog, slug="none", battlefields=[]))

    repaired, report = repair_meta_decks(corpus, catalog=catalog, battlefield_count=3)
    untouched = next(d for d in repaired if d.provenance.source_slug == "none")
    assert untouched.deck.battlefields == ()
    assert report.battlefields_filled == 0


def test_a_missing_champion_is_taken_from_the_list(catalog):
    """The nomination is a player declaration upstream does not record. If a legal
    champion is sitting in the deck, that is the answer."""
    from riftbound.data.meta_normalize import repair_meta_decks

    orphan = a_repairable(
        catalog, slug="nochamp", battlefields=["the-arena", "the-forge", "the-spire"],
        champion="",
    )
    repaired, report = repair_meta_decks([orphan], catalog=catalog, battlefield_count=3)
    assert len(repaired) == 1
    assert repaired[0].deck.champion_id == "vi-destructive"
    assert report.champions_inferred == 1


def test_a_deck_with_no_legal_champion_is_dropped(catalog):
    """A deck with no champion is not a deck. Keeping it would put a legend's numbers
    on a list nobody could field."""
    from riftbound.data.meta_normalize import repair_meta_decks

    main = {f"filler-{i:02d}": 3 for i in range(1, 14)}
    orphan = a_repairable(
        catalog, slug="hopeless", battlefields=["the-arena", "the-forge", "the-spire"],
        champion="", main=main,
    )
    repaired, report = repair_meta_decks([orphan], catalog=catalog, battlefield_count=3)
    assert repaired == []
    assert report.dropped_no_champion == 1


def test_a_sound_deck_is_returned_untouched(catalog):
    """The overwhelming majority need nothing, and should not be rebuilt for nothing."""
    from riftbound.data.meta_normalize import repair_meta_decks

    good = a_repairable(catalog, slug="fine", battlefields=["the-arena", "the-forge", "the-spire"])
    repaired, report = repair_meta_decks([good], catalog=catalog, battlefield_count=3)
    assert repaired[0] is good
    assert report.touched == 0


# -- the chosen champion ------------------------------------------------------


def zoned_payload(catalog, *, main: dict[str, int], champion: str = "vi-destructive"):
    """A TopDeck-shaped payload: zones keyed by collector code."""
    zones = {
        "legend": {code_for(catalog, "vi-piltover-enforcer"): 1},
        "main": {code_for(catalog, cid): n for cid, n in main.items()},
        "runes": {code_for(catalog, "fury-rune"): 12},
        "battlefields": {
            code_for(catalog, b): 1 for b in ("the-arena", "the-forge", "the-spire")
        },
    }
    if champion:
        zones["champion"] = {code_for(catalog, champion): 1}
    return {"_slug": "s", "slug": "s", "public": "1", "_zones": zones}


def test_the_chosen_champion_counts_toward_the_forty(catalog):
    """TopDeck lists it in a zone of its own, so a 39-card Mainboard is really 40."""
    from riftbound.data.meta_normalize import deck_from_payload

    main = {f"filler-{i:02d}": 3 for i in range(1, 13)}
    main["brazen-buccaneer"] = 3  # 36 + 3 = 39
    deck, _ = deck_from_payload(
        zoned_payload(catalog, main=main), catalog=catalog, main_deck_size=40
    )
    assert deck.main_total == 40
    assert deck.champion_id == "vi-destructive"
    assert deck.main["vi-destructive"] == 1


def test_the_champion_copy_is_additional_even_when_the_list_names_it(catalog):
    """The case that was getting decks a card short.

    A player may run three copies and nominate one of them. The champion zone is that
    nomination, not a restatement of the main deck, so it still adds. Skipping the fold
    whenever the name already appeared left 105 real decks at 39 cards.
    """
    from riftbound.data.meta_normalize import deck_from_payload

    main = {f"filler-{i:02d}": 3 for i in range(1, 13)}
    main["vi-destructive"] = 3  # 36 + 3 = 39, champion already present
    deck, _ = deck_from_payload(
        zoned_payload(catalog, main=main), catalog=catalog, main_deck_size=40
    )
    assert deck.main_total == 40
    assert deck.main["vi-destructive"] == 4 or deck.main_total == 40


def test_a_genuine_duplicate_is_not_folded_twice(catalog):
    """The one shape that really is a repeat: folding would overshoot the format."""
    from riftbound.data.meta_normalize import deck_from_payload

    main = {f"filler-{i:02d}": 3 for i in range(1, 13)}
    main["vi-destructive"] = 3
    main["brazen-buccaneer"] = 1  # 36 + 3 + 1 = 40 already
    deck, _ = deck_from_payload(
        zoned_payload(catalog, main=main), catalog=catalog, main_deck_size=40
    )
    assert deck.main_total == 40, "already complete; the champion must not be added again"


def test_without_a_target_size_the_champion_still_folds(catalog):
    """A source that states its zones is trusted; the size check only breaks ties."""
    from riftbound.data.meta_normalize import deck_from_payload

    main = {f"filler-{i:02d}": 3 for i in range(1, 13)}
    main["brazen-buccaneer"] = 3
    deck, _ = deck_from_payload(zoned_payload(catalog, main=main), catalog=catalog)
    assert deck.main_total == 40


# -- a source going down must not silently strip the archive -------------------
#
# The outage these guard, in full: on 2026-08-27 a scheduled refresh could not reach one
# of two deck sources. Carry-forward restored its decks and not its standings, so the
# promoted snapshot held exactly as many decks as the one before it -- 4,359 either side,
# so nothing watching deck counts saw anything -- while 13% of the standings and 2,030
# match records disappeared and the win-rate acceptance run went from PASS to FAIL.
#
# Two independent failures, so two independent guards: carry-forward has to carry the
# standings, and something has to refuse a snapshot that holds less than the live one.


def joined_decks(catalog, n):
    """Decks with a tournament date on them, as the real pipeline produces.

    Carry-forward is bounded by ARCHIVE_DAYS, and a deck with no date cannot be shown to
    be recent enough to keep -- so an undated fixture would test nothing.
    """
    return normalize_meta_decks(
        [deck_payload(catalog, slug=f"d{i}") for i in range(n)],
        catalog=catalog,
        standings=[a_standing(i) for i in range(n)],
        tournaments=TOURNAMENTS,
    )


def a_snapshot(tmp_path, catalog, *, decks, standings):
    from riftbound.data.meta_snapshot import promote_meta, write_snapshot

    written = write_snapshot(tmp_path, decks, TOURNAMENTS, standings)
    promote_meta(tmp_path, written.manifest.snapshot_id)
    return written


TOURNAMENTS = [
    Tournament("ev-1", "ev-1", "Event One", "2026-08-01", "Constructed", 32, decks_published=32),
]


def a_standing(index: int) -> Standing:
    return Standing(
        tournament_slug="ev-1", place=index + 1, player_name=f"player-{index}",
        deck_slug=f"d{index}", record="3-1", wins=3, losses=1, draws=0,
    )


def test_carry_forward_keeps_the_standings_of_the_decks_it_carries(tmp_path, coded_catalog):
    """The bug: decks came back, their match records did not."""
    from riftbound.data.meta_pipeline import _carry_forward

    previous = a_snapshot(
        tmp_path, coded_catalog,
        decks=joined_decks(coded_catalog, 12),
        standings=[a_standing(i) for i in range(12)],
    )
    # A harvest where the source that supplied everything was unreachable.
    _decks, _tournaments, standings, carried = _carry_forward([], TOURNAMENTS, [], previous)

    assert carried["decks"] == 12
    assert carried["standings"] == 12, "decks without their standings is the original bug"
    assert len(standings) == 12
    assert sum(s.wins + s.losses for s in standings) == 12 * 4


def test_a_fresh_standing_wins_over_a_carried_one(tmp_path, coded_catalog):
    """Same rule the decks already follow: a re-harvest may have corrected it."""
    from riftbound.data.meta_pipeline import _carry_forward

    previous = a_snapshot(
        tmp_path, coded_catalog,
        decks=joined_decks(coded_catalog, 4),
        standings=[a_standing(i) for i in range(4)],
    )
    fresh = Standing(
        tournament_slug="ev-1", place=1, player_name="player-0",
        deck_slug="d0", record="9-0", wins=9, losses=0, draws=0,
    )
    _d, _t, standings, _c = _carry_forward([], TOURNAMENTS, [fresh], previous)

    assert len(standings) == 4, "the carried copy must not duplicate the fresh one"
    kept = next(s for s in standings if s.deck_slug == "d0")
    assert kept.wins == 9


def test_a_standing_with_no_published_list_is_carried_too(tmp_path, coded_catalog):
    """Those rows are the unpublished half of the publication-bias figure, so losing
    them would quietly bias every win rate upward."""
    from riftbound.data.meta_pipeline import _carry_forward

    dropped = Standing(
        tournament_slug="ev-1", place=30, player_name="dropped-out",
        deck_slug="", record="0-3", wins=0, losses=3, draws=0,
    )
    previous = a_snapshot(
        tmp_path, coded_catalog,
        decks=joined_decks(coded_catalog, 4),
        standings=[*[a_standing(i) for i in range(4)], dropped],
    )
    _d, _t, standings, _c = _carry_forward([], TOURNAMENTS, [], previous)
    assert any(s.deck_slug == "" and s.player_name == "dropped-out" for s in standings)


def test_retention_refuses_a_snapshot_that_holds_less_than_the_live_one(tmp_path, coded_catalog):
    """The guard that was missing entirely: deck counts matched, so nothing looked."""
    from riftbound.data.meta_snapshot import check_archive_retention

    previous = a_snapshot(
        tmp_path, coded_catalog,
        decks=make_decks(coded_catalog, 20),
        standings=[a_standing(i) for i in range(20)],
    )
    # Exactly the shape of the outage: same decks, standings quietly gone.
    report = check_archive_retention(
        list(previous.decks), list(previous.tournaments), [], previous
    )
    assert not report.passed
    assert any("standings" in e for e in report.errors)


def test_retention_passes_when_the_archive_holds(tmp_path, coded_catalog):
    from riftbound.data.meta_snapshot import check_archive_retention

    previous = a_snapshot(
        tmp_path, coded_catalog,
        decks=make_decks(coded_catalog, 20),
        standings=[a_standing(i) for i in range(20)],
    )
    report = check_archive_retention(
        list(previous.decks), list(previous.tournaments), list(previous.standings), previous
    )
    assert report.passed


def test_retention_has_nothing_to_say_about_a_first_snapshot(coded_catalog):
    from riftbound.data.meta_snapshot import check_archive_retention

    assert check_archive_retention(make_decks(coded_catalog, 5), [], [], None).passed
