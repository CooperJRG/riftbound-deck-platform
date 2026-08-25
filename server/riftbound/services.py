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

from dataclasses import dataclass
from functools import cached_property
import logging

from .config import Config, ConfigError, load_config
from .data.bundle import Bundle, load_current
from .domain.cards import Catalog
from .domain.rules import BoundRules, FormatRules, load_format_rules_dir, normalize_format_name
from .infra.db import Database
from .infra.repos import AvailabilityRepository, CollectionRepository, DeckRepository

logger = logging.getLogger("riftbound")

#: The implicit single user in local mode. Real ids arrive with hosted auth.
LOCAL_USER_ID = "local"


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

    def warm(self) -> None:
        """Touch everything required so startup fails loudly, not on first request."""
        self.config.require_files()
        _ = self.bundle
        _ = self.bound_formats
        _ = self.db


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = Services(config=load_config())
    return _services


def reset_services() -> None:
    """Drop the cached container. Used by tests and after promoting a new bundle."""
    global _services
    _services = None
