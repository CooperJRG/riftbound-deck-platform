"""What we know about bans, and how sure we are.

Bans are the part of a format that changes most often and that we are least able to
verify. Two sources disagree in both directions:

* the **format profile** (``data/rules/constructed.json``), which is ours, deliberate,
  and cited -- and therefore goes stale the moment an announcement lands;
* the **card data**, which carries the upstream source's own ban flag, and which is
  usually more current but says nothing about *which* format it means.

The rule here is to tell rather than to enforce, because we do not know what the player
is doing with the deck. Somebody building for a casual pod, a local format, or an older
event is not wrong to want a card constructed has banned, and silently removing it --
or silently keeping it -- makes the app the least trustworthy thing in the room. A
notice costs a line of text; a wrong assumption costs a game.

So: the profile is what the builder *enforces* (it has to enforce something, and ours is
the one with rulebook citations behind it), and everything either source flags is
*reported*, tagged with where it came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .cards import Catalog
from .deck import Deck
from .rules import BoundRules

#: This format's own ban list. Enforced by the validator; the deck is illegal.
SOURCE_PROFILE = "profile"

#: The card data's ban flag, where our profile does not agree. Not enforced -- the flag
#: names no format, so it may well be about one the player is not playing.
SOURCE_UPSTREAM = "upstream"


@dataclass(frozen=True)
class BanNotice:
    """One card worth mentioning, and why."""
    card_id: str
    name: str
    source: str
    #: True when this card is actually in the deck we are handing over, as opposed to
    #: one we declined to build with. The advice differs.
    in_deck: bool

    @property
    def enforced(self) -> bool:
        return self.source == SOURCE_PROFILE

    def describe(self, format_name: str) -> str:
        if self.source == SOURCE_PROFILE:
            if self.in_deck:
                return (
                    f"{self.name} is banned in {format_name}. This deck is not legal for "
                    f"a {format_name} event as it stands."
                )
            return (
                f"{self.name} is banned in {format_name}, so it was left out of what we "
                f"built for you. If you are playing another format, you can add it back."
            )
        return (
            f"{self.name} is flagged as banned in the card data, but not by our "
            f"{format_name} profile. The flag does not say which format it means, so we "
            f"have kept the card -- check your event before you play it."
        )


def notices_for(
    deck: Deck | None,
    *,
    rules: BoundRules,
    catalog: Catalog,
    considered: Iterable[str] = (),
) -> tuple[BanNotice, ...]:
    """Ban notices for a deck, plus any excluded card the player should know about.

    ``considered`` is the wider set the wizard looked at -- typically the cards of the
    published deck it is proposing. A tournament list from before a banning still plays
    the card, and a player comparing our version against the original deserves to know
    why a slot is different rather than assuming we made a mistake.
    """
    seen: set[str] = set()
    out: list[BanNotice] = []

    def add(card_id: str, *, in_deck: bool) -> None:
        if card_id in seen:
            return
        card = catalog.get(card_id)
        banned_here = rules.is_banned(card_id)
        flagged = bool(card and card.banned_upstream)
        if not banned_here and not flagged:
            return
        seen.add(card_id)
        out.append(
            BanNotice(
                card_id=card_id,
                name=card.name if card else card_id,
                source=SOURCE_PROFILE if banned_here else SOURCE_UPSTREAM,
                in_deck=in_deck,
            )
        )

    if deck is not None:
        for card_id in deck.all_card_ids():
            add(card_id, in_deck=True)
    for card_id in considered:
        add(card_id, in_deck=False)

    # Enforced first, then cards actually in hand: the ordering a player would choose
    # if they only had time to read one line.
    out.sort(key=lambda n: (not n.enforced, not n.in_deck, n.name))
    return tuple(out)


def drift(catalog: Catalog, rules: BoundRules) -> tuple[str, ...]:
    """Cards the card data bans that our profile does not.

    A standing disagreement between the two, surfaced so it can be resolved deliberately
    rather than discovered by a player at an event.
    """
    return tuple(
        sorted(
            card.card_id
            for card in catalog
            if card.banned_upstream and not rules.is_banned(card.card_id)
        )
    )


def deck_card_ids(counts: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(counts)
