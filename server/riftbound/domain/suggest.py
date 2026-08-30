"""What to add next, while a deck is being built by hand.

The builder is a search box and a deck. That is fine once you know the format and
miserable before then: a new player faces 948 cards and no idea which forty go together.
These are the same statistics the wizard already runs on -- play rate, pairing affinity,
domain identity, the power floor -- pointed at a half-built deck instead of a finished
one, so the manual path gets the benefit without being taken over by it.

Nothing here decides anything. Every function returns an ordered shortlist with the
reason attached, and the player picks. A suggestion that cannot say why it is on the
list is a slot machine.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .cards import Card, Catalog
from .deck import Deck
from .deck_builder import legal_main_pool, legal_zone_pool, power_floor
from .legend_index import LegendProfile
from .meta import MetaDeck, shares_champion_identity
from .rules import BoundRules

#: How much of a champion's standing comes from how often the field picks it, against
#: how often it wins. Presence is the steadier number -- every deck contributes to it,
#: while a win rate needs 200 decisive matches before it may be published at all, and
#: only 18 champions in the whole archive clear that bar. Weighting presence higher
#: keeps the ranking stable for the many champions that will never have a rate.
W_PRESENCE = 0.65
W_WIN_RATE = 0.35

#: Suggestions offered at once. Enough to be a choice, few enough to read without
#: having to decide to read them.
SHORTLIST = 5

#: Copies in the main deck before a card's missing partner counts against it.
#:
#: Early on every card's partners are absent, because almost everything is absent -- a
#: deck of three cards would discount the entire pool and rank on the noise left over.
#: Measured on a one-card deck it put a 95%-affinity staple third behind a 32% one. Half
#: a deck is enough for absence to mean a choice rather than an empty list.
SUPPORT_AFTER = 20


@dataclass(frozen=True)
class ChampionOption:
    """One champion this legend could nominate, and how the field has fared with it."""

    card_id: str
    name: str
    image_url: str
    decks: int
    share: float
    win_rate: float
    win_rate_shown: bool
    score: float

    def describe(self) -> str:
        played = f"{self.share:.0%} of this legend's lists"
        if self.win_rate_shown:
            return f"{played} - {self.win_rate:.0%} won"
        return f"{played} - not enough matches to rate"


@dataclass(frozen=True)
class Suggestion:
    """One card worth considering, and the reason it is on the list."""

    card_id: str
    name: str
    image_url: str
    copies: int
    reason: str
    score: float


def champion_options(
    legend_id: str,
    decks: Iterable[MetaDeck],
    catalog: Catalog,
    win_rates: Mapping[str, tuple[float, bool]] | None = None,
) -> list[ChampionOption]:
    """The champions this legend can nominate, best first.

    Scored on presence and win rate together, normalised so the strongest option reads
    100 and the rest sit proportionally below it. Min-max would be harsher and less
    honest: with a median of two champions per legend it prints 100 and 0 for a pair
    that might be a percentage point apart.

    A champion with no publishable win rate is scored against the group's average rate
    rather than against zero. Missing evidence is not evidence of losing, and only 18
    champions in the archive have enough decisive matches to be rated at all.
    """
    legend = catalog.get(legend_id)
    counts: dict[str, int] = {}
    for meta_deck in decks:
        if meta_deck.deck.legend_id != legend_id:
            continue
        champion_id = meta_deck.deck.champion_id
        if not champion_id:
            continue
        if not shares_champion_identity(catalog.get(champion_id), legend):
            continue
        counts[champion_id] = counts.get(champion_id, 0) + 1
    if not counts:
        return []

    total = sum(counts.values())
    rates = win_rates or {}
    rated = [rates[c][0] for c in counts if c in rates and rates[c][1]]
    neutral = sum(rated) / len(rated) if rated else 0.5

    rows: list[tuple[str, int, float, float, bool]] = []
    for champion_id, deck_count in counts.items():
        rate, shown = rates.get(champion_id, (neutral, False))
        if not shown:
            rate = neutral
        rows.append((champion_id, deck_count, deck_count / total, rate, shown))

    best_rate = max((row[3] for row in rows), default=1.0) or 1.0
    raw = {
        row[0]: W_PRESENCE * row[2] + W_WIN_RATE * (row[3] / best_rate) for row in rows
    }
    top = max(raw.values()) or 1.0

    out = [
        ChampionOption(
            card_id=champion_id,
            name=getattr(catalog.get(champion_id), "name", champion_id),
            image_url=getattr(catalog.get(champion_id), "image_url", ""),
            decks=deck_count,
            share=share,
            win_rate=rate,
            win_rate_shown=shown,
            score=100.0 * raw[champion_id] / top,
        )
        for champion_id, deck_count, share, rate, shown in rows
    ]
    out.sort(key=lambda option: (-option.score, option.name))
    return out


def _room_for(deck: Deck, card: Card, rules: BoundRules) -> int:
    """Copies of this card the deck could still take, under the format's limit."""
    limit = rules.int_constraint("main_copy_limit", 3)
    if card.unlimited_copies:
        limit = 99
    held = deck.main.get(card.card_id, 0) + deck.sideboard.get(card.card_id, 0)
    return max(0, limit - held)


def main_deck_suggestions(
    deck: Deck,
    profile: LegendProfile,
    catalog: Catalog,
    rules: BoundRules,
    limit: int = SHORTLIST,
) -> list[Suggestion]:
    """Cards the field plays alongside what this deck already has.

    Ranked by how often the field pairs a card with the cards already chosen, weighted
    by whether this deck can support it -- there is no point offering the second half of
    a combo whose first half is absent and cannot arrive.

    Legality is the pool's job. Domain identity, bans and card type are all settled by
    ``legal_main_pool`` before anything is ranked, so a suggestion is never something
    the deck is not allowed to contain.
    """
    legend = catalog.get(deck.legend_id)
    if legend is None:
        return []
    context = list(deck.main)
    present = set(context)
    settled = sum(deck.main.values()) >= SUPPORT_AFTER

    scored: list[tuple[float, Card, str]] = []
    for card in legal_main_pool(legend, catalog=catalog, rules=rules):
        if _room_for(deck, card, rules) <= 0:
            continue
        affinity = profile.affinity(card.card_id, context) if context else 0.0
        play_rate = profile.play_rate.get(card.card_id, 0.0)
        # Affinity leads once there is a deck to pair against. Before that the only
        # signal available is how much the field plays the card at all.
        blended = (0.7 * affinity + 0.3 * play_rate) if context else play_rate
        support = profile.support(card.card_id, present) if settled else 1.0
        value = blended * support
        if value <= 0:
            continue
        reason = (
            f"played alongside this deck {affinity:.0%} of the time"
            if context and affinity > 0
            else f"in {play_rate:.0%} of lists for this legend"
        )
        scored.append((value, card, reason))

    scored.sort(key=lambda row: (-row[0], row[1].name))
    return [
        Suggestion(
            card_id=card.card_id,
            name=card.name,
            image_url=card.image_url,
            copies=min(
                _room_for(deck, card, rules),
                max(1, int(profile.copies.get(card.card_id, 1))),
            ),
            reason=reason,
            score=value,
        )
        for value, card, reason in scored[:limit]
    ]


def battlefield_suggestions(
    deck: Deck,
    profile: LegendProfile,
    catalog: Catalog,
    rules: BoundRules,
    limit: int = SHORTLIST,
) -> list[Suggestion]:
    """Battlefields the field plays with this legend and these cards.

    The same pairing signal as the main deck, over the battlefield pool. The format
    wants exactly three and they must differ, so anything already chosen is dropped
    rather than offered again further down the list.
    """
    legend = catalog.get(deck.legend_id)
    if legend is None:
        return []
    chosen = set(deck.battlefields)
    context = list(deck.main)

    scored: list[tuple[float, Card, str]] = []
    for card in legal_zone_pool(
        legend,
        rules.str_constraint("battlefield_card_type", "Battlefield"),
        catalog=catalog,
        rules=rules,
    ):
        if card.card_id in chosen:
            continue
        affinity = profile.affinity(card.card_id, context) if context else 0.0
        play_rate = profile.play_rate.get(card.card_id, 0.0)
        value = (0.6 * affinity + 0.4 * play_rate) if context else play_rate
        if value <= 0:
            continue
        reason = (
            f"played with this deck {affinity:.0%} of the time"
            if context and affinity > 0
            else f"in {play_rate:.0%} of lists for this legend"
        )
        scored.append((value, card, reason))

    scored.sort(key=lambda row: (-row[0], row[1].name))
    return [
        Suggestion(
            card_id=card.card_id,
            name=card.name,
            image_url=card.image_url,
            copies=1,
            reason=reason,
            score=value,
        )
        for value, card, reason in scored[:limit]
    ]


def sideboard_suggestions(
    deck: Deck,
    decks: Iterable[MetaDeck],
    scores: Mapping[str, float],
    catalog: Catalog,
    rules: BoundRules,
    limit: int = SHORTLIST,
) -> list[Suggestion]:
    """Cards comparable tournament lists actually keep in reserve.

    Sideboards are not part of the legend index. Deliberately so: folding cards that
    appear only after game one into main-deck affinity would teach the builder that a
    narrow answer belongs in every opening forty. This ranking therefore reads the
    published sideboards directly, first matching the chosen champion when one exists,
    then weighting each list by the same quality score used elsewhere in the meta.

    Lists whose sideboard is missing are left out of the denominator. Missing data is
    not an empty sideboard, and treating it as one would suppress every real signal.
    """
    legend = catalog.get(deck.legend_id)
    if legend is None:
        return []

    comparable = [
        row for row in decks
        if row.deck.legend_id == deck.legend_id
        and row.deck.sideboard
        and (not deck.champion_id or row.deck.champion_id == deck.champion_id)
    ]
    # Some sources know the legend but not the chosen champion. A legend-level answer
    # is still useful, but only as a fallback when the exact pairing has no evidence.
    if not comparable and deck.champion_id:
        comparable = [
            row for row in decks
            if row.deck.legend_id == deck.legend_id and row.deck.sideboard
        ]
    if not comparable:
        return []

    legal = {
        card.card_id: card
        for card in legal_main_pool(legend, catalog=catalog, rules=rules)
    }
    context = set(deck.main)
    weighted_presence: dict[str, float] = {}
    weighted_copies: dict[str, float] = {}
    appearances: dict[str, int] = {}
    total_weight = 0.0

    for row in comparable:
        known_score = scores.get(row.deck_id)
        quality = max(1e-6, known_score if known_score is not None else 1.0)
        similarity = (
            len(context & set(row.deck.main)) / len(context) if context else 0.0
        )
        weight = quality * (0.7 + 0.3 * similarity)
        total_weight += weight
        for card_id, copies in row.deck.sideboard.items():
            if card_id not in legal or _room_for(deck, legal[card_id], rules) <= 0:
                continue
            weighted_presence[card_id] = weighted_presence.get(card_id, 0.0) + weight
            weighted_copies[card_id] = (
                weighted_copies.get(card_id, 0.0) + weight * copies
            )
            appearances[card_id] = appearances.get(card_id, 0) + 1

    if total_weight <= 0:
        return []
    ranked = sorted(
        weighted_presence,
        key=lambda card_id: (
            -weighted_presence[card_id] / total_weight,
            legal[card_id].name,
        ),
    )
    return [
        Suggestion(
            card_id=card_id,
            name=legal[card_id].name,
            image_url=legal[card_id].image_url,
            copies=min(
                _room_for(deck, legal[card_id], rules),
                max(1, round(weighted_copies[card_id] / weighted_presence[card_id])),
            ),
            reason=(
                f"in {appearances[card_id] / len(comparable):.0%} of comparable "
                "sideboards"
            ),
            score=weighted_presence[card_id] / total_weight,
        )
        for card_id in ranked[:limit]
    ]


def rune_suggestion(deck: Deck, catalog: Catalog, rules: BoundRules) -> dict[str, int]:
    """A rune base this deck can actually be cast from.

    The same two-part answer the automatic builder uses. Every domain gets at least the
    largest power any one of its cards demands -- power is the domain-specific half of a
    cost, so a card wanting four Body power cannot be cast from three Body runes -- and
    the remainder is spread by how much of the deck each domain is.

    Offered as a button rather than applied silently. It is the one part of a deck with
    a defensible right answer, and also the part a player is most likely to want to
    overrule.
    """
    legend = catalog.get(deck.legend_id)
    needed = rules.int_constraint("rune_count_exact", 0)
    if legend is None or not needed:
        return {}

    pool = legal_zone_pool(
        legend,
        rules.str_constraint("rune_card_type", "Rune"),
        catalog=catalog,
        rules=rules,
    )
    best: dict[str, Card] = {}
    for card in sorted(pool, key=lambda c: c.name):
        if len(card.domains) == 1:
            best.setdefault(card.domains[0], card)
    if not best:
        return {}

    floor = {
        domain: min(power, needed)
        for domain, power in power_floor(deck.main, catalog).items()
        if domain in best
    }
    weight: dict[str, float] = {}
    for card_id, copies in deck.main.items():
        card = catalog.get(card_id)
        if card is None or not card.domains:
            continue
        for domain in card.domains:
            if domain in best:
                weight[domain] = weight.get(domain, 0.0) + copies / len(card.domains)

    split = dict(floor)
    for domain in weight:
        split.setdefault(domain, 1)
    if not split:
        split = {next(iter(best)): needed}

    while sum(split.values()) > needed:
        pick = min(split, key=lambda d: (split[d], -weight.get(d, 0.0)))
        if split[pick] <= 1 and len(split) > 1:
            del split[pick]
        else:
            split[pick] -= 1
    total = sum(weight.get(d, 0.0) for d in split) or 1.0
    while sum(split.values()) < needed:
        pick = max(split, key=lambda d: weight.get(d, 0.0) / total - split[d] / needed)
        split[pick] += 1

    return {best[domain].card_id: n for domain, n in split.items() if n > 0}
