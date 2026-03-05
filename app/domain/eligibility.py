from __future__ import annotations

from dataclasses import dataclass

from app.domain.normalization import normalize_card_key
from app.domain.rules import FormatRules
from app.infra.cards_repo import CardCatalog, CardRecord


@dataclass(frozen=True)
class EligibilitySnapshot:
    legend_title: str
    legend_domains: tuple[str, ...]
    legends: tuple[CardRecord, ...]
    champions: tuple[CardRecord, ...]
    battlefields: tuple[CardRecord, ...]
    runes: tuple[CardRecord, ...]
    recommended_runes: dict[str, int]
    main_deck_size: int
    rune_deck_size: int
    battlefield_count: int
    main_copy_limit: int
    allowed_main_card_types: tuple[str, ...]
    sideboard_max: int
    allowed_sideboard_card_types: tuple[str, ...]


def _title_match(title: str, query: str) -> bool:
    needle = normalize_card_key(query)
    if not needle:
        return True
    return needle in normalize_card_key(title)


def _within_domain_identity(card: CardRecord, *, legend_domains: set[str], enforce: bool) -> bool:
    if not enforce or not legend_domains:
        return True
    if not card.domain_parse_ok:
        return True
    return set(card.domains).issubset(legend_domains)


def _slice_sorted(rows: list[CardRecord], *, limit: int) -> tuple[CardRecord, ...]:
    return tuple(sorted(rows, key=lambda c: c.title.casefold())[: max(1, limit)])


def _recommend_runes(
    runes: tuple[CardRecord, ...],
    *,
    legend_domains: tuple[str, ...],
    target_total: int,
) -> dict[str, int]:
    if target_total <= 0 or not runes:
        return {}

    domain_order = list(legend_domains)
    picks: list[CardRecord] = []
    used_titles: set[str] = set()
    if domain_order:
        for domain in domain_order:
            card = next((r for r in runes if len(r.domains) == 1 and r.domains[0] == domain), None)
            if card is None:
                card = next((r for r in runes if domain in set(r.domains)), None)
            if card is None:
                continue
            if card.title in used_titles:
                continue
            picks.append(card)
            used_titles.add(card.title)
    if not picks:
        picks = [runes[0]]

    slots = len(picks)
    base = target_total // slots
    rem = target_total % slots
    out: dict[str, int] = {}
    for idx, card in enumerate(picks):
        out[card.title] = base + (1 if idx < rem else 0)
    return out


def build_eligibility_snapshot(
    *,
    cards: CardCatalog,
    rules: FormatRules,
    legend_title: str,
    query: str = "",
    limit: int = 400,
) -> EligibilitySnapshot:
    legend_type = str(rules.constraints.get("legend_card_type") or "Legend").strip()
    champion_super_type = str(rules.constraints.get("champion_super_type") or "Champion").strip()
    battlefield_type = str(rules.constraints.get("battlefield_card_type") or "Battlefield").strip()
    rune_type = str(rules.constraints.get("rune_card_type") or "Rune").strip()
    enforce_identity = rules.bool_constraint("domain_identity_enforced", True)

    resolved_legend = cards.resolve_title(legend_title) if legend_title else ""
    legend_card = cards.get(resolved_legend) if resolved_legend else None
    legend_domains = tuple(legend_card.domains) if legend_card else tuple()
    legend_domain_set = set(legend_domains)
    legend_tags = set(legend_card.champion_tags) if legend_card else set()

    legends: list[CardRecord] = []
    champions: list[CardRecord] = []
    battlefields: list[CardRecord] = []
    runes: list[CardRecord] = []
    for card in cards.cards:
        if not _title_match(card.title, query):
            continue
        if card.card_type == legend_type:
            legends.append(card)
        if card.card_type == "Unit" and card.super_type == champion_super_type:
            if legend_tags and not (legend_tags & set(card.champion_tags)):
                pass
            else:
                champions.append(card)
        if card.card_type == battlefield_type and _within_domain_identity(
            card,
            legend_domains=legend_domain_set,
            enforce=enforce_identity,
        ):
            battlefields.append(card)
        if card.card_type == rune_type and _within_domain_identity(
            card,
            legend_domains=legend_domain_set,
            enforce=enforce_identity,
        ):
            runes.append(card)

    legends_out = _slice_sorted(legends, limit=limit)
    champions_out = _slice_sorted(champions, limit=limit)
    battlefields_out = _slice_sorted(battlefields, limit=limit)
    runes_out = _slice_sorted(runes, limit=limit)

    rune_total = rules.int_constraint("rune_count_exact", 12)
    recommended = _recommend_runes(
        runes_out,
        legend_domains=legend_domains,
        target_total=rune_total,
    )

    return EligibilitySnapshot(
        legend_title=resolved_legend,
        legend_domains=legend_domains,
        legends=legends_out,
        champions=champions_out,
        battlefields=battlefields_out,
        runes=runes_out,
        recommended_runes=recommended,
        main_deck_size=rules.int_constraint("main_deck_size_exact", 40),
        rune_deck_size=rune_total,
        battlefield_count=rules.int_constraint("battlefield_count_exact", 3),
        main_copy_limit=rules.int_constraint("main_copy_limit", 3),
        allowed_main_card_types=tuple(rules.list_constraint("allowed_main_card_types")),
        sideboard_max=rules.int_constraint("sideboard_max", 8),
        allowed_sideboard_card_types=tuple(rules.list_constraint("allowed_sideboard_card_types")),
    )
