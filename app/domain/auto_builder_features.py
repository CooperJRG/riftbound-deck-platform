from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.domain.auto_builder_types import TrainingDeckRow
from app.domain.models import DeckPayload
from app.domain.normalization import normalize_card_key
from app.infra.cards_repo import BASE_DOMAINS, CardCatalog, CardRecord
from app.infra.meta_repo import MetaDeckIndexEntry

_TAG_HINTS = (
    "Bandle City",
    "Bilgewater",
    "Demacia",
    "Freljord",
    "Ionia",
    "Ixtal",
    "Noxus",
    "Piltover",
    "Shadow Isles",
    "Shurima",
    "Targon",
    "Zaun",
    "Void",
)
_EFFECT_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "when",
    "with",
    "you",
    "your",
}
_MAIN_CARD_TYPES = {"Unit", "Gear", "Spell"}


@dataclass(frozen=True)
class CardStaticFeatures:
    title: str
    key: str
    card_type: str
    super_type: str
    domains: tuple[str, ...]
    cost: int
    might: int
    is_unique: bool
    tags: tuple[str, ...]
    effect_tokens: tuple[str, ...]


@dataclass(frozen=True)
class CardTextFeatures:
    keys: tuple[str, ...]
    matrix: np.ndarray
    vectorizer: TfidfVectorizer


def split_compound_tag(tag: str) -> tuple[str, ...]:
    text = str(tag or "").strip()
    if not text:
        return tuple()
    for hint in _TAG_HINTS:
        text = text.replace(hint, f" {hint} ")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = [part.strip() for part in text.split(" ") if part.strip()]
    if not parts:
        return (str(tag).strip(),)
    return tuple(dict.fromkeys(parts))


def tokenize_effect_text(text: str) -> tuple[str, ...]:
    tokens = re.findall(r"[a-zA-Z']+", str(text or "").lower())
    out = [tok for tok in tokens if len(tok) > 2 and tok not in _EFFECT_STOPWORDS]
    return tuple(dict.fromkeys(out))


def deck_signature_from_main(main_by_key: dict[str, int], *, leader_title: str = "", champion_title: str = "") -> str:
    rows = [f"{key}:{int(qty)}" for key, qty in sorted(main_by_key.items()) if int(qty) > 0]
    leader_key = normalize_card_key(leader_title)
    champion_key = normalize_card_key(champion_title)
    if leader_key:
        rows.append(f"legend={leader_key}")
    if champion_key:
        rows.append(f"champion={champion_key}")
    return "|".join(rows)


def legend_domains_for_title(*, cards: CardCatalog, legend_title: str) -> tuple[str, ...]:
    legend = cards.get(legend_title)
    if legend is None:
        return tuple()
    return tuple(sorted(str(domain).strip() for domain in legend.domains if str(domain).strip()))


def shell_id_for_titles(*, cards: CardCatalog, legend_title: str, chosen_champion_title: str) -> str:
    legend_key = normalize_card_key(legend_title)
    champion_key = normalize_card_key(chosen_champion_title)
    domains = legend_domains_for_title(cards=cards, legend_title=legend_title)
    domain_key = ",".join(normalize_card_key(domain) for domain in domains if normalize_card_key(domain))
    return f"{legend_key}|{champion_key}|{domain_key}".strip("|")


def shell_label_for_titles(*, legend_title: str, chosen_champion_title: str) -> str:
    legend = str(legend_title or "").strip()
    champion = str(chosen_champion_title or "").strip()
    if legend and champion:
        return f"{legend} / {champion}"
    return legend or champion or "Unknown Shell"


def sample_weight_for_entry(entry: MetaDeckIndexEntry) -> float:
    source_base = {
        "riot-bologna": 1.30,
        "riot-organized-play": 1.35,
        "mobalytics": 1.10,
        "mobalytics-tournaments": 1.10,
        "riftdecks": 1.15,
        "riftdecks-tournaments": 1.15,
        "riftboundgg": 1.00,
        "piltoverarchive": 0.90,
    }.get(str(entry.source or "").strip().lower(), 1.0)
    age = max(0.0, float(entry.age_days or 0.0))
    age_factor = 1.0 / (1.0 + (age / 45.0))
    meta = max(0.0, min(40.0, float(entry.meta_score or 0.0)))
    meta_factor = 0.85 + (meta / 80.0)
    duplicate_source_count = max(1, int(getattr(entry, "duplicate_source_count", 1) or 1))
    duplicate_factor = 1.10 if duplicate_source_count > 1 else 1.0
    return round(source_base * age_factor * meta_factor * duplicate_factor, 6)


def build_training_rows(entries: Iterable[MetaDeckIndexEntry], *, cards: CardCatalog) -> list[TrainingDeckRow]:
    out: list[TrainingDeckRow] = []
    for entry in entries:
        main_by_key: dict[str, int] = {}
        multiset: list[str] = []
        for title, qty in entry.deck.main.items():
            card = cards.get(title)
            if card is None or card.card_type not in _MAIN_CARD_TYPES:
                continue
            key = normalize_card_key(card.title)
            if not key:
                continue
            count = max(0, int(qty))
            if count <= 0:
                continue
            main_by_key[key] = main_by_key.get(key, 0) + count
            multiset.extend([key] * count)
        if not main_by_key:
            continue
        out.append(
            TrainingDeckRow(
                source=entry.source,
                deck_id=entry.deck_id,
                deck_name=entry.deck_name,
                deck=entry.deck,
                leader_title=entry.leader_title,
                chosen_champion_title=entry.deck.chosen_champion_title,
                main_by_key=main_by_key,
                main_cards_multiset=tuple(multiset),
                meta_score=float(entry.meta_score or 0.0),
                deck_price=entry.deck_price,
                views=entry.views,
                likes=entry.likes,
                age_days=entry.age_days,
                sample_weight=sample_weight_for_entry(entry),
                duplicate_source_count=max(1, int(getattr(entry, "duplicate_source_count", 1) or 1)),
                deck_signature=deck_signature_from_main(
                    main_by_key,
                    leader_title=entry.leader_title,
                    champion_title=entry.deck.chosen_champion_title,
                ),
            )
        )
    return out


def build_main_vocab(rows: Iterable[TrainingDeckRow]) -> tuple[dict[str, int], list[str]]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        for key in sorted(row.main_by_key.keys()):
            if key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return {key: idx for idx, key in enumerate(ordered)}, ordered


def build_card_static_features(cards: CardCatalog, *, vocab_keys: Iterable[str] | None = None) -> dict[str, CardStaticFeatures]:
    allowed = set(vocab_keys or ())
    use_filter = bool(allowed)
    out: dict[str, CardStaticFeatures] = {}
    for card in cards.cards:
        key = normalize_card_key(card.title)
        if not key:
            continue
        if use_filter and key not in allowed:
            continue
        tags: list[str] = []
        for raw_tag in card.tags:
            tags.extend(split_compound_tag(raw_tag))
        out[key] = CardStaticFeatures(
            title=card.title,
            key=key,
            card_type=card.card_type,
            super_type=card.super_type,
            domains=tuple(card.domains),
            cost=int(card.cost or 0),
            might=int(card.might or 0),
            is_unique=bool(card.is_unique),
            tags=tuple(dict.fromkeys(tag for tag in tags if tag)),
            effect_tokens=tokenize_effect_text(card.effect),
        )
    return out


def build_card_text_features(cards: CardCatalog, *, vocab_keys: Iterable[str]) -> CardTextFeatures:
    keys: list[str] = []
    texts: list[str] = []
    for key in vocab_keys:
        card = cards.by_key.get(key)
        if card is None:
            continue
        split_tags: list[str] = []
        for tag in card.tags:
            split_tags.extend(split_compound_tag(tag))
        joined_tags = " ".join(split_tags)
        text = " ".join(
            part for part in [
                card.card_type,
                card.super_type,
                " ".join(card.domains),
                joined_tags,
                str(card.effect or ""),
                str(card.flavor or ""),
                str(card.rarity or ""),
                str(card.set_name or ""),
            ] if part
        )
        keys.append(key)
        texts.append(text)
    vectorizer = TfidfVectorizer(max_features=1024, ngram_range=(1, 2), lowercase=True)
    matrix = vectorizer.fit_transform(texts).toarray().astype(np.float32) if texts else np.zeros((0, 0), dtype=np.float32)
    return CardTextFeatures(keys=tuple(keys), matrix=matrix, vectorizer=vectorizer)


def build_deck_matrix(rows: list[TrainingDeckRow], vocab: dict[str, int]) -> np.ndarray:
    matrix = np.zeros((len(rows), len(vocab)), dtype=np.float32)
    for row_idx, row in enumerate(rows):
        for key, qty in row.main_by_key.items():
            col_idx = vocab.get(key)
            if col_idx is None:
                continue
            matrix[row_idx, col_idx] = float(max(0, int(qty)))
    return matrix


def apply_tfidf_dampening(deck_matrix: np.ndarray, *, sample_weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if deck_matrix.size == 0:
        return deck_matrix.copy(), np.zeros((deck_matrix.shape[1],), dtype=np.float32)
    binary = (deck_matrix > 0).astype(np.float32)
    doc_freq = binary.sum(axis=0)
    idf = np.log((1.0 + float(deck_matrix.shape[0])) / (1.0 + doc_freq)) + 1.0
    weighted = deck_matrix * idf.reshape((1, -1))
    row_scale = sample_weights.reshape((-1, 1)) / max(1e-6, float(sample_weights.mean() or 1.0))
    weighted = weighted * row_scale
    return weighted.astype(np.float32), idf.astype(np.float32)


def mean_embedding_for_main(main_by_key: dict[str, int], card_embeddings: dict[str, np.ndarray], *, dim: int) -> np.ndarray:
    if not main_by_key:
        return np.zeros((dim,), dtype=np.float32)
    total = np.zeros((dim,), dtype=np.float32)
    denom = 0.0
    for key, qty in main_by_key.items():
        vec = card_embeddings.get(key)
        if vec is None:
            continue
        count = float(max(0, int(qty)))
        if count <= 0:
            continue
        total += vec.astype(np.float32) * count
        denom += count
    if denom <= 0:
        return np.zeros((dim,), dtype=np.float32)
    return (total / denom).astype(np.float32)


def deck_cost_curve(main_by_key: dict[str, int], static_features: dict[str, CardStaticFeatures]) -> np.ndarray:
    bins = np.zeros((8,), dtype=np.float32)
    total = 0.0
    for key, qty in main_by_key.items():
        feat = static_features.get(key)
        if feat is None:
            continue
        idx = max(0, min(7, int(feat.cost)))
        bins[idx] += float(max(0, int(qty)))
        total += float(max(0, int(qty)))
    if total > 0:
        bins /= total
    return bins


def deck_domain_balance(main_by_key: dict[str, int], static_features: dict[str, CardStaticFeatures]) -> np.ndarray:
    out = np.zeros((len(BASE_DOMAINS),), dtype=np.float32)
    total = 0.0
    for key, qty in main_by_key.items():
        feat = static_features.get(key)
        if feat is None or not feat.domains:
            continue
        weight = float(max(0, int(qty))) / float(max(1, len(feat.domains)))
        for domain in feat.domains:
            try:
                out[BASE_DOMAINS.index(domain)] += weight
            except ValueError:
                continue
            total += weight
    if total > 0:
        out /= total
    return out


def deck_type_ratios(main_by_key: dict[str, int], static_features: dict[str, CardStaticFeatures]) -> np.ndarray:
    labels = ("Unit", "Gear", "Spell")
    out = np.zeros((len(labels),), dtype=np.float32)
    total = 0.0
    for key, qty in main_by_key.items():
        feat = static_features.get(key)
        if feat is None:
            continue
        try:
            idx = labels.index(feat.card_type)
        except ValueError:
            continue
        count = float(max(0, int(qty)))
        out[idx] += count
        total += count
    if total > 0:
        out /= total
    return out


def deck_special_counts(main_by_key: dict[str, int], static_features: dict[str, CardStaticFeatures]) -> np.ndarray:
    signature = 0.0
    champion = 0.0
    unique_cards = 0.0
    for key, qty in main_by_key.items():
        feat = static_features.get(key)
        if feat is None:
            continue
        count = float(max(0, int(qty)))
        if feat.super_type == "Signature":
            signature += count
        if feat.super_type == "Champion":
            champion += count
        if feat.is_unique:
            unique_cards += count
    return np.array([signature, champion, unique_cards], dtype=np.float32)


def component_confidence(component_vector: np.ndarray) -> float:
    if component_vector.size == 0:
        return 0.0
    ordered = np.sort(component_vector.astype(np.float32))[::-1]
    top = float(ordered[0]) if ordered.size > 0 else 0.0
    second = float(ordered[1]) if ordered.size > 1 else 0.0
    denom = max(1e-6, top + second)
    return max(0.0, min(1.0, (top - second) / denom + 0.5))


def deck_vector(
    *,
    main_by_key: dict[str, int],
    card_embeddings: dict[str, np.ndarray],
    embedding_dim: int,
    win_condition_vector: np.ndarray,
    static_features: dict[str, CardStaticFeatures],
) -> np.ndarray:
    parts = [
        mean_embedding_for_main(main_by_key, card_embeddings, dim=embedding_dim),
        win_condition_vector.astype(np.float32),
        deck_cost_curve(main_by_key, static_features),
        deck_domain_balance(main_by_key, static_features),
        deck_type_ratios(main_by_key, static_features),
        deck_special_counts(main_by_key, static_features),
    ]
    return np.concatenate(parts).astype(np.float32)


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return float(np.dot(left, right) / (left_norm * right_norm))


def legal_main_card_keys_for_legend(*, cards: CardCatalog, legend_title: str) -> set[str]:
    legend = cards.get(legend_title)
    legend_domains = set(legend.domains) if legend is not None else set()
    out: set[str] = set()
    for card in cards.cards:
        if card.card_type not in _MAIN_CARD_TYPES:
            continue
        if legend_domains and (not card.domains or not set(card.domains).issubset(legend_domains)):
            continue
        key = normalize_card_key(card.title)
        if key:
            out.add(key)
    return out


def clamp_copy_limit(card: CardRecord | None, qty: int) -> int:
    if card is None:
        return max(0, int(qty))
    limit = 1 if bool(card.is_unique) else 3
    return max(0, min(limit, int(qty)))


def deck_main_from_payload(deck: DeckPayload, *, cards: CardCatalog) -> dict[str, int]:
    out: dict[str, int] = {}
    for title, qty in deck.main.items():
        card = cards.get(title)
        if card is None or card.card_type not in _MAIN_CARD_TYPES:
            continue
        key = normalize_card_key(card.title)
        if not key:
            continue
        out[key] = out.get(key, 0) + max(0, int(qty))
    return out


def largest_remainder_round(weights: dict[str, float], *, total: int) -> dict[str, int]:
    if total <= 0:
        return {}
    clean = {key: float(value) for key, value in weights.items() if float(value) > 0}
    if not clean:
        return {}
    weight_sum = sum(clean.values())
    if weight_sum <= 0:
        return {}
    raw = {key: (value / weight_sum) * float(total) for key, value in clean.items()}
    base = {key: int(value) for key, value in raw.items()}
    remainder = total - sum(base.values())
    order = sorted(clean.keys(), key=lambda key: (-(raw[key] - base[key]), -clean[key], key))
    for idx in range(max(0, remainder)):
        key = order[idx % len(order)]
        base[key] = base.get(key, 0) + 1
    return {key: qty for key, qty in base.items() if qty > 0}


def pearson_rank_correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_rank = np.argsort(np.argsort(np.array(left, dtype=np.float32))).astype(np.float32)
    right_rank = np.argsort(np.argsort(np.array(right, dtype=np.float32))).astype(np.float32)
    left_centered = left_rank - float(left_rank.mean())
    right_centered = right_rank - float(right_rank.mean())
    denom = float(np.linalg.norm(left_centered) * np.linalg.norm(right_centered))
    if denom <= 0:
        return 0.0
    return float(np.dot(left_centered, right_centered) / denom)
