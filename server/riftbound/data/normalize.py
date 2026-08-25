"""Turn messy source rows into clean oracle cards.

All the knowledge about *how upstream data is broken* lives here, in one place, where
it is visible and testable -- rather than smeared across adapters and lookup helpers
as it was in v2.

Two problems this solves, both measured against the real export:

**Reprints must merge, not compete.** 935 printings collapse to 774 gameplay cards.
v2 picked a single "representative" row per name, which meant inheriting that row's
specific gaps: 61 cards would lose their ability-symbol markup (``:rb_exhaust:``
rendered as an empty string) and 7 field values -- a cost, a superType -- exist on
*only* one printing. We merge field by field instead, taking the best value each
field has anywhere.

**Names are not identities.** The same card ships as "Blitzcrank - Impassive" and
"Blitzcrank, Impassive" depending on the printing. Grouping is by ``card_id``, which
is punctuation-insensitive, so both land on one card.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable, Sequence

from ..domain.cards import Card, Printing, parse_domains
from ..domain.ids import card_id_for, clean_text, oracle_name, print_id_for
from .sources.base import RawCard

# Set codes in canonical release order. Used for ordering, and to recognise a code in
# a slug prefix or a set name like "OGN - Origins".
SET_ORDER: tuple[str, ...] = ("OGN", "OGS", "SFD", "UNL", "ARC")
_SET_NAME_TO_CODE = {
    "origins": "OGN",
    "proving grounds": "OGS",
    "origins proving grounds": "OGS",
    "spiritforged": "SFD",
    "unleashed": "UNL",
    "arcane box set": "ARC",
}
_SET_CODE_RE = re.compile(r"^([A-Za-z]{3})\b")

# Ability symbols are encoded as ":rb_exhaust:" in good rows and stripped to nothing
# in degraded ones. Presence of the markup means the text survived intact.
_SYMBOL_MARKUP = re.compile(r":rb_[a-z_]+:")
_UNIQUE_PHRASES = ("your deck can have only 1 card with this name",)


def set_code_for(slug: str, set_name: str) -> str:
    """Canonical 3-letter set code.

    The slug prefix is the reliable signal -- upstream lists the same set as both
    "OGN - Origins" and bare "Origins", but every slug starts with the code.
    """
    match = _SET_CODE_RE.match(str(slug or ""))
    if match and match.group(1).upper() in SET_ORDER:
        return match.group(1).upper()
    name = clean_text(set_name)
    match = _SET_CODE_RE.match(name)
    if match and match.group(1).upper() in SET_ORDER:
        return match.group(1).upper()
    tail = name.split("-", 1)[-1].strip().casefold()
    return _SET_NAME_TO_CODE.get(tail, _SET_NAME_TO_CODE.get(name.casefold(), ""))


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "null":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _coerce_str(value: object) -> str:
    text = clean_text(value)
    return "" if text.lower() == "null" else text


def _authority(raw: RawCard) -> tuple:
    """Sort key: the most trustworthy printing of a card first.

    Base printings beat Showcase/promo reprints, because promo listings are where the
    degraded text and missing fields cluster.
    """
    rarity = _coerce_str(raw.rarity)
    code = set_code_for(raw.slug, raw.set_name)
    number = _coerce_str(raw.card_number)
    digits = re.sub(r"\D", "", number)
    return (
        1 if raw.promo else 0,
        1 if rarity == "Showcase" else 0,
        SET_ORDER.index(code) if code in SET_ORDER else len(SET_ORDER),
        int(digits) if digits else 10**6,
        number,
    )


def _best_text(values: Sequence[str]) -> str:
    """Pick the richest text: prefer surviving symbol markup, then the longest."""
    candidates = [v for v in values if v]
    if not candidates:
        return ""
    with_markup = [v for v in candidates if _SYMBOL_MARKUP.search(v)]
    pool = with_markup or candidates
    # Authority order is preserved, so ties resolve to the most trustworthy printing.
    return max(pool, key=len)


def _first(values: Iterable[object]) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def _is_unique(effect: str) -> bool:
    text = effect.casefold()
    if any(phrase in text for phrase in _UNIQUE_PHRASES):
        return True
    return text.startswith("unique")


def build_tag_vocabulary(all_tags: Iterable[str]) -> frozenset[str]:
    """The set of tags that are genuinely atomic, across the whole catalogue.

    Upstream packs multi-value fields by concatenation without a separator -- the same
    bug that makes ``color`` read "FuryChaos". Merging printings therefore yields both
    forms: ``['Caitlyn', 'Piltover', 'CaitlynPiltover']``. Some cards carry *only* the
    packed form, so the vocabulary has to be built from every card before any card can
    be cleaned.
    """
    tags = {t for t in all_tags if t}
    # Shortest first: a tag can only be built from tags shorter than itself.
    atoms: set[str] = set()
    for tag in sorted(tags, key=len):
        if not _segment(tag, atoms):
            atoms.add(tag)
    return frozenset(atoms)


def unpack_tags(tags: Sequence[str], vocabulary: frozenset[str]) -> tuple[str, ...]:
    """Replace packed tags with their parts, preserving order and dropping repeats."""
    out: list[str] = []
    for tag in tags:
        parts = _segment(tag, vocabulary - {tag}) or [tag]
        for part in parts:
            if part and part not in out:
                out.append(part)
    return tuple(out)


def _segment(text: str, parts: frozenset[str] | set[str]) -> list[str] | None:
    """Split ``text`` into two or more members of ``parts``, or None if impossible."""
    if not text or not parts:
        return None
    # back[i] = the part ending at i on a shortest segmentation of text[:i]
    back: list[str | None] = [None] * (len(text) + 1)
    depth = [-1] * (len(text) + 1)
    depth[0] = 0
    for end in range(1, len(text) + 1):
        for part in parts:
            start = end - len(part)
            if start < 0 or depth[start] < 0 or text[start:end] != part:
                continue
            if depth[end] < 0 or depth[start] + 1 < depth[end]:
                depth[end] = depth[start] + 1
                back[end] = part
    if depth[len(text)] < 2:
        return None
    out: list[str] = []
    cursor = len(text)
    while cursor > 0 and back[cursor]:
        part = back[cursor]
        out.append(part)
        cursor -= len(part)
    return list(reversed(out))


def normalize(
    raws: Iterable[RawCard], *, warnings: list[str] | None = None
) -> list[Card]:
    """Merge source rows into oracle cards.

    Rows that cannot be identified at all are skipped and reported in ``warnings``
    rather than dropped silently.
    """
    log = warnings if warnings is not None else []
    groups: dict[str, list[RawCard]] = defaultdict(list)

    for raw in raws:
        title = _coerce_str(raw.title)
        cid = card_id_for(title)
        if not cid:
            log.append(f"skipped row with unusable title {raw.title!r} from {raw.source}")
            continue
        groups[cid].append(raw)

    # Tag vocabulary is global: some cards carry only the packed form of a tag.
    tag_vocabulary = build_tag_vocabulary(
        _coerce_str(tag) for rows in groups.values() for raw in rows for tag in raw.tags
    )

    cards: list[Card] = []
    for cid, rows in groups.items():
        rows.sort(key=_authority)

        printings: list[Printing] = []
        seen_prints: set[str] = set()
        for raw in rows:
            pid = print_id_for(raw.slug, fallback_title=raw.title)
            if not pid or pid in seen_prints:
                continue
            seen_prints.add(pid)
            printings.append(
                Printing(
                    print_id=pid,
                    card_id=cid,
                    title=_coerce_str(raw.title),
                    set_code=set_code_for(raw.slug, raw.set_name),
                    set_name=_coerce_str(raw.set_name),
                    card_number=_coerce_str(raw.card_number),
                    rarity=_coerce_str(raw.rarity),
                    promo=bool(raw.promo),
                    image_url=_coerce_str(raw.image_url),
                )
            )

        effect = _best_text([_coerce_str(r.effect) for r in rows])
        color = str(_first(_coerce_str(r.color) or None for r in rows) or "")
        domains, domains_ok = parse_domains(color)

        tags: list[str] = []
        for raw in rows:
            for tag in raw.tags:
                clean = _coerce_str(tag)
                if clean and clean not in tags:
                    tags.append(clean)
        tags = list(unpack_tags(tags, tag_vocabulary))

        card_type = str(_first(_coerce_str(r.card_type) or None for r in rows) or "")
        if not card_type:
            log.append(f"{cid}: no printing declares a card type")

        cards.append(
            Card(
                card_id=cid,
                name=oracle_name(rows[0].title),
                card_type=card_type,
                super_type=str(_first(_coerce_str(r.super_type) or None for r in rows) or ""),
                domains=domains,
                domains_ok=domains_ok,
                cost=_first(_coerce_int(r.cost) for r in rows),
                might=_first(_coerce_int(r.might) for r in rows),
                tags=tuple(tags),
                champion_tags=(),  # filled in by _attach_champion_tags below
                effect=effect,
                flavor=_best_text([_coerce_str(r.flavor) for r in rows]),
                unique=_is_unique(effect),
                printings=tuple(printings),
            )
        )

    return _attach_champion_tags(cards)


def _attach_champion_tags(cards: list[Card]) -> list[Card]:
    """Mark which of a card's tags name a champion.

    Champion identity drives Riftbound's chosen-champion and signature-card rules, so
    it must be derived from the data rather than hardcoded. A tag is a champion tag
    when some card with super type "Champion" is named after it: "Caitlyn - Patrolling"
    is a Champion, so the tag "Caitlyn" is a champion tag while "Piltover" is not.
    """
    champion_names = {
        card.name.split(" - ", 1)[0].strip().casefold()
        for card in cards
        if card.super_type == "Champion"
    }
    champion_names.discard("")

    out: list[Card] = []
    for card in cards:
        matched = tuple(t for t in card.tags if t.casefold() in champion_names)
        out.append(card if matched == card.champion_tags else _replace_tags(card, matched))
    return out


def _replace_tags(card: Card, champion_tags: tuple[str, ...]) -> Card:
    return Card(
        card_id=card.card_id,
        name=card.name,
        card_type=card.card_type,
        super_type=card.super_type,
        domains=card.domains,
        domains_ok=card.domains_ok,
        cost=card.cost,
        might=card.might,
        tags=card.tags,
        champion_tags=champion_tags,
        effect=card.effect,
        flavor=card.flavor,
        unique=card.unique,
        printings=card.printings,
    )
