"""Writing a deck out as text.

The requested exchange shape is one section header followed by one ``<count> <name>``
entry per line. It is what a player pastes into a tournament submission form or a
friend's chat window, so the section names, their order and the punctuation in card
names all have to come out exactly as specified.

Names, not ids. This is the one place in the codebase that deliberately serialises
display titles, because the receiving end is a human or a tool that indexes by title.
Everywhere else stores ``card_id`` for the reason the module docstring in ``deck.py``
gives.
"""

from __future__ import annotations

from collections.abc import Mapping

from .cards import Catalog
from .deck import Deck

#: Section headers, in the order they are written.
LEGEND = "Legend"
CHAMPION = "Champion"
MAIN_DECK = "MainDeck"
BATTLEFIELDS = "Battlefields"
RUNES = "Runes"
SIDEBOARD = "Sideboard"


def export_name(name: str) -> str:
    """A card's name as the exchange format writes it.

    Our catalogue titles a two-part name with a spaced dash -- ``Lillia - Bashful
    Bloom`` -- and the exchange format uses a comma. The dash is the upstream data's
    convention, not a display choice of ours, so the conversion belongs here at the
    boundary rather than in the card model where it would follow the name everywhere.

    Only the first separator is converted. No card in the catalogue has two, but a
    subtitle containing its own dash would otherwise be mangled.
    """
    return name.replace(" - ", ", ", 1)


def _lines(counts: Mapping[str, int], catalog: Catalog) -> list[str]:
    """``<count> <name>`` for each card, alphabetically by name.

    Sorted by the exported name rather than the catalogue's, so the ordering matches
    what the reader sees. Unknown ids are dropped: a deck referencing a card that has
    left the catalogue should export as the legal remainder of itself rather than
    printing a raw id that no importer can resolve.
    """
    rows: list[tuple[str, int]] = []
    for card_id, copies in counts.items():
        card = catalog.get(card_id)
        if card is None or copies <= 0:
            continue
        rows.append((export_name(card.name), copies))
    rows.sort(key=lambda row: row[0])
    return [f"{copies} {name}" for name, copies in rows]


def export_deck(deck: Deck, catalog: Catalog) -> str:
    """The deck as exchange-format text.

    The nominated champion is written under its own header and one copy is taken off
    the main deck, which is where the rules say it lives. A deck running three of its
    champion exports as one under ``Champion`` and two under ``MainDeck``; the two
    sections still total forty, and re-importing puts the copies back together.

    Empty sections are left out. A deck half way through being built has no runes yet,
    and a bare header over nothing reads like a card failed to export.
    """
    blocks: list[tuple[str, list[str]]] = []

    legend = catalog.get(deck.legend_id)
    if legend is not None:
        blocks.append((LEGEND, [f"1 {export_name(legend.name)}"]))

    main = dict(deck.main)
    champion = catalog.get(deck.champion_id)
    if champion is not None:
        blocks.append((CHAMPION, [f"1 {export_name(champion.name)}"]))
        remaining = main.get(champion.card_id, 0) - 1
        if remaining > 0:
            main[champion.card_id] = remaining
        else:
            main.pop(champion.card_id, None)

    blocks.append((MAIN_DECK, _lines(main, catalog)))
    blocks.append((BATTLEFIELDS, _lines(dict.fromkeys(deck.battlefields, 1), catalog)))
    blocks.append((RUNES, _lines(deck.runes, catalog)))
    blocks.append((SIDEBOARD, _lines(deck.sideboard, catalog)))

    out: list[str] = []
    for header, lines in blocks:
        if not lines:
            continue
        out.append(f"{header}:")
        out.extend(lines)
    return "\n".join(out) + "\n" if out else ""


def export_filename(deck: Deck) -> str:
    """A filename for the exported deck, safe on every platform we run on.

    Windows rejects ``<>:"/\\|?*`` outright and every OS dislikes a trailing dot, so
    anything outside letters, digits, dash and underscore becomes a dash. Runs collapse:
    ``Lillia: "the best"`` has four punctuation marks in a row in the middle of it and
    ``Lillia----the-best`` is not a filename anybody wants to look at.
    """
    stem = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in deck.name.strip()
    )
    while "--" in stem:
        stem = stem.replace("--", "-")
    return f"{stem.strip('-') or 'deck'}.txt"
