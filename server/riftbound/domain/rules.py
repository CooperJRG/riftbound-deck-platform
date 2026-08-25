"""Format rules, loaded from data and citing the rulebook.

This is the one part of v2 worth keeping verbatim. A format is a JSON profile holding
a ``constraints`` block and a ``rule_refs`` block that maps each constraint to the
sections of the official rules it comes from. Adding a format is adding a file, and
every legality message the player sees can say *why*.

The one change: ban lists are authored as card **names** (a human reads them off a
published list) but resolved to ``card_id`` when bound to a catalogue, and names that
fail to resolve are reported rather than silently ignored -- v2 kept a duplicate
hardcoded ban list in the solver, which is exactly the drift this prevents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cards import Catalog
from .ids import card_id_for


def normalize_format_name(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "-")


@dataclass(frozen=True)
class FormatRules:
    """A format profile as authored on disk."""
    format_name: str
    description: str
    constraints: Mapping[str, Any]
    rule_refs: Mapping[str, Sequence[str]]
    source_path: Path | None = None

    # -- typed constraint access ------------------------------------------------

    def int_constraint(self, key: str, default: int = 0) -> int:
        try:
            return int(self.constraints.get(key, default))
        except (TypeError, ValueError):
            return default

    def bool_constraint(self, key: str, default: bool = False) -> bool:
        value = self.constraints.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def str_constraint(self, key: str, default: str = "") -> str:
        return str(self.constraints.get(key, default) or default).strip()

    def list_constraint(self, key: str) -> tuple[str, ...]:
        value = self.constraints.get(key)
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(v).strip() for v in value if str(v).strip())

    def refs(self, key: str) -> tuple[str, ...]:
        """Rulebook citations for a constraint, e.g. ('CR 103.1', 'TR 402.1')."""
        value = self.rule_refs.get(key)
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(v).strip() for v in value if str(v).strip())

    def bind(self, catalog: Catalog) -> "BoundRules":
        """Resolve name-based constraints against a catalogue."""
        banned: set[str] = set()
        unresolved: list[str] = []
        for name in self.list_constraint("banned_cards"):
            card = catalog.resolve(name)
            if card is None:
                unresolved.append(name)
            else:
                banned.add(card.card_id)
        return BoundRules(
            rules=self,
            banned_card_ids=frozenset(banned),
            unresolved_bans=tuple(unresolved),
        )


@dataclass(frozen=True)
class BoundRules:
    """Format rules resolved against a specific card catalogue."""
    rules: FormatRules
    banned_card_ids: frozenset[str]
    unresolved_bans: tuple[str, ...] = ()

    def __getattr__(self, item: str) -> Any:
        # Delegate constraint accessors so callers can treat this as the rules object.
        return getattr(self.rules, item)

    @property
    def format_name(self) -> str:
        return self.rules.format_name

    def is_banned(self, card_id: str) -> bool:
        return card_id in self.banned_card_ids


def load_format_rules(path: Path) -> FormatRules:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    name = normalize_format_name(raw.get("format") or path.stem)
    if not name:
        raise ValueError(f"{path} has no 'format' name")
    return FormatRules(
        format_name=name,
        description=str(raw.get("description") or ""),
        constraints=dict(raw.get("constraints") or {}),
        rule_refs=dict(raw.get("rule_refs") or {}),
        source_path=Path(path),
    )


def load_format_rules_dir(rules_dir: Path) -> dict[str, FormatRules]:
    """Load every ``*.json`` profile in a directory, keyed by format name."""
    out: dict[str, FormatRules] = {}
    for path in sorted(Path(rules_dir).glob("*.json")):
        profile = load_format_rules(path)
        out[profile.format_name] = profile
    if not out:
        raise FileNotFoundError(f"No format profiles found in {rules_dir}")
    return out
