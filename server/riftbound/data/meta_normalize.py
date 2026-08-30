"""Raw meta payloads -> :class:`MetaDeck`.

Upstream gives a flat map of collector codes to quantities (``{"OGN-043": "3"}``) with
no zone information. Zones are recovered from each card's type in the catalogue, which
is more robust than trusting an upstream field: it stays correct for cards released
after this code was written, and it fails visibly when a code cannot be resolved.

Unresolvable codes are **reported on the deck**, never dropped. A list that references a
card the current bundle lacks is visibly incomplete rather than quietly wrong — and its
score is penalised for it (see ``meta_scoring``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC
from typing import Any

from ..domain.cards import Card, Catalog
from ..domain.deck import Deck
from ..domain.meta import (
    EVIDENCE_COMMUNITY,
    EVIDENCE_TOURNAMENT_ENTRY,
    EVIDENCE_TOURNAMENT_PLACED,
    MetaDeck,
    Provenance,
    Standing,
    Tournament,
)
from .sources.dotgg_meta import deck_url, iter_board_entries


def _int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def tournaments_from(rows: Iterable[Mapping[str, Any]]) -> list[Tournament]:
    out: list[Tournament] = []
    for row in rows:
        slug = str(row.get("slug") or "").strip()
        if not slug:
            continue
        out.append(
            Tournament(
                tournament_id=str(row.get("tournament_id") or slug),
                slug=slug,
                name=str(row.get("name") or "").strip(),
                date=str(row.get("date") or ""),
                format=str(row.get("format") or "").strip(),
                players=_int(row.get("players")),
                organizer=str(row.get("organizer") or "").strip(),
                winner=str(row.get("winner") or "").strip(),
                decks_published=_int(row.get("decks_published")),
            )
        )
    out.sort(key=lambda t: t.date, reverse=True)
    return out


def standings_from(rows: Iterable[Mapping[str, Any]]) -> list[Standing]:
    return [
        Standing(
            tournament_slug=str(row.get("tournament_slug") or ""),
            place=_int(row.get("place")),
            player_name=str(row.get("player_name") or "").strip(),
            deck_slug=str(row.get("deck_slug") or "").strip(),
            record=str(row.get("record") or "").strip(),
            wins=_int(row.get("wins")),
            losses=_int(row.get("losses")),
            draws=_int(row.get("draws")),
        )
        for row in rows
        if str(row.get("tournament_slug") or "")
    ]


def _nominatable(card_id: str, legend: Card | None, catalog: Catalog) -> bool:
    """Could this champion have been nominated for this legend?

    Champion-tag identity only. Whether the card is *banned* is a different question and
    a moving one -- a deck played before a banning nominated a champion that was legal at
    the time, and rewriting its history to suit today's list would be a worse error than
    the one this guards against. 265 archived decks nominate Draven - Vanquisher, which
    is legal identity and a later ban.
    """
    card = catalog.get(card_id)
    if card is None or card.super_type != "Champion":
        return False
    if legend is None or not legend.champion_tags:
        return True
    return bool(
        {t.casefold() for t in card.champion_tags}
        & {t.casefold() for t in legend.champion_tags}
    )


def _pick_champion(main: Mapping[str, int], legend: Card | None, catalog: Catalog) -> str:
    """Infer the chosen champion from the list.

    The nomination is a player declaration that upstream does not record, so it has to
    be inferred. A champion in the main deck that shares a champion tag with the legend
    is the only legal candidate; where several qualify the most-played one wins, which
    matches how these decks are actually built.
    """
    legend_tags = {t.casefold() for t in legend.champion_tags} if legend else set()
    candidates: list[tuple[int, str]] = []
    for card_id, qty in main.items():
        card = catalog.get(card_id)
        if card is None or card.super_type != "Champion":
            continue
        tags = {t.casefold() for t in card.champion_tags}
        if legend_tags and not (tags & legend_tags):
            continue
        candidates.append((qty, card_id))
    if not candidates:
        return ""
    candidates.sort(key=lambda row: (-row[0], row[1]))
    return candidates[0][1]


def _deck_from_zones(
    payload: Mapping[str, Any], *, catalog: Catalog, main_deck_size: int = 0
) -> tuple[Deck, tuple[str, ...]]:
    """Build a deck from a source that already separates its zones.

    TopDeck supplies these, including the **chosen champion** — which the flat-map path
    below has to infer from champion tags. Where a source states it, we take its word.
    """
    zones: Mapping[str, Mapping[str, int]] = payload.get("_zones") or {}
    unresolved: list[str] = []

    def resolve(zone: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for code, qty in (zones.get(zone) or {}).items():
            card = catalog.by_code(code)
            if card is None:
                unresolved.append(code)
                continue
            out[card.card_id] = out.get(card.card_id, 0) + int(qty)
        return out

    def single(zone: str) -> str:
        resolved = resolve(zone)
        return next(iter(resolved), "")

    battlefields: list[str] = []
    for card_id, qty in resolve("battlefields").items():
        battlefields.extend([card_id] * max(1, qty))

    main = resolve("main")
    champions = resolve("champion")

    # Riftbound's chosen champion is *part of* the 40-card main deck, but TopDeck lists
    # it in a zone of its own. Folding those copies in is what makes the count come out
    # at 40 rather than 39.
    #
    # The copy is *additional*, even when the same card also appears in Mainboard — a
    # player may run three and nominate one of them. An earlier version skipped the fold
    # whenever the champion was already named in Mainboard, on the assumption that the
    # source was repeating itself. It is not: those lists are 39 + 1, exactly like the
    # rest, and skipping left 105 decks a card short.
    #
    # So fold, and only decline when folding actually overshoots the format's main deck
    # *and* the champion was already listed -- which is the one shape that really is a
    # duplicate. Two decks in the live archive look like that.
    folded = dict(main)
    for card_id, qty in champions.items():
        folded[card_id] = folded.get(card_id, 0) + qty
    duplicated = any(card_id in main for card_id in champions)
    if main_deck_size and duplicated and sum(folded.values()) > main_deck_size:
        folded = dict(main)
    main = folded

    # Prefer the source's own champion; fall back to inference when it records none.
    # TopDeck omits the champion for 1,371 of 2,861 live decks, and without this those
    # decks fail legality for "no chosen champion" — a gap in the feed, not the deck.
    #
    # But only when the source's champion could actually have been nominated. A
    # nomination has to share a champion tag with the legend, and the feed does not
    # check: one list arrived as a Kennen deck nominating Nocturne - Horrifying, which
    # is not a Kennen champion and never could have been chosen. Kennen - Storm of
    # Shuriken was sitting in its main deck all along. Taken at face value the deck is
    # attributed to the wrong champion on every trend that counts it.
    legend_id = single("legend")
    legend_card = catalog.get(legend_id) if legend_id else None
    champion_id = next(iter(champions), "")
    if champion_id and not _nominatable(champion_id, legend_card, catalog):
        champion_id = ""
    if not champion_id:
        champion_id = _pick_champion(main, legend_card, catalog)

    deck = Deck.make(
        name=str(payload.get("humanname") or payload.get("name") or "Untitled").strip(),
        format="constructed",
        legend_id=legend_id,
        champion_id=champion_id,
        main=main,
        runes=resolve("runes"),
        battlefields=battlefields,
        sideboard=resolve("sideboard"),
    )
    return deck, tuple(dict.fromkeys(unresolved))


def _resolve_named_zones(
    payload: Mapping[str, Any], *, catalog: Catalog
) -> Mapping[str, Mapping[str, int]]:
    """Convert name-keyed zones to code-keyed ones so one path handles both.

    Some sources address cards by name rather than collector code. ``Catalog.resolve``
    is punctuation-insensitive, which matters here: these names use commas
    ("Irelia, Blade Dancer") where the catalogue uses dashes.
    """
    resolved: dict[str, dict[str, int]] = {}
    for zone, entries in (payload.get("_named_zones") or {}).items():
        bucket = resolved.setdefault(zone, {})
        for name, qty in entries.items():
            card = catalog.resolve(name)
            # Unresolvable names keep their original text so they surface as unresolved
            # rather than vanishing from the list.
            key = card.printings[0].code if card and card.printings else str(name)
            bucket[key] = bucket.get(key, 0) + int(qty)
    return resolved


def deck_from_payload(
    payload: Mapping[str, Any], *, catalog: Catalog, main_deck_size: int = 0
) -> tuple[Deck, tuple[str, ...]]:
    """Build a deck from a source payload.

    Three shapes are accepted and all end at the same :class:`Deck`: zones keyed by
    collector code (TopDeck), zones keyed by card name (the local deck API), and a flat
    code map where zones must be recovered from each card's type (dotgg).
    """
    if payload.get("_named_zones"):
        payload = {**payload, "_zones": _resolve_named_zones(payload, catalog=catalog)}
    if payload.get("_zones"):
        return _deck_from_zones(payload, catalog=catalog, main_deck_size=main_deck_size)

    main: dict[str, int] = {}
    runes: dict[str, int] = {}
    battlefields: list[str] = []
    legend_id = ""
    unresolved: list[str] = []

    for code, qty in iter_board_entries(dict(payload)):
        if qty <= 0:
            continue
        card = catalog.by_code(code)
        if card is None:
            unresolved.append(code)
            continue
        if card.card_type == "Legend":
            # Only one legend is legal; keep the first and treat extras as noise.
            legend_id = legend_id or card.card_id
        elif card.card_type == "Rune":
            runes[card.card_id] = runes.get(card.card_id, 0) + qty
        elif card.card_type == "Battlefield":
            for _ in range(qty):
                battlefields.append(card.card_id)
        else:
            main[card.card_id] = main.get(card.card_id, 0) + qty

    legend = catalog.get(legend_id) if legend_id else None
    deck = Deck.make(
        name=str(payload.get("humanname") or payload.get("name") or "Untitled").strip(),
        format="constructed",
        legend_id=legend_id,
        champion_id=_pick_champion(main, legend, catalog),
        main=main,
        runes=runes,
        battlefields=battlefields,
        sideboard={},
    )
    return deck, tuple(dict.fromkeys(unresolved))


def _evidence_for(standing: Standing | None, payload: Mapping[str, Any]) -> str:
    if standing is not None and standing.place > 0:
        return EVIDENCE_TOURNAMENT_PLACED
    if standing is not None or str(payload.get("is_tournament") or "0") == "1":
        return EVIDENCE_TOURNAMENT_ENTRY
    return EVIDENCE_COMMUNITY


def normalize_meta_decks(
    payloads: Sequence[Mapping[str, Any]],
    *,
    catalog: Catalog,
    standings: Sequence[Standing] = (),
    tournaments: Sequence[Tournament] = (),
    warnings: list[str] | None = None,
    main_deck_size: int = 0,
) -> list[MetaDeck]:
    """Build MetaDecks, joining decklists to tournament results where both exist."""
    log = warnings if warnings is not None else []
    by_slug = {s.deck_slug: s for s in standings if s.deck_slug}
    tournament_by_slug = {t.slug: t for t in tournaments}

    out: list[MetaDeck] = []
    skipped_private = 0
    for payload in payloads:
        slug = str(payload.get("_slug") or payload.get("slug") or "").strip()
        if not slug:
            continue
        # Private decks are not ours to publish, even when the API serves them.
        if str(payload.get("public") or "0") != "1":
            skipped_private += 1
            continue

        deck, unresolved = deck_from_payload(
            payload, catalog=catalog, main_deck_size=main_deck_size
        )
        if deck.main_total == 0:
            continue  # a scratch deck with no cards is not a meta deck

        standing = by_slug.get(slug)
        tournament = tournament_by_slug.get(standing.tournament_slug) if standing else None
        evidence = _evidence_for(standing, payload)
        source = str(payload.get("_source") or "dotgg")
        url = str(payload.get("_tournament_url") or "") or deck_url(slug)

        out.append(
            MetaDeck(
                deck=deck,
                unresolved=unresolved,
                provenance=Provenance(
                    source=source,
                    source_slug=slug,
                    url=url,
                    published_at=(
                        str(payload.get("published_date") or "").strip()
                        or _iso_date(payload.get("date_edited") or payload.get("date"))
                    ),
                    author=str(payload.get("authornick") or "").strip(),
                    views=_int(payload.get("views")),
                    quality=float(payload.get("_quality") or 0.0),
                    evidence=evidence,
                    tournament_slug=standing.tournament_slug if standing else "",
                    tournament_name=tournament.name if tournament else "",
                    tournament_date=tournament.date if tournament else "",
                    placement=standing.place if standing else 0,
                    field_size=tournament.players if tournament else 0,
                ),
            )
        )
        if unresolved:
            log.append(f"{slug}: {len(unresolved)} unresolved card code(s): {', '.join(unresolved[:4])}")

    if skipped_private:
        log.append(f"skipped {skipped_private} non-public deck(s)")
    return out


def _iso_date(value: object) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC).date().isoformat()
    except (TypeError, ValueError):
        return ""


def summarise(decks: Sequence[MetaDeck]) -> dict[str, int]:
    counts = Counter(d.provenance.evidence for d in decks)
    return {
        "total": len(decks),
        "tournamentPlaced": counts.get(EVIDENCE_TOURNAMENT_PLACED, 0),
        "tournamentEntry": counts.get(EVIDENCE_TOURNAMENT_ENTRY, 0),
        "community": counts.get(EVIDENCE_COMMUNITY, 0),
        "incomplete": sum(1 for d in decks if not d.is_complete),
    }


# -- repairing what upstream got wrong ----------------------------------------
#
# Published lists arrive with three recurring defects, and all three are recoverable
# from the corpus itself rather than by guessing. Doing it here, once, at ingest keeps
# every downstream view working from the same repaired data instead of each deciding
# separately what to do with a deck that has four battlefields.


@dataclass(frozen=True)
class RepairReport:
    battlefields_trimmed: int = 0
    battlefields_filled: int = 0
    champions_inferred: int = 0
    dropped_no_champion: int = 0

    @property
    def touched(self) -> int:
        return (
            self.battlefields_trimmed
            + self.battlefields_filled
            + self.champions_inferred
            + self.dropped_no_champion
        )

    def render(self) -> str:
        if not self.touched:
            return "  nothing to repair"
        lines = []
        if self.battlefields_trimmed:
            lines.append(f"  trimmed battlefields on {self.battlefields_trimmed} deck(s)")
        if self.battlefields_filled:
            lines.append(f"  filled battlefields on {self.battlefields_filled} deck(s)")
        if self.champions_inferred:
            lines.append(f"  inferred a champion for {self.champions_inferred} deck(s)")
        if self.dropped_no_champion:
            lines.append(f"  dropped {self.dropped_no_champion} deck(s) with no legal champion")
        return "\n".join(lines)


def _battlefield_popularity(decks: Sequence[MetaDeck]) -> dict[str, Counter[str]]:
    """How often each archetype plays each battlefield.

    The corpus is the authority on what belongs in a deck: a battlefield the rest of the
    archetype runs is a defensible thing to add, and one nobody else runs is the
    defensible thing to drop. Both beat picking alphabetically.
    """
    by_archetype: dict[str, Counter[str]] = defaultdict(Counter)
    by_legend: dict[str, Counter[str]] = defaultdict(Counter)
    for deck in decks:
        for card_id in set(deck.deck.battlefields):
            by_archetype[deck.archetype_id][card_id] += 1
            by_legend[deck.deck.legend_id][card_id] += 1
    # Fall back to the legend when an archetype is too rare to have an opinion.
    for archetype_id, counts in by_archetype.items():
        legend_id = archetype_id.split("::")[0]
        for card_id, n in by_legend.get(legend_id, Counter()).items():
            counts.setdefault(card_id, 0)
            counts[card_id] = max(counts[card_id], 0) or n
    return by_archetype


def repair_meta_decks(
    decks: Sequence[MetaDeck],
    *,
    catalog: Catalog,
    battlefield_count: int = 3,
    warnings: list[str] | None = None,
) -> tuple[list[MetaDeck], RepairReport]:
    """Fix the recoverable defects in published lists, and drop what cannot be fixed.

    * **Too many battlefields** -- trim the ones this archetype plays least. A list with
      four is usually a sideboard battlefield recorded in the wrong zone.
    * **Too few** -- fill from the ones it plays most, chosen only from battlefields the
      archetype already runs, so the addition is legal for that legend by construction
      rather than by a domain check we would have to keep in step with the rules.
    * **No champion** -- take one from the list if a legal one is there. If none is, the
      deck cannot be played as recorded and is dropped: a deck with no champion is not
      a deck, and keeping it would put a legend's numbers on a list nobody could field.
    """
    log = warnings if warnings is not None else []
    popularity = _battlefield_popularity(decks)
    trimmed = filled = inferred = dropped = 0
    out: list[MetaDeck] = []

    for deck in decks:
        current = list(deck.deck.battlefields)
        champion_id = deck.deck.champion_id

        if not champion_id:
            legend = catalog.get(deck.deck.legend_id) if deck.deck.legend_id else None
            champion_id = _pick_champion(deck.deck.main, legend, catalog)
            if not champion_id:
                dropped += 1
                log.append(
                    f"{deck.provenance.source_slug}: dropped, no legal champion in the list"
                )
                continue
            inferred += 1

        if battlefield_count and len(current) != battlefield_count:
            counts = popularity.get(deck.archetype_id, Counter())
            if len(current) > battlefield_count:
                # Least played by this archetype goes first; name breaks ties so a
                # rebuild of the same snapshot produces the same deck.
                current.sort(key=lambda cid: (counts.get(cid, 0), cid), reverse=True)
                current = current[:battlefield_count]
                trimmed += 1
            elif current:
                # Only a list that recorded *some* battlefields is filled. A list that
                # recorded none never had the zone at all -- a different upstream
                # contract, not a transcription slip -- and inventing all three would
                # feed the popularity counts straight back into themselves: the most
                # played battlefield gets assigned to every deck that named none, which
                # makes it the most played. One source publishes 4,471 lists shaped that
                # way, 89% of them without the zone, so the loop is not hypothetical.
                have = set(current)
                extra = [cid for cid, _n in counts.most_common() if cid not in have]
                if len(current) + len(extra) >= battlefield_count:
                    current.extend(extra[: battlefield_count - len(current)])
                    filled += 1

        if champion_id == deck.deck.champion_id and current == list(deck.deck.battlefields):
            out.append(deck)
            continue

        out.append(
            replace(
                deck,
                deck=replace(
                    deck.deck,
                    champion_id=champion_id,
                    battlefields=tuple(sorted(current)),
                ),
            )
        )

    return out, RepairReport(
        battlefields_trimmed=trimmed,
        battlefields_filled=filled,
        champions_inferred=inferred,
        dropped_no_champion=dropped,
    )
