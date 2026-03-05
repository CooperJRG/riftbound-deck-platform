from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

from app.domain.normalization import normalize_card_key


def _to_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class BaseCardPriceRepository:
    def __init__(self, path: Path):
        self._path = path
        self._prices_by_key: dict[str, float] = {}
        self._loaded_mtime: float | None = None
        self._last_error: str | None = None
        self.refresh(force=True)

    def refresh(self, *, force: bool = False) -> None:
        if not self._path.is_file():
            self._prices_by_key = {}
            self._loaded_mtime = None
            self._last_error = None
            return
        try:
            mtime = float(self._path.stat().st_mtime)
        except OSError:
            self._prices_by_key = {}
            self._loaded_mtime = None
            self._last_error = None
            return
        if not force and self._loaded_mtime == mtime:
            return

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._last_error = str(exc)
            return
        if not isinstance(raw, list):
            self._last_error = "Price JSON payload must be a list."
            return

        prices_by_key: dict[str, float] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            key = normalize_card_key(title)
            price = _to_float(row.get("price"))
            if not key or price is None or price <= 0:
                continue
            existing = prices_by_key.get(key)
            if existing is None or price < existing:
                prices_by_key[key] = float(price)

        self._prices_by_key = prices_by_key
        self._loaded_mtime = mtime
        self._last_error = None

    def cheapest_price_for_title(self, title: str) -> float | None:
        self.refresh()
        key = normalize_card_key(title)
        if not key:
            return None
        price = self._prices_by_key.get(key)
        if price is None:
            return None
        return float(price)

    @staticmethod
    def tcgplayer_search_url(title: str) -> str:
        clean = str(title or "").strip()
        if not clean:
            return ""
        query = quote_plus(f"{clean} Riftbound")
        return f"https://www.tcgplayer.com/search/all/product?q={query}&view=grid"
