"""Application wiring.

Two rules this module exists to enforce:

**Nothing heavy at import time.** v2's ``services.py`` imported the auto-builder,
which did a bare ``import torch`` at module scope, so the documented install --
``pip install -r requirements.txt``, which deliberately excludes torch -- produced an
app that could not start. Optional subsystems here are loaded lazily, behind an
accessor, and their absence is reported rather than fatal.

**One catalogue, loaded once, from the promoted bundle.** The bundle is immutable, so
it can be shared freely and reloaded only when the operator promotes a new one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from functools import cached_property
from typing import TYPE_CHECKING

from .config import Config, ConfigError, load_config
from .data.bundle import Bundle, load_current
from .data.meta_snapshot import MetaSnapshot, load_current_meta, seed_meta_if_missing
from .domain.cards import Catalog
from .domain.legend_index import LegendIndex
from .domain.meta import reattribute_champions
from .domain.meta_trends.performance import Performance
from .domain.rules import BoundRules, FormatRules, load_format_rules_dir, normalize_format_name
from .infra.db import Database

if TYPE_CHECKING:
    from .domain.smart_decks import Engine
from .infra.repos import (
    AvailabilityRepository,
    CollectionRepository,
    DeckRepository,
    SmartDeckRepository,
)

logger = logging.getLogger("riftbound")

#: The implicit single user in local mode. Real ids arrive with hosted auth.
LOCAL_USER_ID = "local"


def _riftools_attribution(snapshot) -> dict[str, str]:
    """The credit owed for the matchup table.

    Read off the promoted snapshot's manifest when it carries one: the credit belongs to
    the data, and a snapshot promoted months ago should keep crediting whoever it
    actually came from even if the ingest code moves on.

    Falls back to the source module's own credit, because the table no longer has to
    come from a snapshot at all -- it may have been fetched straight into the matchup
    store, and a credit that quietly disappeared when the data took the newer path would
    be the one failure mode attribution cannot have.
    """
    if snapshot is not None:
        for entry in snapshot.manifest.attribution:
            if str(entry.get("source", "")).lower() == "riftools":
                return dict(entry)
    from .data.sources.riftools import ATTRIBUTION

    return dict(ATTRIBUTION)


@dataclass
class Services:
    config: Config

    @cached_property
    def bundle(self) -> Bundle:
        bundle = load_current(self.config.bundles_dir)
        logger.info(
            "loaded card bundle %s (%d cards, %d printings)",
            bundle.manifest.bundle_id,
            bundle.manifest.card_count,
            bundle.manifest.printing_count,
        )
        return bundle

    @property
    def catalog(self) -> Catalog:
        return self.bundle.catalog

    @cached_property
    def formats(self) -> dict[str, FormatRules]:
        return load_format_rules_dir(self.config.rules_dir)

    @cached_property
    def bound_formats(self) -> dict[str, BoundRules]:
        bound: dict[str, BoundRules] = {}
        for name, profile in self.formats.items():
            rules = profile.bind(self.catalog)
            if rules.unresolved_bans:
                logger.warning(
                    "format %s: %d banned card name(s) do not match any card: %s",
                    name, len(rules.unresolved_bans), ", ".join(rules.unresolved_bans),
                )
            bound[name] = rules
        return bound

    def rules_for(self, format_name: str | None) -> BoundRules:
        key = normalize_format_name(format_name or "constructed")
        rules = self.bound_formats.get(key)
        if rules is None:
            available = ", ".join(sorted(self.bound_formats))
            raise ConfigError(f"Unknown format {key!r}. Available formats: {available}")
        return rules

    @cached_property
    def meta(self) -> MetaSnapshot | None:
        """The promoted meta snapshot, or None.

        Optional by design: the deck builder must work with no meta data at all, so a
        source outage degrades the meta view and nothing else. A corrupt snapshot is
        logged and treated as absent rather than taking the app down.
        """
        try:
            snapshot = load_current_meta(self.config.meta_dir)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("meta snapshot unreadable, continuing without it: %s", exc)
            return None
        if snapshot is not None:
            logger.info(
                "loaded meta snapshot %s (%d decks, %d tournaments)",
                snapshot.manifest.snapshot_id,
                snapshot.manifest.deck_count,
                snapshot.manifest.tournament_count,
            )
        if snapshot is not None:
            # Correct any deck credited to a champion its legend could never have
            # nominated. Done here rather than only in the normaliser because a harvest
            # carries forward every deck the sources no longer return -- most of the
            # archive -- so a normaliser fix would never reach them.
            fixed = reattribute_champions(snapshot.decks, self.catalog)
            changed = sum(
                1 for before, after in zip(snapshot.decks, fixed, strict=True)
                if before.deck.champion_id != after.deck.champion_id
            )
            if changed:
                logger.info("re-attributed the chosen champion on %d deck(s)", changed)
                snapshot = replace(snapshot, decks=tuple(fixed))
        return snapshot

    @cached_property
    def matchups(self):
        """The legend matchup table, resolved against the current bundle.

        Built once and cached, like every other derived meta view: it is a resolve and a
        threshold pass over ~1,700 rows, and the Explore view asks for it on every load.

        Empty rather than absent when the snapshot carries no matrix -- a snapshot
        written before matchups existed, a build run with ``--no-matchups``, or a
        harvest whose win-rate fetch failed with nothing to carry forward. The view
        renders "no matchup data yet" from an empty table, so there is one shape to
        handle rather than two.
        """
        from .data.matchup_store import load_matchups
        from .domain.matchups import MatchupBasis, MatchupTable, build_matchups

        empty = MatchupTable(
            basis=MatchupBasis(
                source_label="", attribution={}, set_window="", published_at="",
                events=0, matrix_matches=0, eligible_matches=0,
                legends_measured=0, legends_shown=0,
                cells_measured=0, cells_shown=0,
            )
        )

        # The store first, the snapshot second. The store is refreshed on its own cheap
        # cadence; the snapshot copy only moves when the whole deck pipeline runs, which
        # in hosted mode is never. Reading the snapshot first would pin the table to the
        # slower of the two -- which is exactly the bug this ordering fixes.
        snapshot = self.meta
        stored = load_matchups(self.config.matchups_dir)
        if stored is not None:
            cells = stored.get("cells") or []
            legend_rows = stored.get("legends") or []
            meta = stored.get("meta") or {}
        elif snapshot is not None and snapshot.matchups:
            cells = list(snapshot.matchups)
            legend_rows = list(snapshot.matchup_legends)
            meta = snapshot.matchup_meta or {}
        else:
            return empty

        table, notes = build_matchups(
            cells=cells,
            legends=legend_rows,
            catalog=self.catalog,
            source_label=str(meta.get("sourceLabel") or ""),
            attribution=_riftools_attribution(snapshot),
            set_window=str(meta.get("setWindow") or ""),
            published_at=str(meta.get("publishedAt") or ""),
            events=int(meta.get("events") or 0),
            matrix_matches=int(meta.get("matrixMatches") or 0),
            eligible_matches=int(meta.get("eligibleMatches") or 0),
        )
        for note in notes:
            logger.warning("matchups: %s", note)
        logger.info(
            "built matchup table: %d legend(s), %d cell(s), %d rated",
            table.basis.legends_measured, table.basis.cells_measured,
            table.basis.cells_shown,
        )
        return table

    def refresh_matchups(self, *, force: bool = False) -> bool:
        """Fetch the matchup table into its own store, if it is stale.

        One request, so this is cheap enough to run on every boot -- which is the point.
        It is deliberately **not** tied to ``meta_refresh``: that flag governs a crawl
        of one request per decklist and is off in hosted mode by design, and leaving the
        matchup table behind it meant the live site never had one at all.

        Returns whether the store was written. Every failure is swallowed and logged:
        the table is an enhancement, and a source outage must degrade it rather than
        taking down a boot or a request.
        """
        from .data.matchup_store import age_hours, write_matchups
        from .data.sources.riftools_winrates import RiftoolsWinratesSource
        from .domain.matchups import symmetry_errors

        if not self.config.matchup_refresh and not force:
            return False
        age = age_hours(self.config.matchups_dir)
        if not force and 0 <= age < self.config.matchup_refresh_hours:
            logger.debug("matchup table is %.1fh old; not refetching", age)
            return False

        try:
            fetched = RiftoolsWinratesSource().fetch()
        except Exception as exc:  # the source already swallows; belt and braces
            logger.warning("matchup refresh failed: %s", exc)
            return False
        if not fetched.ok or not fetched.cells:
            logger.warning(
                "matchup refresh failed: %s", fetched.error or "no cells returned"
            )
            return False

        problems = symmetry_errors(fetched.cells)
        if problems:
            # Refused for the same reason the pipeline refuses it: a matrix that does
            # not mirror no longer means what this code believes it means.
            logger.warning(
                "matchup table refused, %d asymmetric cell(s): %s",
                len(problems), problems[0],
            )
            return False

        try:
            write_matchups(
                self.config.matchups_dir,
                cells=fetched.cells,
                legends=fetched.legends,
                meta={
                    "sourceLabel": fetched.source_label,
                    "setWindow": fetched.set_window,
                    "publishedAt": fetched.published_at,
                    "events": fetched.event_count,
                    "matrixMatches": fetched.matrix_matches,
                    "eligibleMatches": fetched.eligible_matches,
                },
            )
        except OSError as exc:
            logger.warning("could not write the matchup store: %s", exc)
            return False

        # The derived table is cached on this container; drop it so the next read picks
        # up what was just written rather than serving the old one until a restart.
        self.__dict__.pop("matchups", None)
        self.__dict__.pop("field_outlooks", None)
        logger.info(
            "matchup table refreshed: %d cells, %d legends, %d matches over %d events",
            len(fetched.cells), len(fetched.legends),
            fetched.matrix_matches, fetched.event_count,
        )
        return True

    @cached_property
    def field_outlooks(self) -> dict:
        """Every legend's position in the field, keyed by legend id.

        One pass over the matchup table, cached: the legend picker asks for all of them
        at once and the builder asks for one on every deck change. Empty without a
        matchup table, which is a supported state everywhere it is read.
        """
        from .domain.field_plan import rank_by_field

        table = self.matchups
        if not table.available:
            return {}
        return rank_by_field(
            [r.legend_id for r in table.records], table=table, catalog=self.catalog
        )

    @cached_property
    def champion_performance(self) -> tuple[Performance, ...]:
        """Win rates by champion, over the whole archive and current era.

        Computed once and cached: it is one pass over the standings, and the builder
        asks for it on every keystroke that changes the deck. Empty when there is no
        snapshot, which is a supported state -- the builder works with no meta data at
        all, and a champion list without win rates is still a champion list.
        """
        snapshot = self.meta
        if snapshot is None:
            return ()
        from datetime import date

        from .domain.eras import eras_for_format
        from .domain.meta_trends.common import TrendFilter
        from .domain.meta_trends.performance import performance

        table = performance(
            decks=snapshot.decks,
            tournaments=snapshot.tournaments,
            standings=snapshot.standings,
            catalog=self.catalog,
            trend_filter=TrendFilter(from_date=date.min, to_date=date.max),
            eras=eras_for_format(self.rules_for("constructed")),
            dimension="champion",
        )
        return table.ranked()

    @cached_property
    def db(self) -> Database:
        db = Database(self.config.db_path)
        applied = db.migrate()
        if applied:
            logger.info("applied migrations: %s", ", ".join(applied))
        if self.config.is_local:
            db.ensure_user(LOCAL_USER_ID, "You")
        return db

    @cached_property
    def decks(self) -> DeckRepository:
        return DeckRepository(self.db)

    @cached_property
    def collections(self) -> CollectionRepository:
        return CollectionRepository(self.db)

    @cached_property
    def availability(self) -> AvailabilityRepository:
        return AvailabilityRepository(self.db, self.collections)

    @cached_property
    def smart_decks(self) -> SmartDeckRepository:
        return SmartDeckRepository(self.db)

    @cached_property
    def deck_scores(self) -> dict[str, float]:
        """Meta deck scores, keyed by deck id. Empty without a snapshot."""
        from .domain.meta_scoring import score_all, totals

        if self.meta is None:
            return {}
        return totals(score_all(self.meta.decks))

    @cached_property
    def legend_index(self) -> LegendIndex:
        """Per-legend meta summaries, built once, **scoped to the current format era**.

        Derived from the snapshot rather than stored: it is a pure function of data we
        already have, and a cache that can disagree with its source is a bug waiting to
        be filed. Measured at 0.14s for 3,322 decks, which is cheap enough to pay on
        first use and forget about.

        The era scope is the point. Built over the whole archive this index averaged two
        formats -- a third of the decks predate the March 2026 bans -- and the builder
        handed the player that average. See :func:`legend_index.build_scoped_index` for
        the measurements, and ``deck_fidelity`` for the gate that guards it.
        """
        from .domain.eras import eras_for_format
        from .domain.legend_index import build_scoped_index

        if self.meta is None:
            return LegendIndex(profiles={})
        era = eras_for_format(self.rules_for("constructed")).current
        return build_scoped_index(self.meta.decks, self.deck_scores, era)

    @cached_property
    def deck_scoreboard(self):
        """Baselines for the two deck-strength scores, over the current-era field.

        The meta denominator is format-wide; the second denominator contains every
        published list for the legend, regardless of chosen champion. That keeps a
        rarely played champion from creating an artificially easy 100.
        """
        from .domain.eras import eras_for_format
        from .domain.meta_scoring import score_all, totals
        from .domain.smart_decks.scoring import build_scoreboard

        if self.meta is None:
            return build_scoreboard([], {})
        era = eras_for_format(self.rules_for("constructed")).current
        current = [
            deck for deck in self.meta.decks
            if era.contains(deck.provenance.tournament_date or deck.provenance.published_at)
        ]
        return build_scoreboard(current, totals(score_all(current)))

    def engine_for(self, legend_id: str) -> Engine | None:
        """A wizard engine bound to one legend, or None if the meta knows nothing of it."""
        from .domain.smart_decks import Engine

        profile = self.legend_index.get(legend_id)
        if profile is None or self.meta is None:
            return None
        decks = {
            deck.deck_id: deck
            for deck in self.meta.decks
            if deck.deck.legend_id == legend_id
        }
        return Engine(
            catalog=self.catalog,
            rules=self.rules_for("constructed"),
            profile=profile,
            decks=decks,
            scores=self.deck_scores,
            scoreboard=self.deck_scoreboard,
        )

    def unusable_bundle(self) -> str:
        """Why the promoted bundle cannot support the app, or "" if it can.

        The format profile names the card types a legal deck is made of. If the
        catalogue contains none of one of them, no deck can be built, nothing validates,
        and the deck builder is furniture -- whatever the cause.

        Checked by *type presence* rather than by looking for a known defect, so this
        catches the next shape change as well as the one that prompted it: upstream
        turned `type` into a list, the adapter stringified it, and every card's type
        became "['Unit']". Every rule silently stopped matching and the promoted bundle
        looked perfectly healthy -- right card count, right names, no errors.
        """
        try:
            rules = self.rules_for("constructed")
        except ConfigError:
            return ""  # a missing profile is a different failure, reported elsewhere
        required = {
            "runes": rules.str_constraint("rune_card_type", "Rune"),
            "battlefields": rules.str_constraint("battlefield_card_type", "Battlefield"),
            "legends": rules.str_constraint("legend_card_type", "Legend"),
        }
        missing = [
            f"{label} ({wanted!r})"
            for label, wanted in required.items()
            if wanted and not any(card.is_type(wanted) for card in self.catalog)
        ]
        if not missing:
            return ""
        sample = ", ".join(sorted({c.card_type for c in self.catalog if c.card_type})[:6])
        return (
            f"the promoted bundle has no {', no '.join(missing)}. "
            f"Card types present look like: {sample or '(none)'}"
        )

    def _rebuild_bundle(self) -> bool:
        """Rebuild and promote the card bundle from upstream. True if it now looks usable.

        Startup only, and only when the promoted bundle is already unusable -- at which
        point the site is down regardless, so a couple of seconds and one upstream
        request is the cheap option. The alternative is what actually happened: correct
        code shipped, the volume kept the damaged bundle, and the entrypoint skipped the
        rebuild because a bundle "was present".
        """
        from .data.pipeline import main as pipeline_main

        logger.error("card bundle unusable — rebuilding from upstream")
        try:
            code = pipeline_main(["build", "--promote"])
        except Exception as exc:
            logger.error("bundle rebuild failed: %s", exc)
            return False
        if code != 0:
            logger.error("bundle rebuild exited %s", code)
            return False
        # Drop everything derived from the bundle we just replaced.
        for key in ("bundle", "bound_formats", "formats"):
            self.__dict__.pop(key, None)
        return not self.unusable_bundle()

    def warm(self) -> None:
        """Touch everything required so startup fails loudly, not on first request."""
        self.config.require_files()
        _ = self.bundle
        _ = self.bound_formats
        _ = self.db

        # A bundle can be present, well-formed and still unusable. Self-heal once rather
        # than serving a catalogue in which nothing is a rune.
        problem = self.unusable_bundle()
        if problem:
            logger.error("%s", problem)
            if self._rebuild_bundle():
                logger.info("rebuilt card bundle %s", self.bundle.manifest.bundle_id)
            else:
                logger.error(
                    "card bundle is still unusable after a rebuild. The app will start, "
                    "but deck building and Smart Decks will not work until this is fixed."
                )
        # Fills a cold database from the snapshot committed at data/meta-seed, so
        # Explore and Smart Decks have real content on the very first request rather
        # than an empty screen until the first live harvest lands. A no-op once
        # anything real has been promoted, so this only ever does something once.
        self.config.meta_dir.mkdir(parents=True, exist_ok=True)
        seed_meta_if_missing(self.config.meta_dir, self.config.root / "data" / "meta-seed")


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = Services(config=load_config())
    return _services


def reset_services() -> None:
    """Drop the cached container. Used by tests and after promoting a new bundle.

    Also clears the identity layer's record of which visitor rows it has written. That
    cache describes the database this container holds, so it has to die with it --
    otherwise a rebuilt database keeps being told a row exists that it no longer has,
    and the next save fails on a foreign key.
    """
    global _services
    _services = None
    # Imported here: identity imports from this module, so a top-level import would
    # close the cycle.
    from .api.identity import forget_known_users

    forget_known_users()
