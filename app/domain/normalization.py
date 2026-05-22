from __future__ import annotations

from collections import Counter
from html import unescape
import re


def strip_starter_suffix(text: str) -> str:
    raw = unescape(str(text or "")).strip()
    if not raw:
        return ""
    raw = raw.replace("\u2013", "-").replace("\u2014", "-")
    # First strip trailing parenthetical promo/event suffixes
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw)
    # Then strip trailing starter suffixes
    raw = re.sub(r"\s*[-,]\s*starter\s*$", "", raw, flags=re.IGNORECASE)
    return raw.strip()


def normalize_card_key(text: str) -> str:
    raw = strip_starter_suffix(text)
    if not raw:
        return ""
    # Normalize quote/dash variants and collapse starter suffix aliases.
    raw = raw.replace("\u2019", "'").replace("\u2018", "'").replace("\u2032", "'").replace("\uFF07", "'")
    raw = raw.lower()
    raw = re.sub(r"\s*-\s*", " ", raw)
    raw = re.sub(r"\s*,\s*", " ", raw)
    raw = re.sub(r"[^a-z0-9]+", "", raw)
    return raw


def coerce_quantity(value: object) -> int:
    try:
        num = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return max(0, num)


def coerce_cards_map(raw: object) -> dict[str, int]:
    out: Counter[str] = Counter()
    if isinstance(raw, dict):
        for k, v in raw.items():
            title = str(k or "").strip()
            qty = coerce_quantity(v)
            if title and qty > 0:
                out[title] += qty
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("card") or item.get("name") or "").strip()
            qty = coerce_quantity(item.get("qty") or item.get("quantity") or 0)
            if title and qty > 0:
                out[title] += qty
    return dict(out)


def parse_cards_text_blob(raw: str) -> dict[str, int]:
    out: Counter[str] = Counter()
    for line in str(raw or "").splitlines():
        text = line.strip()
        if not text:
            continue
        m = re.match(r"^(?:(\d+)\s*[xX]\s+|\s*([xX])?\s*(\d+)\s+)?(.+)$", text)
        if not m:
            continue
        qty = 1
        if m.group(1):
            qty = coerce_quantity(m.group(1))
        elif m.group(3):
            qty = coerce_quantity(m.group(3))
        title = str(m.group(4) or "").strip()
        if title and qty > 0:
            out[title] += qty
    return dict(out)


def canonicalize_titles(cards_map: dict[str, int], *, resolve_title) -> dict[str, int]:
    out: Counter[str] = Counter()
    for title, qty in cards_map.items():
        canonical = resolve_title(title)
        if canonical and qty > 0:
            out[canonical] += int(qty)
    return dict(out)
