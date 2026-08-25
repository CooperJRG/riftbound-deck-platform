"""The deck model.

Every slot references a ``card_id``. v2 stored decks as JSON blobs of
``{"Honest Broker": 3}`` -- display titles -- so a card renamed upstream silently
orphaned itself out of every saved deck. Nothing here stores a name.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping

ZONE_MAIN = "main"
ZONE_RUNES = "runes"
ZONE_BATTLEFIELDS = "battlefields"
ZONE_SIDEBOARD = "sideboard"
ZONES = (ZONE_MAIN, ZONE_RUNES, ZONE_BATTLEFIELDS, ZONE_SIDEBOARD)


def clean_counts(raw: Mapping[str, int] | None) -> dict[str, int]:
    """Normalise a card_id -> quantity map, dropping empties."""
    out: dict[str, int] = {}
    for key, value in (raw or {}).items():
        card_id = str(key or "").strip().lower()
        try:
            qty = int(value)
        except (TypeError, ValueError):
            continue
        if card_id and qty > 0:
            out[card_id] = out.get(card_id, 0) + qty
    return out


@dataclass(frozen=True)
class Deck:
    """A deck list. Immutable; edits return a new deck."""
    name: str = "Untitled Deck"
    format: str = "constructed"
    legend_id: str = ""
    champion_id: str = ""
    main: Mapping[str, int] = field(default_factory=dict)
    runes: Mapping[str, int] = field(default_factory=dict)
    battlefields: tuple[str, ...] = ()
    sideboard: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def make(
        cls,
        *,
        name: str = "Untitled Deck",
        format: str = "constructed",
        legend_id: str = "",
        champion_id: str = "",
        main: Mapping[str, int] | None = None,
        runes: Mapping[str, int] | None = None,
        battlefields: Iterable[str] = (),
        sideboard: Mapping[str, int] | None = None,
    ) -> "Deck":
        return cls(
            name=str(name or "Untitled Deck").strip() or "Untitled Deck",
            format=str(format or "constructed").strip().lower(),
            legend_id=str(legend_id or "").strip().lower(),
            champion_id=str(champion_id or "").strip().lower(),
            main=clean_counts(main),
            runes=clean_counts(runes),
            battlefields=tuple(str(b).strip().lower() for b in battlefields if str(b).strip()),
            sideboard=clean_counts(sideboard),
        )

    # -- totals -----------------------------------------------------------------

    @property
    def main_total(self) -> int:
        return sum(self.main.values())

    @property
    def rune_total(self) -> int:
        return sum(self.runes.values())

    @property
    def sideboard_total(self) -> int:
        return sum(self.sideboard.values())

    def zone(self, zone: str) -> Mapping[str, int]:
        return {
            ZONE_MAIN: self.main,
            ZONE_RUNES: self.runes,
            ZONE_SIDEBOARD: self.sideboard,
        }.get(zone, {})

    def all_card_ids(self) -> set[str]:
        """Every card the deck references, across all zones."""
        ids = set(self.main) | set(self.runes) | set(self.sideboard) | set(self.battlefields)
        if self.legend_id:
            ids.add(self.legend_id)
        if self.champion_id:
            ids.add(self.champion_id)
        return ids

    # -- edits ------------------------------------------------------------------

    def with_card(self, card_id: str, qty: int, *, zone: str = ZONE_MAIN) -> "Deck":
        """Set the number of copies of a card in a zone (0 removes it)."""
        card_id = str(card_id or "").strip().lower()
        if not card_id:
            return self
        if zone == ZONE_BATTLEFIELDS:
            current = [b for b in self.battlefields if b != card_id]
            if qty > 0:
                current.append(card_id)
            return replace(self, battlefields=tuple(current))
        counts = dict(self.zone(zone))
        if qty > 0:
            counts[card_id] = int(qty)
        else:
            counts.pop(card_id, None)
        if zone == ZONE_MAIN:
            return replace(self, main=counts)
        if zone == ZONE_RUNES:
            return replace(self, runes=counts)
        if zone == ZONE_SIDEBOARD:
            return replace(self, sideboard=counts)
        return self

    def with_meta(self, **kwargs: object) -> "Deck":
        return replace(self, **kwargs)  # type: ignore[arg-type]
