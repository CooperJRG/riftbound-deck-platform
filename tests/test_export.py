"""The exchange text format.

The format is not ours -- it is what other Riftbound tools read -- so the headline test
is byte-equality against a real exported list rather than a set of assertions about
shape. If a section moves, two card entries rejoin a line or a name loses its comma,
this fails on the diff.
"""

from __future__ import annotations

from riftbound.domain.cards import build_catalog
from riftbound.domain.deck import Deck
from riftbound.domain.export import export_deck, export_filename, export_name

from tests.conftest import make_card

# A published Lillia list, as another tool wrote it.
LILLIA = """\
Legend:
1 Lillia, Bashful Bloom
Champion:
1 Lillia, Fae Fawn
MainDeck:
3 Brutalizer
2 Charm
2 Consult the Past
2 Defy
3 Discipline
2 Eclipse
2 Heart of Dark Ice
2 Lilting Lullaby
3 Scuttle Crab
1 Singularity
2 Sprite Burst
3 Sprite Fountain
3 Sprite Mother
2 Sprite Queen
3 Stupefy
2 Thousand-Tailed Watcher
1 Unchecked Power
1 Vilemaw
Battlefields:
1 Black Flame Altar
1 Seat of Power
1 Targon's Peak
Runes:
6 Calm Rune
6 Mind Rune
Sideboard:
2 Back Off
1 Defy
2 Disarming Rake
1 Lilting Lullaby
2 Pickpocket
"""

MAIN = {
    "Brutalizer": 3,
    "Charm": 2,
    "Consult the Past": 2,
    "Defy": 2,
    "Discipline": 3,
    "Eclipse": 2,
    "Heart of Dark Ice": 2,
    "Lilting Lullaby": 2,
    "Scuttle Crab": 3,
    "Singularity": 1,
    "Sprite Burst": 2,
    "Sprite Fountain": 3,
    "Sprite Mother": 3,
    "Sprite Queen": 2,
    "Stupefy": 3,
    "Thousand-Tailed Watcher": 2,
    "Unchecked Power": 1,
    "Vilemaw": 1,
}
SIDEBOARD = {
    "Back Off": 2,
    "Defy": 1,
    "Disarming Rake": 2,
    "Lilting Lullaby": 1,
    "Pickpocket": 2,
}
BATTLEFIELDS = ("Black Flame Altar", "Seat of Power", "Targon's Peak")


def slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace(",", "").replace("'", "")


def lillia_catalog():
    names = [
        "Lillia - Bashful Bloom",
        "Lillia - Fae Fawn",
        *MAIN,
        *SIDEBOARD,
        *BATTLEFIELDS,
        "Calm Rune",
        "Mind Rune",
    ]
    return build_catalog([make_card(slug(name), name) for name in dict.fromkeys(names)])


def lillia_deck() -> Deck:
    main = {slug(name): copies for name, copies in MAIN.items()}
    main[slug("Lillia - Fae Fawn")] = 1
    return Deck.make(
        name="Lillia",
        legend_id=slug("Lillia - Bashful Bloom"),
        champion_id=slug("Lillia - Fae Fawn"),
        main=main,
        runes={slug("Calm Rune"): 6, slug("Mind Rune"): 6},
        battlefields=[slug(name) for name in BATTLEFIELDS],
        sideboard={slug(name): copies for name, copies in SIDEBOARD.items()},
    )


def test_exports_a_published_list_verbatim():
    """The whole point: what we write is what the ecosystem reads."""
    catalog = lillia_catalog()
    assert export_deck(lillia_deck(), catalog) == LILLIA


def test_deck_and_champion_sections_still_total_forty():
    """Lifting the champion out must not lose a card."""
    catalog = lillia_catalog()
    text = export_deck(lillia_deck(), catalog)
    counted = 0
    section = ""
    for line in text.splitlines():
        if line.endswith(":"):
            section = line[:-1]
        elif section in ("Champion", "MainDeck"):
            counted += int(line.split(" ", 1)[0])
    assert counted == 40


def test_extra_copies_of_the_champion_stay_in_the_main_deck():
    """A deck running three of its champion nominates one and plays two."""
    catalog = lillia_catalog()
    deck = lillia_deck()
    main = dict(deck.main)
    main[slug("Lillia - Fae Fawn")] = 3
    text = export_deck(Deck.make(**{**deck.__dict__, "main": main}), catalog)
    assert "Champion:\n1 Lillia, Fae Fawn" in text
    main_block = text.split("MainDeck:\n", 1)[1].split("\nBattlefields:", 1)[0]
    assert "2 Lillia, Fae Fawn" in main_block.splitlines()


def test_empty_sections_are_omitted():
    """Half a deck exports as half a deck, not as empty headers."""
    catalog = lillia_catalog()
    deck = Deck.make(
        legend_id=slug("Lillia - Bashful Bloom"), main={slug("Brutalizer"): 3}
    )
    text = export_deck(deck, catalog)
    assert "Runes:" not in text
    assert "Sideboard:" not in text
    assert "Champion:" not in text
    assert text == "Legend:\n1 Lillia, Bashful Bloom\nMainDeck:\n3 Brutalizer\n"


def test_cards_missing_from_the_catalogue_are_dropped():
    """Better a short list than a raw id no importer can resolve."""
    catalog = lillia_catalog()
    deck = Deck.make(main={slug("Brutalizer"): 3, "card-that-left": 2})
    assert export_deck(deck, catalog) == "MainDeck:\n3 Brutalizer\n"


def test_only_the_first_separator_becomes_a_comma():
    """A subtitle with its own dash keeps it."""
    assert export_name("Lillia - Bashful Bloom") == "Lillia, Bashful Bloom"
    assert export_name("Thousand-Tailed Watcher") == "Thousand-Tailed Watcher"
    assert export_name("A - B - C") == "A, B - C"


def test_filename_is_safe_on_windows():
    assert export_filename(Deck.make(name='Lillia: "the best"/v2')) == "Lillia-the-best-v2.txt"
    # Deck.make already refuses a blank name; the fallback covers a Deck built
    # directly, e.g. one deserialised from a row written before that guard existed.
    assert export_filename(Deck.make(name="   ")) == "Untitled-Deck.txt"
    assert export_filename(Deck(name="!!!")) == "deck.txt"
