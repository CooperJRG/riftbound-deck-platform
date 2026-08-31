"""The competitive meta, filtered through what the player can actually field.

Every deck is returned with three things attached:

* **provenance** — where it came from and what backs it, so a ranking can be argued with;
* **score** with its breakdown, for the same reason;
* **coverage** against the active availability profile — the number that matters to a
  casual player, because "3rd of 257" is only useful alongside "and you're four cards
  short of it".

That last join is the reason meta tracking earns its place here rather than being a link
to someone else's tier list.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ...data.scheduler import snapshot_age_hours
from ...domain.availability import deck_coverage
from ...domain.eras import eras_for_format
from ...domain.meta import EVIDENCE_TIERS, MetaDeck, build_archetypes
from ...domain.meta_scoring import score_all, totals
from ...domain.meta_trends import (
    TrendFilter,
    archive_span,
    card_detail,
    card_trends,
    champion_meta,
    default_range,
    legend_meta,
    parse_date,
)
from ...domain.meta_trends import (
    overview as trend_overview,
)
from ...domain.meta_trends import (
    tournament_detail as build_tournament_detail,
)
from ...services import Services, get_services, reset_services
from ..identity import Identity, current_identity
from ..schemas import (
    ArchetypeView,
    AttributionView,
    CardDetailView,
    CardTrendOverviewView,
    ChampionMetaView,
    EraView,
    LegendMetaView,
    MetaDeckView,
    MetaStatusView,
    RefreshRunView,
    RefreshStatusView,
    TournamentDetailView,
    TournamentView,
    TrendOverviewView,
)
from ..views import meta_deck_view, tournament_view

router = APIRouter(prefix="/api/meta", tags=["meta"])


def _require_meta(services: Services):
    snapshot = services.meta
    if snapshot is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "No meta snapshot has been built yet. Run: "
                "python -m riftbound.data.meta_pipeline build --promote"
            ),
        )
    return snapshot


@router.get("/status", response_model=MetaStatusView)
def meta_status(services: Services = Depends(get_services)) -> MetaStatusView:
    """Whether meta data exists, and how fresh it is. Never 503s — absence is an answer."""
    snapshot = services.meta
    if snapshot is None:
        return MetaStatusView(
            available=False,
            snapshot_id="",
            created_at="",
            deck_count=0,
            tournament_count=0,
            evidence_counts={},
            warnings=[],
            attribution=[],
        )
    m = snapshot.manifest
    return MetaStatusView(
        available=True,
        snapshot_id=m.snapshot_id,
        created_at=m.created_at,
        deck_count=m.deck_count,
        tournament_count=m.tournament_count,
        evidence_counts=dict(m.evidence_counts),
        warnings=list(m.warnings[:10]),
        attribution=[
            AttributionView(
                source=a.get("source", ""), url=a.get("url", ""), text=a.get("text", "")
            )
            for a in m.attribution
        ],
    )


@router.get("/tournaments", response_model=list[TournamentView])
def list_tournaments(
    limit: int = Query(default=30, ge=1, le=200),
    services: Services = Depends(get_services),
) -> list[TournamentView]:
    snapshot = _require_meta(services)
    return [tournament_view(t) for t in snapshot.tournaments[:limit]]


def _trend_filter(
    snapshot,
    *,
    from_date: str,
    to_date: str,
    format: str,
    min_players: int,
    bucket: str,
    range_: str = "",
) -> TrendFilter:
    """Resolve a window.

    ``range`` -- "all" or a number of days -- is resolved here rather than by the
    client, because a client computing dates has to know the archive's span before it
    can ask for it, and an empty answer falls through to the ninety-day default. That
    is how "All time" quietly became "90 days": the page had not loaded the span yet,
    sent no `from`, and got the default back. The server always knows the span.
    """
    default_from, default_to = default_range(snapshot.tournaments)
    start = parse_date(from_date) if from_date else default_from
    end = parse_date(to_date) if to_date else default_to

    wanted = range_.strip().casefold()
    if wanted and end is not None:
        if wanted == "all":
            span_from, _span_to, _count = archive_span(snapshot.tournaments)
            start = parse_date(span_from) or start
        elif wanted.isdigit() and int(wanted) > 0:
            start = end - timedelta(days=int(wanted) - 1)
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="from and to must be ISO dates")
    if start > end:
        raise HTTPException(status_code=400, detail="from must not be after to")
    if bucket not in ("week", "month"):
        raise HTTPException(status_code=400, detail="bucket must be week or month")
    return TrendFilter(
        from_date=start,
        to_date=end,
        format=format,
        min_players=min_players,
        bucket=bucket,
    )


def _standing_counts(snapshot) -> Counter[str]:
    return Counter(row.tournament_slug for row in snapshot.standings)


@router.get("/trends/overview", response_model=TrendOverviewView)
def trends_overview(
    dimension: str = Query(default="champion", pattern="^(champion|legend|archetype)$"),
    from_date: str = Query(default="", alias="from"),
    to_date: str = Query(default="", alias="to"),
    format: str = Query(default="", max_length=40),
    min_players: int = Query(default=8, ge=0, le=100_000, alias="minPlayers"),
    bucket: str = Query(default="week"),
    range_: str = Query(default="", alias="range", max_length=8),
    limit: int = Query(default=12, ge=1, le=50),
    era: str = Query(default="", max_length=40),
    include_dormant: bool = Query(default=False, alias="includeDormant"),
    services: Services = Depends(get_services),
) -> TrendOverviewView:
    """Share of the field by entity, and how each fared where the sample allows.

    ``era`` scopes the win rates to one banned-list window and defaults to the current
    one. A rate averaged across a ban describes a format nobody is playing, so the
    default is the narrow, correct answer rather than the largest sample. ``era=all``
    opts into the whole archive.

    Presence is *not* era-scoped: the date range already controls that, and silently
    moving the window a caller asked for would make two numbers on one page disagree
    about their own denominator.

    ``includeDormant`` appends the entities the archive knows but this window does not,
    each scored 0 and ordered by what the archive still says about them, so a tier list
    over a short range ranks the whole field rather than dropping part of it. It also
    means ``series`` can exceed ``limit``: the limit bounds the entities with lists, and
    the dormant tail is however long the archive makes it.
    """
    snapshot = _require_meta(services)
    trend_filter = _trend_filter(
        snapshot,
        from_date=from_date,
        to_date=to_date,
        format=format,
        min_players=min_players,
        bucket=bucket,
        range_=range_,
    )
    result = trend_overview(
        decks=snapshot.decks,
        tournaments=snapshot.tournaments,
        standing_count_by_tournament=_standing_counts(snapshot),
        catalog=services.catalog,
        trend_filter=trend_filter,
        dimension=dimension,
        limit=limit,
        standings=snapshot.standings,
        eras=eras_for_format(services.rules_for("constructed")),
        era_id=era,
        include_dormant=include_dormant,
    )
    return TrendOverviewView.model_validate(result, from_attributes=True)


@router.get("/eras", response_model=list[EraView])
def list_eras(services: Services = Depends(get_services)) -> list[EraView]:
    """The banned-list windows a meta statistic can be scoped to, oldest first.

    Served rather than hardcoded in the client for the same reason the rules are: an era
    is data, it changes when the game changes, and a client holding its own copy is a
    second policy that drifts.
    """
    eras = eras_for_format(services.rules_for("constructed"))
    return [
        EraView(
            era_id=era.era_id,
            name=era.name,
            from_date=era.from_date,
            to_date=era.to_date,
            is_open=era.is_open,
            is_cited=era.is_cited,
            evidence=era.evidence,
            bans_introduced=list(era.bans_introduced),
        )
        for era in eras
    ]


@router.get("/trends/champions/{champion_id}", response_model=ChampionMetaView)
def champion_trends(
    champion_id: str,
    from_date: str = Query(default="", alias="from"),
    to_date: str = Query(default="", alias="to"),
    format: str = Query(default="", max_length=40),
    min_players: int = Query(default=8, ge=0, le=100_000, alias="minPlayers"),
    bucket: str = Query(default="week"),
    range_: str = Query(default="", alias="range", max_length=8),
    services: Services = Depends(get_services),
) -> ChampionMetaView:
    snapshot = _require_meta(services)
    result = champion_meta(
        champion_id=champion_id,
        decks=snapshot.decks,
        tournaments=snapshot.tournaments,
        standing_count_by_tournament=_standing_counts(snapshot),
        catalog=services.catalog,
        trend_filter=_trend_filter(
            snapshot,
            from_date=from_date,
            to_date=to_date,
            format=format,
            min_players=min_players,
            bucket=bucket,
            range_=range_,
        ),
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"No tournament data for champion {champion_id!r}")
    return ChampionMetaView.model_validate(result, from_attributes=True)


@router.get("/trends/legends/{legend_id}", response_model=LegendMetaView)
def legend_trends(
    legend_id: str,
    from_date: str = Query(default="", alias="from"),
    to_date: str = Query(default="", alias="to"),
    format: str = Query(default="", max_length=40),
    min_players: int = Query(default=8, ge=0, le=100_000, alias="minPlayers"),
    bucket: str = Query(default="week"),
    range_: str = Query(default="", alias="range", max_length=8),
    services: Services = Depends(get_services),
) -> LegendMetaView:
    snapshot = _require_meta(services)
    result = legend_meta(
        legend_id=legend_id,
        decks=snapshot.decks,
        tournaments=snapshot.tournaments,
        standing_count_by_tournament=_standing_counts(snapshot),
        catalog=services.catalog,
        trend_filter=_trend_filter(
            snapshot,
            from_date=from_date,
            to_date=to_date,
            format=format,
            min_players=min_players,
            bucket=bucket,
            range_=range_,
        ),
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"No tournament data for legend {legend_id!r}")
    return LegendMetaView.model_validate(result, from_attributes=True)


@router.get("/tournaments/{slug:path}", response_model=TournamentDetailView)
def tournament_detail(
    slug: str,
    services: Services = Depends(get_services),
) -> TournamentDetailView:
    snapshot = _require_meta(services)
    result = build_tournament_detail(
        slug=slug,
        tournaments=snapshot.tournaments,
        decks=snapshot.decks,
        catalog=services.catalog,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"No tournament {slug!r}")
    return TournamentDetailView.model_validate(result, from_attributes=True)


def _ranked(services: Services) -> tuple[list[MetaDeck], dict]:
    snapshot = _require_meta(services)
    decks = list(snapshot.decks)
    scores = score_all(decks)
    decks.sort(key=lambda d: scores[d.deck_id].total, reverse=True)
    return decks, scores


#: Orderings `/decks` offers. Rank is the default -- the same "what's actually good"
#: ranking every other meta view leads with -- and recency is the one alternative a
#: player searching by card actually wants: "what's newest running this" answers a
#: different question than "what's best running this", and both are real questions.
DECK_SORTS = ("rank", "recency")

#: A search naming more than this many cards is not narrowing a deck list any more --
#: `_deck_card_ids` intersection against a whole archive per extra card id is cheap, but
#: an unbounded list is still an unbounded request body for no real use case.
MAX_SEARCH_CARDS = 12


def _deck_card_ids(deck: MetaDeck) -> set[str]:
    """Every card this deck is *about*, for matching against a card search.

    `_deck_counts` already covers main, runes, battlefields and the legend; the
    champion is the one card a player searching by card would expect to match that it
    does not otherwise include, since it is not always also a main-deck card.
    """
    ids = set(_deck_counts(deck))
    if deck.deck.champion_id:
        ids.add(deck.deck.champion_id)
    return ids


def _by_recency(deck: MetaDeck) -> str:
    # Same convention as `legend_index` and the scoring recency term: the tournament
    # date when there is a tournament behind the list, the publish date otherwise. ISO
    # strings sort correctly as text, and a deck with neither sorts last, not first.
    return deck.provenance.tournament_date or deck.provenance.published_at


@router.get("/decks", response_model=list[MetaDeckView])
def list_meta_decks(
    archetype: str = Query(default="", max_length=120),
    evidence: str = Query(default="", max_length=32),
    buildable_only: bool = Query(default=False, alias="buildableOnly"),
    card_id: list[str] = Query(default=[], alias="cardId"),
    sort: str = Query(default="rank", pattern="^(rank|recency)$"),
    limit: int = Query(default=30, ge=1, le=200),
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[MetaDeckView]:
    """Ranked meta decks, each scored against what the player can field.

    ``cardId`` narrows to decks running *every* card named (an "and", not an "or" --
    "decks with both of these" is the question a player comparing two cards actually
    has, and it is one query rather than intersecting two separate result sets by hand).
    """
    if evidence and evidence not in EVIDENCE_TIERS:
        raise HTTPException(
            status_code=400, detail=f"evidence must be one of {', '.join(EVIDENCE_TIERS)}"
        )
    if len(card_id) > MAX_SEARCH_CARDS:
        raise HTTPException(
            status_code=400, detail=f"cardId accepts at most {MAX_SEARCH_CARDS} cards."
        )
    wanted = {c.strip().lower() for c in card_id if c.strip()}

    decks, scores = _ranked(services)
    if sort == "recency":
        decks = sorted(decks, key=_by_recency, reverse=True)
    profile = services.availability.load(user_id=identity.user_id)
    catalog = services.catalog

    out: list[MetaDeckView] = []
    for deck in decks:
        if archetype and deck.archetype_id != archetype:
            continue
        if evidence and deck.provenance.evidence != evidence:
            continue
        if wanted and not wanted.issubset(_deck_card_ids(deck)):
            continue
        coverage = deck_coverage(
            _deck_counts(deck), profile=profile, catalog=catalog
        )
        if buildable_only and not coverage.is_complete:
            continue
        out.append(meta_deck_view(deck, scores[deck.deck_id], coverage, catalog))
        if len(out) >= limit:
            break
    return out


@router.get("/archetypes", response_model=list[ArchetypeView])
def list_archetypes(
    limit: int = Query(default=20, ge=1, le=100),
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> list[ArchetypeView]:
    """What is winning, grouped by legend + champion."""
    snapshot = _require_meta(services)
    decks = list(snapshot.decks)
    scores = score_all(decks)
    archetypes = build_archetypes(decks, catalog=services.catalog, scores=totals(scores))
    profile = services.availability.load(user_id=identity.user_id)
    catalog = services.catalog

    out: list[ArchetypeView] = []
    for arch in archetypes[:limit]:
        best = arch.decks[0] if arch.decks else None
        coverage = (
            deck_coverage(_deck_counts(best), profile=profile, catalog=catalog)
            if best
            else None
        )
        out.append(
            ArchetypeView(
                archetype_id=arch.archetype_id,
                name=arch.name,
                legend_id=arch.legend_id,
                champion_id=arch.champion_id,
                deck_count=arch.deck_count,
                tournament_deck_count=arch.tournament_deck_count,
                best_placement=arch.best_placement,
                best_field_size=arch.best_field_size,
                latest_date=arch.latest_date,
                score=round(arch.score, 4),
                best_deck=(
                    meta_deck_view(best, scores[best.deck_id], coverage, catalog)
                    if best and coverage
                    else None
                ),
            )
        )
    return out


@router.get("/decks/{deck_id}", response_model=MetaDeckView)
def get_meta_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> MetaDeckView:
    decks, scores = _ranked(services)
    match = next((d for d in decks if d.deck_id == deck_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No meta deck {deck_id!r}.")
    profile = services.availability.load(user_id=identity.user_id)
    coverage = deck_coverage(_deck_counts(match), profile=profile, catalog=services.catalog)
    return meta_deck_view(match, scores[match.deck_id], coverage, services.catalog)


@router.post("/decks/{deck_id}/import", status_code=201)
def import_meta_deck(
    deck_id: str,
    services: Services = Depends(get_services),
    identity: Identity = Depends(current_identity),
) -> dict:
    """Copy a meta deck into the player's own library, ready to edit.

    The copy records where it came from in its name, so a deck in the library is never
    mistaken for one the player built themselves.
    """
    snapshot = _require_meta(services)
    match = next((d for d in snapshot.decks if d.deck_id == deck_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No meta deck {deck_id!r}.")
    copy = match.deck.with_meta(name=f"{match.deck.name} (imported)")
    new_id = services.decks.save(copy, user_id=identity.user_id)
    return {"deckId": new_id, "name": copy.name, "source": match.provenance.url}


def _deck_counts(deck: MetaDeck) -> dict[str, int]:
    """Every card a deck needs, across zones, for coverage accounting."""
    counts = dict(deck.deck.main)
    for card_id, qty in deck.deck.runes.items():
        counts[card_id] = counts.get(card_id, 0) + qty
    for card_id in deck.deck.battlefields:
        counts[card_id] = counts.get(card_id, 0) + 1
    if deck.deck.legend_id:
        counts[deck.deck.legend_id] = counts.get(deck.deck.legend_id, 0) + 1
    return counts


# -- scheduled refresh --------------------------------------------------------


def _run_view(record) -> RefreshRunView:
    return RefreshRunView(
        started_at=record.started_at,
        finished_at=record.finished_at,
        ok=record.ok,
        promoted=record.promoted,
        snapshot_id=record.snapshot_id,
        deck_count=record.deck_count,
        duration_ms=record.duration_ms,
        message=record.message,
    )


def _scheduler(request: Request):
    scheduler = getattr(request.app.state, "meta_scheduler", None)
    if scheduler is None:
        raise HTTPException(
            status_code=503,
            detail="The refresh scheduler is not running in this process.",
        )
    return scheduler


def _refresh_status(request: Request, services: Services) -> RefreshStatusView:
    scheduler = getattr(request.app.state, "meta_scheduler", None)
    snapshot = services.meta
    age = snapshot_age_hours(snapshot.manifest.created_at) if snapshot else None
    state = scheduler.state if scheduler else None
    interval = state.interval_hours if state else 0.0

    return RefreshStatusView(
        enabled=bool(state and state.enabled),
        status=state.status if state else "off",
        interval_hours=interval,
        next_run_at=state.next_run_at if state else "",
        runs=state.runs if state else 0,
        failures=state.failures if state else 0,
        consecutive_failures=state.consecutive_failures if state else 0,
        snapshot_age_hours=age if age is not None else -1.0,
        # Stale means "older than two refresh intervals": one missed run is a blip, two
        # is a pattern worth showing somebody.
        stale=bool(age is not None and interval and age > interval * 2),
        last_run=_run_view(state.last_run) if state and state.last_run else None,
        history=[_run_view(r) for r in (state.history if state else [])],
    )


@router.get("/refresh", response_model=RefreshStatusView)
def refresh_status(
    request: Request, services: Services = Depends(get_services)
) -> RefreshStatusView:
    """Whether the meta is keeping itself current. Never 503s."""
    return _refresh_status(request, services)


@router.post("/refresh", response_model=RefreshStatusView)
async def refresh_now(
    request: Request, services: Services = Depends(get_services)
) -> RefreshStatusView:
    """Harvest now rather than waiting for the timer.

    The honest answer to "run the meta pipeline" for somebody who is looking at a web
    page and does not want to find a terminal. Returns as soon as the run finishes;
    a concurrent request is told a run is already in flight rather than starting a
    second one.
    """
    scheduler = _scheduler(request)
    record = await scheduler.run_once()
    if record is None:
        raise HTTPException(
            status_code=409,
            detail="A refresh is already running. Check back in a moment.",
        )
    # The snapshot on disk has changed; drop everything derived from the old one.
    reset_services()
    return _refresh_status(request, get_services())


# -- cards --------------------------------------------------------------------


@router.get("/trends/cards", response_model=CardTrendOverviewView)
def card_trend_overview(
    from_date: str = Query(default="", alias="from"),
    to_date: str = Query(default="", alias="to"),
    format: str = Query(default="", max_length=40),
    min_players: int = Query(default=8, ge=0, le=100_000, alias="minPlayers"),
    bucket: str = Query(default="week"),
    range_: str = Query(default="", alias="range", max_length=8),
    card_type: str = Query(default="", max_length=20, alias="cardType"),
    limit: int = Query(default=40, ge=1, le=200),
    services: Services = Depends(get_services),
) -> CardTrendOverviewView:
    """How often the field plays each card, and which way that is moving."""
    snapshot = _require_meta(services)
    result = card_trends(
        decks=snapshot.decks,
        tournaments=snapshot.tournaments,
        catalog=services.catalog,
        trend_filter=_trend_filter(
            snapshot, from_date=from_date, to_date=to_date, format=format,
            min_players=min_players, bucket=bucket, range_=range_,
        ),
        limit=limit,
        card_type=card_type,
    )
    return CardTrendOverviewView.model_validate(result, from_attributes=True)


@router.get("/trends/cards/{card_id}", response_model=CardDetailView)
def card_trend_detail(
    card_id: str,
    from_date: str = Query(default="", alias="from"),
    to_date: str = Query(default="", alias="to"),
    format: str = Query(default="", max_length=40),
    min_players: int = Query(default=8, ge=0, le=100_000, alias="minPlayers"),
    bucket: str = Query(default="week"),
    range_: str = Query(default="", alias="range", max_length=8),
    services: Services = Depends(get_services),
) -> CardDetailView:
    snapshot = _require_meta(services)
    result = card_detail(
        card_id=card_id,
        decks=snapshot.decks,
        tournaments=snapshot.tournaments,
        catalog=services.catalog,
        trend_filter=_trend_filter(
            snapshot, from_date=from_date, to_date=to_date, format=format,
            min_players=min_players, bucket=bucket, range_=range_,
        ),
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No published list in this window plays {card_id!r}. Widen the date "
                "range or lower the minimum event size."
            ),
        )
    return CardDetailView.model_validate(result, from_attributes=True)
