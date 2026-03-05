from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from app.domain.normalization import normalize_card_key, strip_starter_suffix

BASE_DOMAINS = ("Calm", "Chaos", "Body", "Fury", "Mind", "Order")

# Piltover Archive CDN: artwork when card JSON has no imageUrl (format SET-NUMBER e.g. OGS-001)
PILTOVER_CARD_ART_BASE = "https://cdn.piltoverarchive.com/cards"


def _parse_domains(color: str | None) -> tuple[tuple[str, ...], bool]:
    if not color:
        return tuple(), True
    text = str(color).strip()
    if not text or text.lower() == "colorless":
        return tuple(), True
    cursor = text
    out: list[str] = []
    while cursor:
        matched = False
        for domain in BASE_DOMAINS:
            if cursor.startswith(domain):
                out.append(domain)
                cursor = cursor[len(domain) :]
                matched = True
                break
        if not matched:
            return tuple(), False
    return tuple(sorted(set(out))), True


def _parse_optional_int(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit() or ch == "-")
    if not digits or digits == "-":
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n", ""}:
        return False
    return False


def _infer_champion_tags(tags: tuple[str, ...], known_legend_tags: tuple[str, ...]) -> tuple[str, ...]:
    out: list[str] = []
    lowered = [tag.lower() for tag in tags]
    for legend_tag in known_legend_tags:
        needle = legend_tag.lower()
        if any(needle in raw for raw in lowered):
            out.append(legend_tag)
    return tuple(dict.fromkeys(out))


def _infer_unique_deck_limit(effect: object) -> bool:
    text = str(effect or "").strip().casefold()
    if not text:
        return False
    if "your deck can have only 1 card with this name" in text:
        return True
    return text.startswith("unique")


@dataclass(frozen=True)
class CardRecord:
    title: str
    card_type: str
    super_type: str
    tags: tuple[str, ...]
    champion_tags: tuple[str, ...]
    domains: tuple[str, ...]
    domain_parse_ok: bool
    cost: int | None
    might: int | None
    image_url: str
    is_unique: bool = False
    rarity: str = ""
    set_name: str = ""
    card_number: str = ""
    effect: str = ""
    flavor: str = ""
    promo: bool = False


@dataclass(frozen=True)
class CardCatalog:
    cards: tuple[CardRecord, ...]
    by_title: dict[str, CardRecord]
    by_key: dict[str, CardRecord]

    def get(self, title: str) -> CardRecord | None:
        clean = str(title or "").strip()
        if not clean:
            return None
        direct = self.by_title.get(clean)
        if direct is not None:
            return direct
        key = normalize_card_key(clean)
        if not key:
            return None
        return self.by_key.get(key)

    def resolve_title(self, title: str) -> str:
        clean = strip_starter_suffix(str(title or "").strip())
        card = self.get(clean)
        if card is not None:
            return card.title
        return clean

    def search(self, query: str, *, limit: int = 50) -> list[CardRecord]:
        needle = normalize_card_key(query)
        if not needle:
            return list(self.cards[: max(1, limit)])
        out: list[CardRecord] = []
        for card in self.cards:
            hay = normalize_card_key(card.title)
            if needle in hay:
                out.append(card)
                if len(out) >= max(1, limit):
                    break
        return out


def load_card_catalog(path: Path) -> CardCatalog:
    if not path.is_file():
        return CardCatalog(cards=(), by_title={}, by_key={})
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Card catalog at {path} is invalid.")

    known_legend_tags: list[str] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        if str(row.get("cardType") or "").strip() != "Legend":
            continue
        tags = row.get("tags")
        if not isinstance(tags, list):
            continue
        for tag in tags:
            text = str(tag or "").strip()
            if text:
                known_legend_tags.append(text)
    known_legend_tags = list(dict.fromkeys(known_legend_tags))
    known_legend_tuple = tuple(known_legend_tags)

    cards: list[CardRecord] = []
    by_title: dict[str, CardRecord] = {}
    by_key: dict[str, CardRecord] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        tags_raw = row.get("tags")
        tags = tuple(str(t).strip() for t in tags_raw if str(t).strip()) if isinstance(tags_raw, list) else tuple()
        domains, ok = _parse_domains(str(row.get("color") or "").strip() or None)
        champion_tags = _infer_champion_tags(tags, known_legend_tuple)
        image_url = str(row.get("imageUrl") or row.get("image_url") or "").strip()
        card = CardRecord(
            title=title,
            card_type=str(row.get("cardType") or "").strip(),
            super_type=str(row.get("superType") or "").strip(),
            tags=tags,
            champion_tags=champion_tags,
            domains=domains,
            domain_parse_ok=ok,
            cost=_parse_optional_int(row.get("cost")),
            might=_parse_optional_int(row.get("might")),
            image_url=image_url,
            is_unique=_infer_unique_deck_limit(row.get("effect")),
            rarity=str(row.get("rarity") or "").strip(),
            set_name=str(row.get("set") or "").strip(),
            card_number=str(row.get("cardNumber") or "").strip(),
            effect=str(row.get("effect") or "").strip(),
            flavor=str(row.get("flavor") or "").strip(),
            promo=_parse_bool(row.get("promo")),
        )
        cards.append(card)
        if title not in by_title:
            by_title[title] = card
        key = normalize_card_key(title)
        if key and key not in by_key:
            by_key[key] = card

    return CardCatalog(cards=tuple(cards), by_title=by_title, by_key=by_key)


def card_art_url(card: CardRecord) -> str:
    """Resolved artwork URL: use catalog imageUrl, or Piltover CDN from set + number."""
    if card.image_url and card.image_url.strip():
        return card.image_url.strip()
    set_name = (card.set_name or "").strip()
    card_number = (card.card_number or "").strip()
    if not set_name or not card_number:
        return ""
    # Set code = first token (e.g. "OGS - Proving Grounds" -> "OGS", "SFD" -> "SFD")
    set_code = set_name.split()[0].upper() if set_name.split() else ""
    if not set_code:
        return ""
    # CDN path: SET-NUMBER.webp (e.g. OGS-001, SFD-129)
    return f"{PILTOVER_CARD_ART_BASE}/{set_code}-{card_number}.webp?width=3840"
