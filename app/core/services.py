from __future__ import annotations

from dataclasses import dataclass

from app.core.config import AppConfig, load_config
from app.domain.rules import FormatRules, load_format_rules_map, normalize_format_name
from app.infra.auto_builder_repo import AutoBuilderRepository
from app.infra.cards_repo import CardCatalog, load_card_catalog
from app.infra.meta_repo import MetaDeckRepository
from app.infra.model_observation_repo import ModelObservationRepository
from app.infra.pricing_repo import BaseCardPriceRepository
from app.infra.storage import SqliteStorage
from app.infra.storage_types import StorageProtocol


@dataclass
class AppServices:
    config: AppConfig
    rules: FormatRules
    rules_by_format: dict[str, FormatRules]
    cards: CardCatalog
    storage: StorageProtocol
    meta: MetaDeckRepository
    prices: BaseCardPriceRepository
    auto_builder: AutoBuilderRepository
    model_observation: ModelObservationRepository

    def rules_for_format(self, format_name: str | None) -> FormatRules:
        key = normalize_format_name(str(format_name or ""))
        return self.rules_by_format.get(key, self.rules)

    def available_format_rules(self) -> list[tuple[str, FormatRules]]:
        rows = list(self.rules_by_format.items())
        rows.sort(key=lambda row: (0 if row[0] == normalize_format_name(self.rules.format_name) else 1, row[0]))
        return rows

    def feature_flags(self, *, role: str = "user") -> dict[str, bool]:
        auto_builder_enabled = bool(self.config.auto_builder_enabled)
        try:
            status = self.auto_builder.status()
        except Exception:
            status = {}
        fatal_error = str(status.get("lastError") or "").strip()
        if fatal_error:
            auto_builder_enabled = False
        model_observation_enabled = bool(self.config.model_observation_enabled and str(role or "").strip().lower() == "admin")
        return {
            "autoBuilderEnabled": auto_builder_enabled,
            "modelObservationEnabled": model_observation_enabled,
            "communityGalleryEnabled": True,
        }


_services: AppServices | None = None


def build_services() -> AppServices:
    config = load_config()
    rules_by_format = load_format_rules_map(
        default_profile=config.rules_profile_path,
        profiles_dir=config.rules_profiles_dir,
    )
    rules = rules_by_format.get(normalize_format_name("constructed")) or next(iter(rules_by_format.values()))
    cards = load_card_catalog(config.cards_path)
    if config.storage_backend == "postgres":
        from app.infra.postgres_storage import PostgresStorage

        storage: StorageProtocol = PostgresStorage(config.database_url)
    else:
        storage = SqliteStorage(config.db_path)
    storage.init_schema()
    meta = MetaDeckRepository(config.meta_index_path, cards, rules)
    prices = BaseCardPriceRepository(config.base_card_prices_json_path)
    auto_builder = AutoBuilderRepository(
        config.auto_builder_dir,
        meta=meta,
        cards=cards,
        rules=rules,
        prices=prices,
        enabled=config.auto_builder_enabled,
    )
    model_observation = ModelObservationRepository(
        registry_dir=config.model_registry_dir,
        config=config,
        auto_builder=auto_builder,
    )
    return AppServices(
        config=config,
        rules=rules,
        rules_by_format=rules_by_format,
        cards=cards,
        storage=storage,
        meta=meta,
        prices=prices,
        auto_builder=auto_builder,
        model_observation=model_observation,
    )


def get_services() -> AppServices:
    global _services
    if _services is None:
        _services = build_services()
    return _services
