"""Card identity.

v2's fatal data decision was keying every stored deck and collection row on the
card's *display title*. Upstream data is not consistent about titles: the same card
appears as both "Blitzcrank - Impassive" and "Blitzcrank, Impassive", and promo
printings carry parenthetical suffixes. A renamed card silently orphaned itself out
of every saved deck.

This module defines two stable identifiers:

``card_id``   The game card ("caitlyn-patrolling"). Riftbound's deck rules operate on
              card *names* — copy limits are per name — so the oracle name is the
              gameplay identity. **Decks reference card_id.**

``print_id``  One physical printing ("ogn-068a-caitlyn-patrolling"). Distinguishes the
              base printing from its Showcase and promo variants. **Collections
              reference print_id** so a user can own a specific version.

Many print_ids map to one card_id. Nothing else in the system may be used as a key.
"""

from __future__ import annotations

import re
import unicodedata

# Trailing "(Origins Release Event Promo)", "(TFT Promo)", ...
_PARENTHETICAL_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")
# Trailing "- Starter" / ", starter"
_STARTER_SUFFIX = re.compile(r"\s*[-,]\s*starter\s*$", re.IGNORECASE)
_NON_SLUG = re.compile(r"[^a-z0-9]+")

_DASH_VARIANTS = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2212": "-",
}
_QUOTE_VARIANTS = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2032": "'", "\uff07": "'",
}


def clean_text(value: object) -> str:
    """Normalize unicode punctuation so upstream variants compare equal."""
    text = unicodedata.normalize("NFC", str(value or "")).strip()
    for src, dst in _DASH_VARIANTS.items():
        text = text.replace(src, dst)
    for src, dst in _QUOTE_VARIANTS.items():
        text = text.replace(src, dst)
    # Upstream sometimes HTML-escapes apostrophes into the slug ("emperor-039-s-dais").
    return text


def oracle_name(title: object) -> str:
    """The card's gameplay name, with printing-specific decoration removed.

    >>> oracle_name("Caitlyn - Patrolling (Chinese Arcane Box Set Promo)")
    'Caitlyn - Patrolling'
    """
    text = clean_text(title)
    if not text:
        return ""
    text = _PARENTHETICAL_SUFFIX.sub("", text)
    text = _STARTER_SUFFIX.sub("", text)
    return text.strip()


def card_id_for(title: object) -> str:
    """Stable gameplay identifier derived from the oracle name.

    Separator punctuation is dropped, so "Blitzcrank - Impassive" and
    "Blitzcrank, Impassive" — the same card, spelled two ways upstream — agree.

    >>> card_id_for("Blitzcrank, Impassive")
    'blitzcrank-impassive'
    >>> card_id_for("Kai'Sa - Daughter of the Void")
    'kaisa-daughter-of-the-void'
    """
    name = oracle_name(title)
    if not name:
        return ""
    # Drop apostrophes entirely rather than turning them into separators, so
    # "Kai'Sa" -> "kaisa" and not "kai-sa".
    name = name.replace("'", "")
    return _NON_SLUG.sub("-", name.lower()).strip("-")


def print_id_for(slug: object, *, fallback_title: object = "") -> str:
    """Identifier for one printing. Uses the upstream slug when present."""
    text = _NON_SLUG.sub("-", clean_text(slug).lower()).strip("-")
    if text:
        return text
    return card_id_for(fallback_title)


def search_key(value: object) -> str:
    """Aggressive key for fuzzy lookup of user- and importer-supplied names."""
    return _NON_SLUG.sub("", clean_text(value).lower().replace("'", ""))
