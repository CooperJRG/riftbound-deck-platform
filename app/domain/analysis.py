from __future__ import annotations

from collections import Counter
import re

from app.domain.models import (
    CardNeed,
    CardReplacementSuggestion,
    DeckAnalysisResult,
    DeckPayload,
    ReplacementOption,
)
from app.domain.normalization import normalize_card_key
from app.infra.cards_repo import CardCatalog, CardRecord

MAIN_DECK_TYPES = {"Unit", "Gear", "Spell"}
_STOPWORDS = {
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


def _deck_requirement_map(deck: DeckPayload) -> dict[str, int]:
    req = Counter({k: max(0, int(v)) for k, v in deck.main.items() if int(v) > 0})
    if deck.legend_title:
        req[deck.legend_title] += 1
    if deck.chosen_champion_title:
        req[deck.chosen_champion_title] = max(1, req.get(deck.chosen_champion_title, 0))
    for title, qty in deck.runes.items():
        q = max(0, int(qty))
        if q > 0:
            req[title] += q
    for title in deck.battlefields:
        t = str(title or "").strip()
        if t:
            req[t] += 1
    for title, qty in deck.sideboard.items():
        q = max(0, int(qty))
        if q > 0:
            req[title] += q
    return dict(req)


def _is_main_replacement_target(title: str, deck: DeckPayload, cards: CardCatalog) -> bool:
    if title not in deck.main:
        return False
    if title == deck.chosen_champion_title:
        return False
    card = cards.get(title)
    if card is None:
        return False
    if card.card_type not in MAIN_DECK_TYPES:
        return False
    if card.super_type == "Champion":
        return False
    return True


def _is_legal_candidate_for_legend(card: CardRecord, *, legend_domains: set[str]) -> bool:
    if card.card_type not in MAIN_DECK_TYPES:
        return False
    if card.super_type in {"Champion", "Signature"}:
        return False
    if legend_domains:
        if not card.domains:
            return False
        if not set(card.domains).issubset(legend_domains):
            return False
    return True


def _effect_tokens(effect: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z']+", str(effect or "").lower())
    return {tok for tok in tokens if len(tok) > 2 and tok not in _STOPWORDS}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    denom = len(left.union(right))
    if denom <= 0:
        return 0.0
    return len(left.intersection(right)) / float(denom)


def _legacy_similarity(source: CardRecord, candidate: CardRecord) -> tuple[float, str]:
    if source.card_type != candidate.card_type:
        return 0.0, "card type mismatch"
    if source.card_type not in MAIN_DECK_TYPES:
        return 0.0, "unsupported source card type"
    # Champion units are identity-locked.
    if source.super_type == "Champion" and source.super_type != candidate.super_type:
        return 0.0, "critical supertype mismatch"
    # Missing signature cards should map to regular cards, not other signatures.
    if source.super_type == "Signature" and candidate.super_type == "Signature":
        return 0.0, "signature-to-signature replacement is disallowed"

    total = 0.0
    reasons: list[str] = []

    if source.super_type and source.super_type == candidate.super_type:
        total += 2.0
        reasons.append(f"same supertype ({source.super_type})")

    domain_j = _jaccard(set(source.domains), set(candidate.domains))
    total += 2.0 * domain_j
    if domain_j > 0:
        reasons.append("domain overlap")

    tag_j = _jaccard(set(source.tags), set(candidate.tags))
    total += 1.5 * tag_j
    if tag_j > 0:
        reasons.append("tag overlap")

    effect_j = _jaccard(_effect_tokens(source.effect), _effect_tokens(candidate.effect))
    total += 1.5 * effect_j
    if effect_j > 0:
        reasons.append("effect overlap")

    if source.cost is not None and candidate.cost is not None:
        delta = min(5.0, float(abs(source.cost - candidate.cost)))
        total += 1.25 * (1.0 - delta / 5.0)
        if delta <= 1:
            reasons.append("similar cost")

    if source.might is not None and candidate.might is not None:
        delta = min(6.0, float(abs(source.might - candidate.might)))
        total += 0.75 * (1.0 - delta / 6.0)
        if delta <= 1:
            reasons.append("similar might")

    return total, ", ".join(reasons) if reasons else "same role"


def _replacement_score(
    target: CardRecord,
    candidate: CardRecord,
    *,
    available: int,
    legend_domains: tuple[str, ...],
) -> tuple[float, str]:
    base_score, reason = _legacy_similarity(target, candidate)
    if base_score <= 0:
        return 0.0, reason

    legend_domain_set = set(legend_domains)
    cand_domains = set(candidate.domains)
    in_identity = not legend_domain_set or (bool(cand_domains) and cand_domains.issubset(legend_domain_set))

    score = base_score
    if in_identity:
        score += 1.5

    if len(legend_domains) >= 2:
        domain_a, domain_b = legend_domains[0], legend_domains[1]
        has_a = domain_a in cand_domains
        has_b = domain_b in cand_domains
        if has_a and has_b:
            score += 1.0
        elif has_a or has_b:
            score += 0.75
    elif legend_domains and cand_domains:
        score += 0.5

    # Prefer options that can cover more missing copies from collection.
    score += min(3.0, float(available) * 0.8)

    return score, reason


def _domain_bucket_key(card: CardRecord, domain_a: str, domain_b: str) -> str:
    domains = set(card.domains)
    has_a = domain_a in domains
    has_b = domain_b in domains
    if has_a and has_b:
        return "both"
    if has_a:
        return "a"
    if has_b:
        return "b"
    return "other"


def _select_balanced_options(
    ranked: list[tuple[float, str, ReplacementOption, CardRecord]],
    *,
    legend_domains: tuple[str, ...],
    max_items: int = 3,
) -> list[ReplacementOption]:
    if not ranked:
        return []
    if len(legend_domains) < 2:
        return [row[2] for row in ranked[:max_items]]

    domain_a, domain_b = legend_domains[0], legend_domains[1]
    bucket_a: list[tuple[float, str, ReplacementOption, CardRecord]] = []
    bucket_b: list[tuple[float, str, ReplacementOption, CardRecord]] = []
    bucket_both: list[tuple[float, str, ReplacementOption, CardRecord]] = []
    bucket_other: list[tuple[float, str, ReplacementOption, CardRecord]] = []

    for row in ranked:
        key = _domain_bucket_key(row[3], domain_a, domain_b)
        if key == "a":
            bucket_a.append(row)
        elif key == "b":
            bucket_b.append(row)
        elif key == "both":
            bucket_both.append(row)
        else:
            bucket_other.append(row)

    picked: list[tuple[float, str, ReplacementOption, CardRecord]] = []
    if bucket_a and bucket_b:
        # Ensure both legend domains are represented when possible.
        if bucket_a[0][0] >= bucket_b[0][0]:
            picked.append(bucket_a.pop(0))
            picked.append(bucket_b.pop(0))
        else:
            picked.append(bucket_b.pop(0))
            picked.append(bucket_a.pop(0))
    elif bucket_a and bucket_both:
        picked.append(bucket_a.pop(0))
        picked.append(bucket_both.pop(0))
    elif bucket_b and bucket_both:
        picked.append(bucket_b.pop(0))
        picked.append(bucket_both.pop(0))

    remaining = bucket_a + bucket_b + bucket_both + bucket_other
    remaining.sort(key=lambda row: (-row[0], row[1]))
    while len(picked) < max_items and remaining:
        picked.append(remaining.pop(0))

    return [row[2] for row in picked[:max_items]]


def _build_replacement_suggestions(
    *,
    deck: DeckPayload,
    cards: CardCatalog,
    requirements: dict[str, int],
    collection_by_key: dict[str, int],
    missing_cards: list[CardNeed],
) -> list[CardReplacementSuggestion]:
    legend = cards.get(deck.legend_title) if deck.legend_title else None
    legend_domains_tuple = tuple(legend.domains) if legend is not None else tuple()
    legend_domains = set(legend_domains_tuple)
    out: list[CardReplacementSuggestion] = []

    for missing in missing_cards:
        title = missing.card
        if not _is_main_replacement_target(title, deck, cards):
            continue
        target = cards.get(title)
        if target is None:
            continue

        options_scored: list[tuple[float, str, ReplacementOption, CardRecord]] = []
        for candidate in cards.cards:
            if candidate.title == title:
                continue
            if candidate.card_type != target.card_type:
                continue
            if not _is_legal_candidate_for_legend(candidate, legend_domains=legend_domains):
                continue
            c_key = normalize_card_key(candidate.title)
            if not c_key:
                continue
            owned = max(0, int(collection_by_key.get(c_key, 0)))
            required_elsewhere = max(0, int(requirements.get(candidate.title, 0)))
            available_from_collection = max(0, owned - required_elsewhere)
            copy_cap = 1 if candidate.is_unique else 3
            legal_slots = max(0, copy_cap - required_elsewhere)
            available = min(available_from_collection, legal_slots)
            if available <= 0:
                continue
            score, _reason = _replacement_score(
                target,
                candidate,
                available=available,
                legend_domains=legend_domains_tuple,
            )
            if score <= 0:
                continue
            options_scored.append(
                (
                    score,
                    candidate.title.casefold(),
                    ReplacementOption(
                        card=candidate.title,
                        owned=owned,
                        available=available,
                        score=round(score, 2),
                    ),
                    candidate,
                )
            )

        options_scored.sort(key=lambda row: (-row[0], row[1]))
        if not options_scored:
            continue
        selected = _select_balanced_options(options_scored, legend_domains=legend_domains_tuple, max_items=6)
        out.append(
            CardReplacementSuggestion(
                card=title,
                missing=missing.missing,
                options=selected,
            )
        )

    return out


def analyze_collection_completion(
    deck: DeckPayload,
    *,
    collection: dict[str, int],
    cards: CardCatalog | None = None,
) -> DeckAnalysisResult:
    requirements = _deck_requirement_map(deck)
    collection_by_key = {
        normalize_card_key(title): max(0, int(qty))
        for title, qty in collection.items()
        if normalize_card_key(title)
    }

    total_required = sum(requirements.values())
    total_owned_for_deck = 0
    missing_copies = 0
    missing_cards: list[CardNeed] = []
    for title, required in sorted(requirements.items()):
        key = normalize_card_key(title)
        owned = int(collection_by_key.get(key, 0))
        owned_for_card = min(required, owned)
        missing = max(0, required - owned)
        total_owned_for_deck += owned_for_card
        missing_copies += missing
        if missing > 0:
            missing_cards.append(
                CardNeed(
                    card=title,
                    required=required,
                    owned=owned,
                    missing=missing,
                )
            )

    replacement_suggestions: list[CardReplacementSuggestion] = []
    if cards is not None and missing_cards:
        replacement_suggestions = _build_replacement_suggestions(
            deck=deck,
            cards=cards,
            requirements=requirements,
            collection_by_key=collection_by_key,
            missing_cards=missing_cards,
        )

    completion_pct = 100.0 if total_required <= 0 else round((total_owned_for_deck / total_required) * 100.0, 2)
    return DeckAnalysisResult(
        total_required=total_required,
        total_owned_for_deck=total_owned_for_deck,
        missing_copies=missing_copies,
        missing_unique_cards=len(missing_cards),
        completion_pct=completion_pct,
        is_buildable=missing_copies == 0,
        missing_cards=missing_cards,
        shopping_list=missing_cards,
        replacement_suggestions=replacement_suggestions,
    )
