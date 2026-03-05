from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FormatRules:
    format_name: str
    description: str
    source_of_truth: tuple[dict[str, Any], ...]
    constraints: dict[str, Any]
    rule_refs: dict[str, list[str]]

    def refs(self, key: str) -> list[str]:
        return list(self.rule_refs.get(key, []))

    def int_constraint(self, key: str, default: int = 0) -> int:
        try:
            return int(self.constraints.get(key, default))
        except (TypeError, ValueError):
            return default

    def bool_constraint(self, key: str, default: bool = False) -> bool:
        value = self.constraints.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)

    def list_constraint(self, key: str) -> list[str]:
        value = self.constraints.get(key, [])
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return []


def load_format_rules(path: Path) -> FormatRules:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Rule profile at {path} is invalid.")
    return FormatRules(
        format_name=str(raw.get("format") or "constructed"),
        description=str(raw.get("description") or ""),
        source_of_truth=tuple(raw.get("source_of_truth") or []),
        constraints=dict(raw.get("constraints") or {}),
        rule_refs={k: list(v or []) for k, v in dict(raw.get("rule_refs") or {}).items()},
    )


def normalize_format_name(value: str) -> str:
    return str(value or "").strip().lower() or "constructed"


def load_format_rules_map(*, default_profile: Path, profiles_dir: Path | None = None) -> dict[str, FormatRules]:
    loaded: dict[str, FormatRules] = {}
    default_rules = load_format_rules(default_profile)
    loaded[normalize_format_name(default_rules.format_name)] = default_rules

    profile_dir = profiles_dir if profiles_dir is not None else default_profile.parent
    if not profile_dir.is_dir():
        return loaded

    for path in sorted(profile_dir.glob("*.json")):
        try:
            rules = load_format_rules(path)
        except Exception:
            continue
        loaded[normalize_format_name(rules.format_name)] = rules
    return loaded
