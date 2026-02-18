from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    app_root: Path
    workspace_root: Path
    cards_path: Path
    meta_index_path: Path
    rules_profile_path: Path
    rules_reference_dir: Path
    db_path: Path
    web_root: Path
    host: str
    port: int


def _resolve_path(value: str, *, base: Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        return raw
    return (base / raw).resolve()


def load_config() -> AppConfig:
    app_root = Path(__file__).resolve().parents[2]
    workspace_root = app_root.parent
    cards_path = _resolve_path(
        os.getenv("RB_CARDS_PATH", str(workspace_root / "riftbound-cards.json")),
        base=workspace_root,
    )
    meta_index_path = _resolve_path(
        os.getenv("RB_META_INDEX_PATH", str(workspace_root / "artifacts" / "meta-deck-index.json")),
        base=workspace_root,
    )
    rules_profile_path = _resolve_path(
        os.getenv("RB_RULE_PROFILE_PATH", str(app_root / "rules_profiles" / "constructed.json")),
        base=app_root,
    )
    rules_reference_dir = _resolve_path(
        os.getenv("RB_RULES_REFERENCE_DIR", str(workspace_root / "rules")),
        base=workspace_root,
    )
    db_path = _resolve_path(
        os.getenv("RB_DB_PATH", str(app_root / "data" / "deck_platform.db")),
        base=app_root,
    )
    web_root = _resolve_path(
        os.getenv("RB_WEB_ROOT", str(app_root / "web")),
        base=app_root,
    )
    host = os.getenv("RB_HOST", "127.0.0.1")
    port = int(os.getenv("RB_PORT", "8010"))
    return AppConfig(
        app_root=app_root,
        workspace_root=workspace_root,
        cards_path=cards_path,
        meta_index_path=meta_index_path,
        rules_profile_path=rules_profile_path,
        rules_reference_dir=rules_reference_dir,
        db_path=db_path,
        web_root=web_root,
        host=host,
        port=port,
    )

