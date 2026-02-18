from __future__ import annotations

from dataclasses import dataclass

from app.core.config import AppConfig, load_config
from app.domain.rules import FormatRules, load_format_rules
from app.infra.cards_repo import CardCatalog, load_card_catalog
from app.infra.meta_repo import MetaDeckRepository
from app.infra.storage import SqliteStorage


@dataclass
class AppServices:
    config: AppConfig
    rules: FormatRules
    cards: CardCatalog
    storage: SqliteStorage
    meta: MetaDeckRepository


_services: AppServices | None = None


def build_services() -> AppServices:
    config = load_config()
    rules = load_format_rules(config.rules_profile_path)
    cards = load_card_catalog(config.cards_path)
    storage = SqliteStorage(config.db_path)
    storage.init_schema()
    meta = MetaDeckRepository(config.meta_index_path, cards, rules)
    return AppServices(
        config=config,
        rules=rules,
        cards=cards,
        storage=storage,
        meta=meta,
    )


def get_services() -> AppServices:
    global _services
    if _services is None:
        _services = build_services()
    return _services
