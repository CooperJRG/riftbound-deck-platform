"""Card catalog: immutable, id-keyed, and tolerant of cards it has never seen.

Two levels (see ``ids``): a ``Card`` is the gameplay object a deck references; a
``Printing`` is one physical version a collection can own.

Unknown cards are a first-class case. A new set must never crash deck validation or
orphan a saved deck, so every lookup that misses returns ``None`` and callers surface
it as a *reported* problem rather than an exception or a silent drop.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field

from .ids import card_id_for, search_key

BASE_DOMAINS: tuple[str, ...] = ("Body", "Calm", "Chaos", "Fury", "Mind", "Order")
_DOMAIN_LOOKUP = {d.lower(): d for d in BASE_DOMAINS}

RARITY_ORDER: tuple[str, ...] = ("Common", "Uncommon", "Rare", "Epic", "Showcase")


def coerce_card_types(value: object) -> tuple[str, ...]:
    """Card types from whatever shape a source supplies.

    Upstream changed ``type`` from a string ("Unit") to a list (``["Unit"]``), and a
    handful of cards are genuinely two types at once (``["Unit", "Gear"]``). Both
    shapes land here so no adapter has to know, exactly as :func:`coerce_domains`
    handles the same drift in ``color``.

    This is not cosmetic. Before it existed the list was stringified, so every card
    reported its type as ``"['Unit']"`` -- which matches no rule, no zone and no
    filter in the app. Runes stopped being runes, no deck was legal, and Smart Decks
    reported that nothing in the legal pool could fill a champion slot.

    >>> coerce_card_types("Unit")
    ('Unit',)
    >>> coerce_card_types(["Unit", "Gear"])
    ('Unit', 'Gear')
    >>> coerce_card_types(None)
    ()
    """
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        # Order is preserved rather than sorted: the first entry is the card's primary
        # type, which is what decides its zone.
        return tuple(t for t in (str(v).strip() for v in value) if t)
    text = str(value).strip()
    return (text,) if text else ()


def coerce_domains(color: object) -> tuple[tuple[str, ...], bool]:
    """Domains from whatever shape a source supplies.

    Modern sources give a proper list (``["Mind", "Body"]``); older exports pack them
    into one string (``"MindBody"``). Both land here so no adapter has to know.
    """
    if isinstance(color, (list, tuple, set)):
        found = tuple(
            sorted({_DOMAIN_LOOKUP[str(c).strip().lower()]
                    for c in color
                    if str(c).strip().lower() in _DOMAIN_LOOKUP})
        )
        # A non-empty list whose entries we did not recognise is a parse failure;
        # an empty list is a colourless card, which is a fact, not a failure.
        recognised = len(found) == len([c for c in color if str(c).strip()])
        return found, recognised
    return parse_domains(color)


def parse_domains(color: object) -> tuple[tuple[str, ...], bool]:
    """Split a packed colour string into domains.

    Upstream packs multi-domain cards as "FuryChaos" and single-domain as "Fury".
    Returns ``(domains, parsed_ok)``; ``parsed_ok`` is False when the value is
    missing or unrecognised, which callers treat as "do not enforce identity"
    rather than "has no domains".

    >>> parse_domains("FuryChaos")
    (('Chaos', 'Fury'), True)
    >>> parse_domains("Colorless")
    ((), True)
    """
    raw = str(color or "").strip()
    if not raw or raw.lower() == "null":
        return (), False
    if raw.lower() == "colorless":
        return (), True

    found: list[str] = []
    rest = raw
    while rest:
        for lowered, canonical in _DOMAIN_LOOKUP.items():
            if rest.lower().startswith(lowered):
                found.append(canonical)
                rest = rest[len(lowered):]
                break
        else:
            return tuple(sorted(set(found))), False
    return tuple(sorted(set(found))), True


@dataclass(frozen=True)
class Printing:
    """One physical version of a card."""
    print_id: str
    card_id: str
    title: str            # full title, including any promo suffix
    set_code: str         # "OGN", "SFD", "UNL", "OGS", "ARC", "VEN", ...
    set_name: str
    card_number: str
    rarity: str
    promo: bool
    image_url: str

    @property
    def code(self) -> str:
        """Collector code, e.g. "OGN-068".

        This is how decklists reference cards everywhere upstream, so it is the join
        key when importing an external list. Upper-cased because upstream is not
        internally consistent about case — the card list ships "VEN-R02a" while
        decklists reference "VEN-R02A", and it even varies within one set
        ("VEN-R04B-P" beside "VEN-R02b-P"). Matching case-sensitively silently loses
        those cards from imported lists.
        """
        if not self.set_code or not self.card_number:
            return ""
        return f"{self.set_code}-{self.card_number}".upper()


@dataclass(frozen=True)
class Card:
    """A gameplay card. Fields are merged across all of its printings."""
    card_id: str
    name: str
    #: The card's *primary* type -- what decides its zone. Unit | Spell | Gear |
    #: Battlefield | Legend | Rune | Token.
    card_type: str
    super_type: str       # Champion | Signature | Basic | Token | ""
    domains: tuple[str, ...]
    domains_ok: bool
    cost: int | None
    might: int | None
    tags: tuple[str, ...]
    champion_tags: tuple[str, ...]
    effect: str
    flavor: str
    unique: bool
    #: The card's own text lifts the format's copy limit ("Your deck can have any
    #: number of cards named X"). A property of the card, not of the format, so it
    #: travels with the card rather than living in a rules profile that would go stale
    #: the moment another one is printed.
    #: The domain-specific half of the cost, paid with runes of the card's own domain.
    #: Energy covers the rest and is domain-free, so this -- not ``cost`` -- is what a
    #: rune base has to satisfy. Defaulted because a bundle built before it was
    #: ingested has no value for it, and a card with an unknown power requirement should
    #: read as unknown rather than as zero.
    power: int | None = None
    unlimited_copies: bool = False
    #: The source's own ban flag. Advisory only — a format's rules profile decides
    #: legality. Kept so the pipeline can report when the two have drifted apart,
    #: because ban lists go stale exactly the way set lists do.
    banned_upstream: bool = False
    #: Every type the card has, primary first. Almost always one; two cards in the
    #: current pool are ``('Unit', 'Gear')``. `card_type` stays the primary so that
    #: zone assignment -- which has exactly one right answer -- is unchanged, while
    #: rules that ask "is this a Gear" can consult the whole set.
    #:
    #: Defaulted to empty and read through :meth:`is_type`, so a bundle built before
    #: this existed keeps working off `card_type` alone.
    card_types: tuple[str, ...] = ()
    printings: tuple[Printing, ...] = field(default_factory=tuple)

    @property
    def all_types(self) -> tuple[str, ...]:
        """Every type this card has. Falls back to the primary for older bundles."""
        return self.card_types or ((self.card_type,) if self.card_type else ())

    def is_type(self, name: str) -> bool:
        """Whether the card is of a type, counting secondary ones.

        Use this wherever a *rule* asks about a type -- legality, filtering. Zone
        assignment keeps comparing `card_type`, because a card goes in exactly one
        zone and the primary type is what decides which.
        """
        return any(t == name for t in self.all_types)

    @property
    def default_printing(self) -> Printing | None:
        return self.printings[0] if self.printings else None

    @property
    def image_url(self) -> str:
        for p in self.printings:
            if p.image_url:
                return p.image_url
        return ""

    @property
    def rarity(self) -> str:
        """Rarity of the most common printing — what a casual player likely owns."""
        ranked = [p.rarity for p in self.printings if p.rarity in RARITY_ORDER]
        if not ranked:
            return ""
        return min(ranked, key=RARITY_ORDER.index)

    @property
    def set_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(p.set_code for p in self.printings if p.set_code))

    def in_domains(self, allowed: Iterable[str]) -> bool:
        """Is this card inside a domain identity? Unparseable domains never block."""
        allowed_set = set(allowed)
        if not allowed_set or not self.domains_ok:
            return True
        return set(self.domains).issubset(allowed_set)


@dataclass(frozen=True)
class Catalog:
    """Immutable card catalog with id-first lookup and name fallback."""
    cards: tuple[Card, ...]
    _by_card_id: Mapping[str, Card]
    _by_print_id: Mapping[str, Printing]
    _by_search_key: Mapping[str, Card]
    _by_code: Mapping[str, Card]

    def __iter__(self) -> Iterator[Card]:
        return iter(self.cards)

    def __len__(self) -> int:
        return len(self.cards)

    def get(self, card_id: str) -> Card | None:
        """Primary lookup. Returns None for cards this bundle does not know."""
        return self._by_card_id.get(str(card_id or "").strip().lower())

    def printing(self, print_id: str) -> Printing | None:
        return self._by_print_id.get(str(print_id or "").strip().lower())

    def by_code(self, code: str) -> Card | None:
        """Resolve a collector code such as "OGN-068" to its gameplay card.

        Imported decklists address cards this way. Unlike a name, a code is stable and
        unambiguous, so an imported list survives renames and promo variants.
        """
        return self._by_code.get(str(code or "").strip().upper())

    def resolve(self, text: str) -> Card | None:
        """Best-effort lookup for a human- or importer-supplied name.

        Tries card_id, then print_id, then a punctuation-insensitive name key.
        Used only at the import boundary; never for storage.
        """
        raw = str(text or "").strip()
        if not raw:
            return None
        direct = self.get(raw)
        if direct is not None:
            return direct
        by_code = self.by_code(raw)
        if by_code is not None:
            return by_code
        printing = self.printing(raw)
        if printing is not None:
            return self.get(printing.card_id)
        by_id = self._by_card_id.get(card_id_for(raw))
        if by_id is not None:
            return by_id
        return self._by_search_key.get(search_key(raw))

    def of_type(self, card_type: str) -> tuple[Card, ...]:
        return tuple(c for c in self.cards if c.card_type == card_type)


def build_catalog(cards: Iterable[Card]) -> Catalog:
    ordered = tuple(sorted(cards, key=lambda c: c.name.casefold()))
    by_card_id: dict[str, Card] = {}
    by_print_id: dict[str, Printing] = {}
    by_search: dict[str, Card] = {}
    by_code: dict[str, Card] = {}
    for card in ordered:
        by_card_id[card.card_id] = card
        by_search.setdefault(search_key(card.name), card)
        for printing in card.printings:
            by_print_id[printing.print_id] = printing
            if printing.code:
                by_code.setdefault(printing.code, card)
            # Full promo titles resolve back to the gameplay card.
            by_search.setdefault(search_key(printing.title), card)
    return Catalog(
        cards=ordered,
        _by_card_id=by_card_id,
        _by_print_id=by_print_id,
        _by_search_key=by_search,
        _by_code=by_code,
    )
