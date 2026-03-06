from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex


@dataclass(frozen=True)
class AppConfig:
    app_root: Path
    workspace_root: Path
    storage_backend: str
    database_url: str
    cards_path: Path
    meta_index_path: Path
    meta_index_csv_path: Path
    base_card_prices_json_path: Path
    base_card_prices_csv_path: Path
    deck_sources_cache_dir: Path
    meta_refresh_script_path: Path
    meta_refresh_extra_args: tuple[str, ...]
    meta_auto_refresh_enabled: bool
    meta_auto_refresh_interval_sec: int
    meta_auto_refresh_timeout_sec: int
    meta_auto_refresh_run_on_startup: bool
    auto_builder_dir: Path
    model_registry_dir: Path
    auto_builder_enabled: bool
    auto_builder_epochs: int
    model_observation_enabled: bool
    rules_profile_path: Path
    rules_profiles_dir: Path
    rules_reference_dir: Path
    db_path: Path
    web_root: Path
    supabase_url: str
    supabase_anon_key: str
    supabase_jwks_url: str
    supabase_jwt_audience: str
    supabase_service_role_key: str
    allowed_origins: tuple[str, ...]
    sentry_dsn: str
    host: str
    port: int


def _resolve_path(value: str, *, base: Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        return raw
    return (base / raw).resolve()


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(str(raw).strip()) if raw is not None else int(default)
    except ValueError:
        value = int(default)
    return max(minimum, value)


def _env_command_args(name: str) -> tuple[str, ...]:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return ()
    try:
        return tuple(shlex.split(raw, posix=False))
    except ValueError:
        # Fall back to whitespace split when quoting is invalid.
        return tuple(part for part in raw.split() if part)


def _env_list(name: str, *, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    rows = tuple(part.strip() for part in raw.split(",") if part.strip())
    return rows or default


def load_config() -> AppConfig:
    app_root = Path(__file__).resolve().parents[2]
    workspace_root = app_root.parent
    # On Railway (PORT set), default data paths under app_root so deploy bundle is self-contained.
    file_base = app_root if os.getenv("PORT") else workspace_root
    database_url = str(os.getenv("RB_DATABASE_URL", "") or "").strip()
    storage_backend = str(os.getenv("RB_STORAGE_BACKEND", "postgres" if database_url else "sqlite") or "sqlite").strip().lower()
    if storage_backend not in {"sqlite", "postgres"}:
        storage_backend = "sqlite"
    # Cards: default to visible copy in project root (riftbound-cards.json); override with RB_CARDS_PATH.
    default_cards = app_root / "riftbound-cards.json"
    cards_path = _resolve_path(
        os.getenv("RB_CARDS_PATH", str(default_cards)),
        base=app_root,
    )
    meta_index_path = _resolve_path(
        os.getenv("RB_META_INDEX_PATH", str(file_base / "artifacts" / "meta-deck-index.json")),
        base=file_base,
    )
    meta_index_csv_path = _resolve_path(
        os.getenv("RB_META_INDEX_CSV_PATH", str(meta_index_path.with_suffix(".csv"))),
        base=file_base,
    )
    base_card_prices_json_path = _resolve_path(
        os.getenv("RB_BASE_CARD_PRICES_JSON_PATH", str(file_base / "artifacts" / "base-card-prices.json")),
        base=file_base,
    )
    base_card_prices_csv_path = _resolve_path(
        os.getenv("RB_BASE_CARD_PRICES_CSV_PATH", str(file_base / "artifacts" / "base-card-prices.csv")),
        base=file_base,
    )
    deck_sources_cache_dir = _resolve_path(
        os.getenv("RB_DECK_SOURCES_CACHE_DIR", str(file_base / "artifacts" / "deck_sources")),
        base=file_base,
    )
    meta_refresh_script_path = _resolve_path(
        os.getenv("RB_META_REFRESH_SCRIPT_PATH", str(file_base / "scripts" / "refresh_meta_deck_index.py")),
        base=file_base,
    )
    meta_refresh_extra_args = _env_command_args("RB_META_REFRESH_EXTRA_ARGS")
    meta_auto_refresh_enabled = _env_bool("RB_META_AUTO_REFRESH_ENABLED", default=False)
    meta_auto_refresh_interval_sec = _env_int("RB_META_AUTO_REFRESH_INTERVAL_SEC", default=3600, minimum=60)
    meta_auto_refresh_timeout_sec = _env_int("RB_META_AUTO_REFRESH_TIMEOUT_SEC", default=1800, minimum=60)
    meta_auto_refresh_run_on_startup = _env_bool("RB_META_AUTO_REFRESH_RUN_ON_STARTUP", default=False)
    auto_builder_dir = _resolve_path(
        os.getenv("RB_AUTO_BUILDER_DIR", str(file_base / "artifacts" / "auto_builder")),
        base=file_base,
    )
    model_registry_dir = _resolve_path(
        os.getenv("RB_MODEL_REGISTRY_DIR", str(file_base / "artifacts" / "auto_builder_models")),
        base=file_base,
    )
    auto_builder_enabled = _env_bool(
        "RB_ENABLE_AUTO_BUILDER",
        default=_env_bool("RB_AUTO_BUILDER_ENABLED", default=True),
    )
    auto_builder_epochs = _env_int("RB_AUTO_BUILDER_EPOCHS", default=12, minimum=1)
    model_observation_enabled = _env_bool("RB_ENABLE_MODEL_OBSERVATION", default=True)
    rules_profile_path = _resolve_path(
        os.getenv("RB_RULE_PROFILE_PATH", str(app_root / "rules_profiles" / "constructed.json")),
        base=app_root,
    )
    rules_profiles_dir = _resolve_path(
        os.getenv("RB_RULES_PROFILES_DIR", str(app_root / "rules_profiles")),
        base=app_root,
    )
    rules_reference_dir = _resolve_path(
        os.getenv("RB_RULES_REFERENCE_DIR", str(file_base / "rules")),
        base=file_base,
    )
    db_path = _resolve_path(
        os.getenv("RB_DB_PATH", str(app_root / "data" / "deck_platform.db")),
        base=app_root,
    )
    web_root = _resolve_path(
        os.getenv("RB_WEB_ROOT", str(app_root / "web")),
        base=app_root,
    )
    supabase_url = str(os.getenv("RB_SUPABASE_URL", "") or "").strip()
    supabase_anon_key = str(os.getenv("RB_SUPABASE_ANON_KEY", "") or "").strip()
    supabase_jwks_url = str(os.getenv("RB_SUPABASE_JWKS_URL", "") or "").strip()
    supabase_jwt_audience = str(os.getenv("RB_SUPABASE_JWT_AUDIENCE", "authenticated") or "authenticated").strip()
    supabase_service_role_key = str(os.getenv("RB_SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
    allowed_origins = _env_list(
        "RB_ALLOWED_ORIGINS",
        default=("http://127.0.0.1:8010", "http://localhost:8010"),
    )
    sentry_dsn = str(os.getenv("RB_SENTRY_DSN", "") or "").strip()
    host = os.getenv("RB_HOST", "0.0.0.0" if os.getenv("PORT") else "127.0.0.1")
    port = int(os.getenv("PORT") or os.getenv("RB_PORT", "8010"))
    return AppConfig(
        app_root=app_root,
        workspace_root=workspace_root,
        storage_backend=storage_backend,
        database_url=database_url,
        cards_path=cards_path,
        meta_index_path=meta_index_path,
        meta_index_csv_path=meta_index_csv_path,
        base_card_prices_json_path=base_card_prices_json_path,
        base_card_prices_csv_path=base_card_prices_csv_path,
        deck_sources_cache_dir=deck_sources_cache_dir,
        meta_refresh_script_path=meta_refresh_script_path,
        meta_refresh_extra_args=meta_refresh_extra_args,
        meta_auto_refresh_enabled=meta_auto_refresh_enabled,
        meta_auto_refresh_interval_sec=meta_auto_refresh_interval_sec,
        meta_auto_refresh_timeout_sec=meta_auto_refresh_timeout_sec,
        meta_auto_refresh_run_on_startup=meta_auto_refresh_run_on_startup,
        auto_builder_dir=auto_builder_dir,
        model_registry_dir=model_registry_dir,
        auto_builder_enabled=auto_builder_enabled,
        auto_builder_epochs=auto_builder_epochs,
        model_observation_enabled=model_observation_enabled,
        rules_profile_path=rules_profile_path,
        rules_profiles_dir=rules_profiles_dir,
        rules_reference_dir=rules_reference_dir,
        db_path=db_path,
        web_root=web_root,
        supabase_url=supabase_url,
        supabase_anon_key=supabase_anon_key,
        supabase_jwks_url=supabase_jwks_url,
        supabase_jwt_audience=supabase_jwt_audience,
        supabase_service_role_key=supabase_service_role_key,
        allowed_origins=allowed_origins,
        sentry_dsn=sentry_dsn,
        host=host,
        port=port,
    )
