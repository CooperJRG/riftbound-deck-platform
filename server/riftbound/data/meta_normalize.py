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

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

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
        )
        for row in rows
        if str(row.get("tournament_slug") or "")
    ]


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


def deck_from_payload(
    payload: Mapping[str, Any], *, catalog: Catalog
) -> tuple[Deck, tuple[str, ...]]:
    """Split a flat code->quantity map into zones. Returns the deck and unresolved codes."""
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

        deck, unresolved = deck_from_payload(payload, catalog=catalog)
        if deck.main_total == 0:
            continue  # a scratch deck with no cards is not a meta deck

        standing = by_slug.get(slug)
        tournament = tournament_by_slug.get(standing.tournament_slug) if standing else None
        evidence = _evidence_for(standing, payload)

        out.append(
            MetaDeck(
                deck=deck,
                unresolved=unresolved,
                provenance=Provenance(
                    source="dotgg",
                    source_slug=slug,
                    url=deck_url(slug),
                    published_at=_iso_date(payload.get("date_edited") or payload.get("date")),
                    author=str(payload.get("authornick") or "").strip(),
                    views=_int(payload.get("views")),
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
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(int(str(value)), tz=timezone.utc).date().isoformat()
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
