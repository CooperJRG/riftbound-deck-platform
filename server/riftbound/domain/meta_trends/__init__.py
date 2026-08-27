"""Honest, presentation-neutral tournament trend aggregation.

The meta snapshot contains two different populations: every known tournament entrant,
and the much smaller set of entrants whose complete deck list was published. Champion
and archetype claims can only be made about the latter. This package keeps that
distinction explicit so the UI never turns "48 published lists" into "the 2,224-player
field" by accident.

Four modules, split along the lines where the numbers stop meaning the same thing:

* :mod:`common` -- the shared vocabulary. Filters, points, and the decisions that must
  be identical everywhere: what counts as a usable list, what a period is, how confident
  a sample lets us sound. A second opinion about "eligible" is how two pages end up
  quoting different totals for the same window.
* :mod:`entities` -- share of the field by champion, legend or archetype. A *share* here
  partitions: every charted list has one, so they sum to 1.
* :mod:`cards` -- what is being played rather than what is winning. A card's *adoption*
  does not partition, because a list plays forty of them. Kept in its own module so it
  is harder to give the two the same label and then divide one by the other.
* :mod:`dossiers` -- the drill-downs behind a ranking, answering "where did this number
  come from" with placements, pairings and the actual lists.

Everything the rest of the app used to import from the single module is re-exported
here, so this split changed no call sites.
"""

from .cards import (
    CardDetail,
    CardHome,
    CardPartner,
    CardPoint,
    CardTrend,
    CardTrendOverview,
    card_detail,
    card_trends,
)
from .common import (
    HIGH_CONFIDENCE_COVERAGE,
    HIGH_CONFIDENCE_DECKS,
    HIGH_CONFIDENCE_EVENTS,
    MIN_DECKS_FOR_CHART_POINT,
    MIN_DECKS_FOR_MOMENTUM,
    MODERATE_CONFIDENCE_DECKS,
    MODERATE_CONFIDENCE_EVENTS,
    Bucket,
    CardAdoption,
    Dimension,
    EntityTrend,
    Pairing,
    TrendDeck,
    TrendFilter,
    TrendOverview,
    TrendPoint,
    archive_span,
    default_range,
    parse_date,
)
from .dossiers import (
    ChampionMeta,
    LegendMeta,
    TournamentDetail,
    TournamentEntity,
    champion_meta,
    legend_meta,
    tournament_detail,
)
from .entities import overview

__all__ = [
    "HIGH_CONFIDENCE_COVERAGE",
    "HIGH_CONFIDENCE_DECKS",
    "HIGH_CONFIDENCE_EVENTS",
    "MIN_DECKS_FOR_CHART_POINT",
    "MIN_DECKS_FOR_MOMENTUM",
    "MODERATE_CONFIDENCE_DECKS",
    "MODERATE_CONFIDENCE_EVENTS",
    "Bucket",
    "CardAdoption",
    "CardDetail",
    "CardHome",
    "CardPartner",
    "CardPoint",
    "CardTrend",
    "CardTrendOverview",
    "ChampionMeta",
    "Dimension",
    "EntityTrend",
    "LegendMeta",
    "Pairing",
    "TournamentDetail",
    "TournamentEntity",
    "TrendDeck",
    "TrendFilter",
    "TrendOverview",
    "TrendPoint",
    "archive_span",
    "card_detail",
    "card_trends",
    "champion_meta",
    "default_range",
    "legend_meta",
    "overview",
    "parse_date",
    "tournament_detail",
]
