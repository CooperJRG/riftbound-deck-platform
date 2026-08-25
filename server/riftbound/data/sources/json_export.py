"""Card source: a local JSON export in the dotgg/community shape.

This is the bootstrap source. It reads the flat card export the v2 project used --
one object per printing, with ``slug``, ``title``, ``set``, ``cardNumber`` and so on --
so the rebuild starts from data we already have and can be diffed against later
network sources.

It is also the model for every future adapter: fetch, shape into ``RawCard``, never
raise.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

from .base import CardSource, FetchResult, RawCard


class JsonExportSource(CardSource):
    """Reads a flat array of printing objects from a JSON file."""

    def __init__(self, path: Path, *, name: str = "json-export"):
        self.name = name
        self._path = Path(path)

    def fetch(self) -> FetchResult:
        started = time.perf_counter()
        result = FetchResult(name=self.name)
        try:
            if not self._path.is_file():
                raise FileNotFoundError(f"No card export at {self._path}")
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError(
                    f"{self._path} must contain a JSON array of card objects, "
                    f"got {type(raw).__name__}"
                )
            for row in raw:
                if not isinstance(row, dict):
                    continue
                result.fetched += 1
                result.cards.append(
                    RawCard(
                        source=self.name,
                        slug=str(row.get("slug") or ""),
                        title=str(row.get("title") or ""),
                        set_name=str(row.get("set") or ""),
                        card_number=str(row.get("cardNumber") or row.get("card_number") or ""),
                        rarity=str(row.get("rarity") or ""),
                        promo=bool(row.get("promo")),
                        image_url=str(row.get("imageUrl") or row.get("image_url") or ""),
                        card_type=str(row.get("cardType") or row.get("card_type") or ""),
                        super_type=str(row.get("superType") or row.get("super_type") or ""),
                        color=str(row.get("color") or ""),
                        cost=row.get("cost"),
                        might=row.get("might"),
                        tags=tuple(str(t) for t in (row.get("tags") or []) if str(t).strip()),
                        effect=str(row.get("effect") or ""),
                        flavor=str(row.get("flavor") or ""),
                    )
                )
        except Exception as exc:  # adapters never raise -- see base.CardSource
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result
