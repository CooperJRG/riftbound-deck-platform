from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from app.domain.models import DeckPayload, MetaDeckSummary
from app.domain.normalization import coerce_cards_map, normalize_card_key, strip_starter_suffix
from app.domain.rules import FormatRules
from app.domain.validator import validate_deck_for_meta_index
from app.infra.cards_repo import CardCatalog


def _to_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _split_components(
    cards_map: dict[str, int],
    *,
    catalog: CardCatalog,
    leader_title: str,
) -> tuple[str, dict[str, int], dict[str, int], list[str]]:
    legend = catalog.resolve_title(leader_title) if leader_title else ""
    main: dict[str, int] = {}
    runes: dict[str, int] = {}
    battlefields: list[str] = []

    for raw_title, qty in cards_map.items():
        title = catalog.resolve_title(raw_title)
        card = catalog.get(title)
        q = max(0, int(qty))
        if q <= 0:
            continue
        if card is not None and card.card_type == "Legend":
            if not legend:
                legend = title
            continue
        if card is not None and card.card_type == "Rune":
            runes[title] = runes.get(title, 0) + q
            continue
        if card is not None and card.card_type == "Battlefield":
            for _ in range(q):
                battlefields.append(title)
            continue
        main[title] = main.get(title, 0) + q

    return legend, main, runes, battlefields


def _infer_champion(main: dict[str, int], *, legend: str, catalog: CardCatalog) -> str:
    legend_card = catalog.get(legend)
    legend_tags = set(legend_card.champion_tags) if legend_card is not None else set()

    candidates: list[tuple[int, int, str]] = []
    for title, qty in main.items():
        card = catalog.get(title)
        if card is None:
            continue
        if card.card_type != "Unit" or card.super_type != "Champion":
            continue
        tag_match = 1 if legend_tags and (legend_tags & set(card.champion_tags)) else 0
        candidates.append((tag_match, int(qty), title))

    if not candidates:
        return ""
    candidates.sort(key=lambda row: (-row[0], -row[1], row[2].lower()))
    return candidates[0][2]


def _deck_requirement_map(deck: DeckPayload) -> dict[str, int]:
    out: dict[str, int] = {}

    def add(title: str, qty: int) -> None:
        clean = str(title or "").strip()
        count = max(0, int(qty))
        if not clean or count <= 0:
            return
        out[clean] = out.get(clean, 0) + count

    for title, qty in deck.main.items():
        add(title, qty)
    for title, qty in deck.runes.items():
        add(title, qty)
    for title in deck.battlefields:
        add(title, 1)
    for title, qty in deck.sideboard.items():
        add(title, qty)
    if deck.legend_title:
        add(deck.legend_title, 1)
    if deck.chosen_champion_title:
        out[deck.chosen_champion_title] = max(1, out.get(deck.chosen_champion_title, 0))
    return out


def _requirements_by_key(deck: DeckPayload) -> tuple[tuple[str, int], ...]:
    counts_by_key: dict[str, int] = {}
    for title, qty in _deck_requirement_map(deck).items():
        key = normalize_card_key(title)
        if not key:
            continue
        counts_by_key[key] = counts_by_key.get(key, 0) + max(0, int(qty))
    return tuple((key, qty) for key, qty in sorted(counts_by_key.items(), key=lambda row: row[0]) if qty > 0)


@dataclass(frozen=True)
class MetaDeckIndexEntry:
    source: str
    deck_id: str
    deck_name: str
    deck_url: str
    meta_score: float | None
    deck_price: float | None
    views: float | None
    likes: int | None
    age_days: float | None
    leader_title: str
    deck: DeckPayload
    search_key: str
    requirements_by_key: tuple[tuple[str, int], ...]
    total_required: int
    duplicate_source_count: int = 1


class MetaDeckRepository:
    def __init__(self, path: Path, catalog: CardCatalog, rules: FormatRules, *, pool: object | None = None):
        self._path = path
        self._catalog = catalog
        self._rules = rules
        self._pool = pool
        self._entries: list[MetaDeckIndexEntry] = []
        self._query_cache: dict[str, tuple[int, ...]] = {}
        self._raw_row_count = 0
        self._last_refreshed_at: str | None = None
        self._last_refresh_attempt_at: str | None = None
        self._last_error: str | None = None
        self.refresh()

    def _load_rows(self) -> list[dict]:
        if self._pool is not None:
            try:
                from app.infra.postgres_storage import PostgresStorage
                tmp = PostgresStorage.__new__(PostgresStorage)
                tmp._pool = self._pool  # type: ignore[attr-defined]
                rows = tmp.load_meta_deck_rows()
                if rows:
                    return rows
            except Exception:
                pass
        if not self._path.is_file():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []

    def _build_index(self, rows: list[dict]) -> list[MetaDeckIndexEntry]:
        out: list[MetaDeckIndexEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or "").strip()
            deck_id = str(row.get("id") or row.get("deckId") or "").strip()
            deck_name = str(row.get("name") or row.get("deckName") or "").strip() or "Unnamed Deck"
            deck_url = str(row.get("url") or row.get("deckUrl") or "").strip()
            leader_title = strip_starter_suffix(str(row.get("leaderTitle") or "").strip())
            hay = normalize_card_key(f"{source} {deck_name} {leader_title}")

            cards_map = coerce_cards_map(row.get("cards"))
            legend, main, runes, battlefields = _split_components(cards_map, catalog=self._catalog, leader_title=leader_title)
            chosen = _infer_champion(main, legend=legend, catalog=self._catalog)

            deck_payload = DeckPayload(
                name=deck_name,
                source=source or "meta",
                format="constructed",
                legendTitle=legend,
                chosenChampionTitle=chosen,
                main=main,
                runes=runes,
                battlefields=battlefields,
                sideboard={},
            )
            validation = validate_deck_for_meta_index(
                deck_payload,
                rules=self._rules,
                cards=self._catalog,
            )
            if not validation.is_valid:
                continue

            requirements_by_key = _requirements_by_key(deck_payload)
            total_required = sum(qty for _key, qty in requirements_by_key)
            out.append(
                MetaDeckIndexEntry(
                    source=source or "meta",
                    deck_id=deck_id or deck_name,
                    deck_name=deck_name,
                    deck_url=deck_url,
                    meta_score=_to_float(row.get("metaScore") or row.get("meta_score")),
                    deck_price=_to_float(row.get("deckPrice") or row.get("deck_price")),
                    views=_to_float(row.get("views")),
                    likes=_to_int(row.get("likes")),
                    age_days=_to_float(row.get("ageDays") or row.get("age_days")),
                    leader_title=legend or strip_starter_suffix(leader_title),
                    deck=deck_payload,
                    search_key=hay,
                    requirements_by_key=requirements_by_key,
                    total_required=total_required,
                    duplicate_source_count=max(1, _to_int(row.get("duplicateSourceCount")) or 1),
                )
            )
        return out

    def refresh(self) -> dict[str, object]:
        attempt_at = datetime.now(timezone.utc).isoformat()
        self._last_refresh_attempt_at = attempt_at
        try:
            rows = self._load_rows()
            entries = self._build_index(rows)
        except Exception as exc:
            self._last_error = str(exc)
            return self.status()

        self._entries = entries
        self._query_cache = {}
        self._raw_row_count = len(rows)
        self._last_refreshed_at = attempt_at
        self._last_error = None
        return self.status()

    def status(self) -> dict[str, object]:
        return {
            "sourcePath": str(self._path),
            "indexedDecks": len(self._entries),
            "rawRows": int(self._raw_row_count),
            "lastRefreshedAt": self._last_refreshed_at,
            "lastRefreshAttemptAt": self._last_refresh_attempt_at,
            "lastError": self._last_error,
        }

    def search_entries(self, *, query: str = "", limit: int | None = None, offset: int = 0) -> list[MetaDeckIndexEntry]:
        needle = normalize_card_key(query)
        if needle not in self._query_cache:
            if not needle:
                self._query_cache[needle] = tuple(range(len(self._entries)))
            else:
                self._query_cache[needle] = tuple(
                    idx for idx, entry in enumerate(self._entries) if needle in entry.search_key
                )
        matches = self._query_cache[needle]
        start = max(0, int(offset))
        if limit is None:
            window = matches[start:]
        else:
            end = start + max(1, int(limit))
            window = matches[start:end]
        return [self._entries[idx] for idx in window]

    def list_decks(self, *, query: str = "", limit: int = 50, offset: int = 0) -> list[MetaDeckSummary]:
        entries = self.search_entries(query=query, limit=limit, offset=offset)
        return [
            MetaDeckSummary(
                source=entry.source,
                deckId=entry.deck_id,
                deckName=entry.deck_name,
                deckUrl=entry.deck_url,
                metaScore=entry.meta_score,
                deckPrice=entry.deck_price,
                views=entry.views,
                likes=entry.likes,
                ageDays=entry.age_days,
                leaderTitle=entry.leader_title,
                deck=entry.deck,
            )
            for entry in entries
        ]
