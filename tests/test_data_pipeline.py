"""Normalisation and the promotion gate.

These pin the behaviours that keep the card data trustworthy as it is refreshed --
the subsystem whose absence let v2's data rot.
"""

from __future__ import annotations

import json

import pytest

from riftbound.data.bundle import read_bundle, resolve_current, write_bundle, promote
from riftbound.data.gate import (
    MAX_CARD_LOSS_RATIO,
    check_against_previous,
    check_sources,
    check_structure,
    run_gate,
)
from riftbound.data.normalize import (
    build_tag_vocabulary,
    normalize,
    set_code_for,
    unpack_tags,
)
from riftbound.data.sources.base import RawCard, FetchResult
from riftbound.data.sources.json_export import JsonExportSource
from riftbound.data.bundle import SourceHealth


def raw(title, slug="", **kw):
    return RawCard(source="test", title=title, slug=slug or title.lower().replace(" ", "-"), **kw)


# -- normalisation ------------------------------------------------------------


def test_printings_of_one_card_merge_into_one_card():
    cards = normalize([
        raw("Caitlyn - Patrolling", "ogn-068-caitlyn-patrolling", card_type="Unit"),
        raw("Caitlyn - Patrolling (Chinese Arcane Box Set Promo)", "arc-002-caitlyn-patrolling",
            card_type="Unit", promo=True),
    ])
    assert len(cards) == 1
    assert cards[0].card_id == "caitlyn-patrolling"
    assert len(cards[0].printings) == 2


def test_merge_recovers_symbol_markup_lost_on_a_promo_printing():
    """61 real cards would lose their ability symbols to a single-row pick."""
    cards = normalize([
        raw("Heimerdinger - Inventor", "arc-003", promo=True,
            effect="I have all  abilities of all friendly legends."),
        raw("Heimerdinger - Inventor", "ogn-111",
            effect="I have all :rb_exhaust: abilities of all friendly legends."),
    ])
    assert ":rb_exhaust:" in cards[0].effect


def test_merge_recovers_fields_present_on_only_one_printing():
    """Real case: viktor-leader's superType is null on the promo listing."""
    cards = normalize([
        raw("Viktor - Leader", "ogn-246", card_type="Unit", super_type="Champion", cost=4),
        raw("Viktor - Leader", "ogn-246-p", card_type="Unit", super_type="", cost=None, promo=True),
    ])
    assert cards[0].super_type == "Champion"
    assert cards[0].cost == 4


def test_comma_and_dash_spellings_merge():
    cards = normalize([
        raw("Blitzcrank - Impassive", "ogn-067", card_type="Unit"),
        raw("Blitzcrank, Impassive (Promo)", "ogn-067-p", card_type="Unit", promo=True),
    ])
    assert len(cards) == 1


def test_rows_without_a_usable_title_are_reported_not_dropped_silently():
    warnings: list[str] = []
    cards = normalize([raw(""), raw("Real Card", card_type="Unit")], warnings=warnings)
    assert len(cards) == 1
    assert any("unusable title" in w for w in warnings)


def test_domains_are_unpacked_from_the_concatenated_colour_field():
    cards = normalize([raw("Two Domain Card", card_type="Unit", color="FuryChaos")])
    assert cards[0].domains == ("Chaos", "Fury")
    assert cards[0].domains_ok


def test_missing_colour_marks_domains_unparsed_rather_than_empty():
    cards = normalize([raw("No Colour", card_type="Unit", color="")])
    assert cards[0].domains_ok is False


def test_colorless_is_a_parsed_empty_domain_set():
    cards = normalize([raw("Artifact", card_type="Gear", color="Colorless")])
    assert cards[0].domains == () and cards[0].domains_ok is True


@pytest.mark.parametrize(
    "slug,set_name,expected",
    [
        ("ogn-068-caitlyn", "OGN - Origins", "OGN"),
        ("ogn-247-kaisa", "Origins", "OGN"),          # upstream drops the code
        ("sfd-207-dais", "Spiritforged", "SFD"),
        ("unl-r04b-body-rune", "UNL - Unleashed", "UNL"),
        ("arc-002-caitlyn", "ARC - Arcane Box Set", "ARC"),
    ],
)
def test_set_code_prefers_the_slug_prefix(slug, set_name, expected):
    assert set_code_for(slug, set_name) == expected


def test_champion_tags_are_derived_from_champion_cards():
    cards = normalize([
        raw("Caitlyn - Patrolling", card_type="Unit", super_type="Champion",
            tags=("Caitlyn", "Piltover")),
        raw("Some Ally", card_type="Unit", tags=("Caitlyn", "Piltover")),
    ])
    ally = next(c for c in cards if c.card_id == "some-ally")
    assert ally.champion_tags == ("Caitlyn",), "Piltover is a region, not a champion"


def test_packed_tags_are_unpacked_using_the_whole_catalogue():
    """'PirateBilgewater' appears on cards that carry no split form of their own."""
    vocabulary = build_tag_vocabulary(["Pirate", "Bilgewater", "PirateBilgewater"])
    assert unpack_tags(["PirateBilgewater"], vocabulary) == ("Pirate", "Bilgewater")


def test_unpacking_leaves_genuine_tags_alone():
    vocabulary = build_tag_vocabulary(["Pirate", "Bilgewater", "Noxus"])
    assert unpack_tags(["Noxus"], vocabulary) == ("Noxus",)


def test_unique_is_inferred_from_rules_text():
    cards = normalize([
        raw("Singular", card_type="Gear",
            effect="Your deck can have only 1 card with this name.")
    ])
    assert cards[0].unique is True


# -- the gate -----------------------------------------------------------------


def make_cards(n: int, prefix: str = "card"):
    return normalize([raw(f"{prefix} {i}", card_type="Unit", color="Fury") for i in range(n)])


def test_gate_rejects_a_bundle_that_loses_most_of_its_cards(tmp_path):
    """The check v2 needed: a scraper returning an error page must not become truth."""
    previous = write_bundle(tmp_path, make_cards(500))
    report = check_against_previous(make_cards(50), previous)
    assert not report.passed
    assert "disappeared" in report.errors[0]


def test_gate_allows_a_small_erratum_removal(tmp_path):
    previous = write_bundle(tmp_path, make_cards(500))
    shrunk = make_cards(500)[:-2]  # lose 2 of 500 = 0.4%
    report = check_against_previous(shrunk, previous)
    assert report.passed
    assert MAX_CARD_LOSS_RATIO > 0.004


def test_gate_reports_new_cards_as_a_warning(tmp_path):
    previous = write_bundle(tmp_path, make_cards(300))
    report = check_against_previous(make_cards(320), previous)
    assert report.passed
    assert any("new card" in w for w in report.warnings)


def test_first_bundle_must_clear_a_plausibility_floor():
    assert not check_against_previous(make_cards(5), None).passed
    assert check_against_previous(make_cards(400), None).passed


def test_gate_rejects_an_empty_bundle():
    report = check_structure([])
    assert not report.passed


def test_gate_rejects_a_bundle_where_every_source_failed():
    report = check_sources([SourceHealth("a", False, 0, 0, error="HTTP 503")])
    assert not report.passed
    assert "every source failed" in report.errors[0]


def test_gate_passes_when_one_source_survives():
    report = check_sources([
        SourceHealth("a", False, 0, 0, error="HTTP 503"),
        SourceHealth("b", True, 900, 900),
    ])
    assert report.passed
    assert any("failed" in w for w in report.warnings)


def test_gate_warns_when_a_source_starts_dropping_rows():
    report = check_sources([SourceHealth("a", True, fetched=900, accepted=100)])
    assert report.passed
    assert any("shape may have changed" in w for w in report.warnings)


def test_gate_catches_duplicate_print_ids():
    cards = make_cards(3)
    duped = list(cards) + [cards[0].__class__(**{**cards[0].__dict__, "card_id": "other-id"})]
    report = check_structure(duped)
    assert not report.passed


# -- bundles ------------------------------------------------------------------


def test_bundle_roundtrips(tmp_path):
    written = write_bundle(tmp_path, make_cards(10), notes="hello")
    loaded = read_bundle(written.path)
    assert loaded.manifest.card_count == 10
    assert loaded.manifest.notes == "hello"
    assert len(loaded.catalog) == 10


def test_bundle_detects_tampering(tmp_path):
    written = write_bundle(tmp_path, make_cards(10))
    payload = json.loads((written.path / "cards.json").read_text(encoding="utf-8"))
    payload[0]["name"] = "Edited By Hand"
    (written.path / "cards.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity check"):
        read_bundle(written.path)


def test_building_a_bundle_does_not_promote_it(tmp_path):
    write_bundle(tmp_path, make_cards(400))
    assert resolve_current(tmp_path) is None, "promotion must be a deliberate second step"


def test_promotion_points_current_at_the_bundle(tmp_path):
    written = write_bundle(tmp_path, make_cards(400))
    promote(tmp_path, written.manifest.bundle_id)
    assert resolve_current(tmp_path).name == written.manifest.bundle_id


def test_run_gate_combines_every_check(tmp_path):
    previous = write_bundle(tmp_path, make_cards(500))
    report = run_gate(
        make_cards(10),
        sources=[SourceHealth("a", True, 10, 10)],
        previous=previous,
    )
    assert not report.passed


# -- source adapters ----------------------------------------------------------


def test_a_missing_source_file_fails_without_raising(tmp_path):
    result = JsonExportSource(tmp_path / "nope.json", name="missing").fetch()
    assert isinstance(result, FetchResult)
    assert result.ok is False
    assert "No card export" in result.error


def test_a_malformed_source_file_fails_without_raising(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"not": "an array"}', encoding="utf-8")
    result = JsonExportSource(path).fetch()
    assert result.ok is False
    assert "must contain a JSON array" in result.error
