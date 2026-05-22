from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.domain.models import DeckPayload, DeckValidationResult
from app.domain.normalization import canonicalize_titles, coerce_cards_map
from app.domain.rules import FormatRules
from app.domain.validator import validate_deck
from app.infra.cards_repo import CardCatalog, CardRecord


@dataclass(frozen=True)
class WizardSolveResult:
    deck: DeckPayload
    validation: DeckValidationResult
    metrics: dict[str, Any]
    diff: dict[str, list[dict[str, Any]]]
    explanations: list[str]
    playlist: list[dict[str, Any]]
    replacement_clusters: list[dict[str, Any]]
    solver_status: str


def _canonical_deck(deck: DeckPayload, *, cards: CardCatalog, format_name: str = "") -> DeckPayload:
    resolve_title = cards.resolve_title
    return DeckPayload(
        name=deck.name,
        source=deck.source,
        format=format_name or deck.format,
        legendTitle=resolve_title(deck.legend_title),
        chosenChampionTitle=resolve_title(deck.chosen_champion_title),
        main=canonicalize_titles(coerce_cards_map(deck.main), resolve_title=resolve_title),
        runes=canonicalize_titles(coerce_cards_map(deck.runes), resolve_title=resolve_title),
        battlefields=[resolve_title(title) for title in deck.battlefields if str(title).strip()],
        sideboard=canonicalize_titles(coerce_cards_map(deck.sideboard), resolve_title=resolve_title),
    )


def _canonical_owned(owned: dict[str, int], *, cards: CardCatalog) -> dict[str, int]:
    out: dict[str, int] = {}
    for title, qty in (owned or {}).items():
        clean = cards.resolve_title(title)
        amount = max(0, int(qty or 0))
        if clean and amount > 0:
            out[clean] = out.get(clean, 0) + amount
    return out


def _main_copy_cap(card: CardRecord | None, *, rules: FormatRules) -> int:
    cap = max(1, rules.int_constraint("main_copy_limit", 3))
    if card is not None and bool(card.is_unique):
        return 1
    return cap


def _legend_domains(deck: DeckPayload, *, cards: CardCatalog) -> set[str]:
    legend = cards.get(deck.legend_title)
    if legend is None or not legend.domain_parse_ok:
        return set()
    return set(legend.domains)


def _domain_legal(card: CardRecord, domains: set[str]) -> bool:
    if not domains:
        return True
    if not card.domain_parse_ok:
        return True
    return bool(card.domains) and set(card.domains).issubset(domains)


def _banned_titles(*, rules: FormatRules, cards: CardCatalog) -> set[str]:
    configured = rules.list_constraint("banned_cards")
    source = configured or [
        "Called Shot",
        "Draven - Vanquisher",
        "Fight or Flight",
        "Scrapheap",
        "Obelisk of Power",
        "Reaver's Row",
        "The Dreaming Tree",
    ]
    return {cards.resolve_title(title) for title in source if str(title).strip()}


def _is_legal_main_candidate(card: CardRecord, deck: DeckPayload, *, rules: FormatRules, cards: CardCatalog) -> bool:
    allowed_types = set(rules.list_constraint("allowed_main_card_types"))
    if allowed_types and card.card_type not in allowed_types:
        return False
    if card.title in _banned_titles(rules=rules, cards=cards):
        return False
    return _domain_legal(card, _legend_domains(deck, cards=cards))


def _support_from_seed(seed: DeckPayload, *, rules: FormatRules, cards: CardCatalog) -> tuple[dict[str, int], list[str]]:
    runes = dict(seed.runes or {})
    battlefields = [title for title in list(seed.battlefields or []) if str(title).strip()]
    legend_domains = _legend_domains(seed, cards=cards)
    banned = _banned_titles(rules=rules, cards=cards)

    rune_exact = rules.int_constraint("rune_count_exact", 12)
    if sum(runes.values()) != rune_exact:
        runes = {}
        for card in cards.cards:
            if card.card_type != str(rules.constraints.get("rune_card_type") or "Rune").strip():
                continue
            if card.title in banned or not _domain_legal(card, legend_domains):
                continue
            runes[card.title] = rune_exact
            break

    battlefield_exact = rules.int_constraint("battlefield_count_exact", 3)
    unique_required = rules.bool_constraint("battlefield_unique_required", False)
    if len(battlefields) != battlefield_exact or (unique_required and len(set(battlefields)) != len(battlefields)):
        battlefields = []
        for card in cards.cards:
            if card.card_type != str(rules.constraints.get("battlefield_card_type") or "Battlefield").strip():
                continue
            if card.title in banned or not _domain_legal(card, legend_domains):
                continue
            if unique_required and card.title in battlefields:
                continue
            battlefields.append(card.title)
            if len(battlefields) >= battlefield_exact:
                break
    return runes, battlefields


def _diff_main(before: dict[str, int], after: dict[str, int]) -> dict[str, list[dict[str, Any]]]:
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    qty_changes: list[dict[str, Any]] = []
    keys = sorted(set(before) | set(after))
    for title in keys:
        old = int(before.get(title, 0) or 0)
        new = int(after.get(title, 0) or 0)
        if old <= 0 and new > 0:
            added.append({"card": title, "qty": new})
        elif old > 0 and new <= 0:
            removed.append({"card": title, "qty": old})
        elif old != new:
            qty_changes.append({"card": title, "before": old, "after": new})
    return {"added": added, "removed": removed, "qtyChanges": qty_changes}


def _replacement_clusters_from_diff(
    diff: dict[str, list[dict[str, Any]]],
    *,
    validation: DeckValidationResult,
    metrics: dict[str, Any],
    solver_status: str,
) -> list[dict[str, Any]]:
    removed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []

    for row in diff.get("removed", []):
        qty = max(0, int(row.get("qty", 0) or 0))
        card = str(row.get("card") or "").strip()
        if card and qty > 0:
            removed.append({"card": card, "qty": qty})

    for row in diff.get("qtyChanges", []):
        before = max(0, int(row.get("before", 0) or 0))
        after = max(0, int(row.get("after", 0) or 0))
        card = str(row.get("card") or "").strip()
        if not card or before == after:
            continue
        if before > after:
            removed.append({"card": card, "qty": before - after})
        else:
            added.append({"card": card, "qty": after - before})

    for row in diff.get("added", []):
        qty = max(0, int(row.get("qty", 0) or 0))
        card = str(row.get("card") or "").strip()
        if card and qty > 0:
            added.append({"card": card, "qty": qty})

    if not removed or not added:
        return []

    return [
        {
            "source": "owned-solver",
            "reason": "Legal owned-card replacement cluster",
            "score": float(metrics.get("completionPct", 0.0) or 0.0) / 100.0,
            "removed": removed,
            "added": added,
            "diff": diff,
            "legal": bool(validation.is_valid),
            "fullyOwned": bool(metrics.get("isFullyOwned", False)),
            "solverStatus": solver_status,
        }
    ]


def _completion_metrics(deck: DeckPayload, *, owned: dict[str, int]) -> dict[str, Any]:
    required = 0
    owned_total = 0
    missing_unique = 0
    for title, qty in dict(deck.main or {}).items():
        needed = max(0, int(qty or 0))
        if needed <= 0:
            continue
        required += needed
        have = min(needed, max(0, int(owned.get(title, 0) or 0)))
        owned_total += have
        if have < needed:
            missing_unique += 1
    completion = 100.0 if required <= 0 else (float(owned_total) / float(required)) * 100.0
    return {
        "completionPct": completion,
        "isFullyOwned": missing_unique == 0,
        "ownedMainCopies": owned_total,
        "requiredMainCopies": required,
        "missingUniqueCards": missing_unique,
    }


def build_wizard_playlist(reference: DeckPayload | None, solved: DeckPayload, *, owned: dict[str, int]) -> list[dict[str, Any]]:
    if reference is None:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title, qty in sorted(dict(reference.main or {}).items()):
        needed = max(0, int(qty or 0))
        if needed <= 0:
            continue
        have = max(0, int(owned.get(title, 0) or 0))
        solved_qty = max(0, int((solved.main or {}).get(title, 0) or 0))
        short = max(0, needed - have)
        if short <= 0 or title in seen:
            continue
        seen.add(title)
        out.append(
            {
                "card": title,
                "required": short,
                "reason": "From original optimal template",
                "source": "optimal-target",
                "priority": 0.99 if solved_qty < needed else 0.75,
                "score": 0.99 if solved_qty < needed else 0.75,
            }
        )
    out.sort(key=lambda row: (-float(row.get("priority", 0.0) or 0.0), str(row.get("card") or "").lower()))
    return out


def apply_wizard_main_swap(
    deck: DeckPayload,
    from_card: str,
    to_card: str,
    *,
    owned: dict[str, int],
    rules: FormatRules,
    cards: CardCatalog,
    strict_owned: bool = True,
) -> DeckPayload:
    canonical = _canonical_deck(deck, cards=cards)
    source = cards.resolve_title(from_card)
    target = cards.resolve_title(to_card)
    main = dict(canonical.main or {})
    qty = max(0, int(main.get(source, 0) or 0))
    if qty <= 0 or not target:
        return canonical
    target_card = cards.get(target)
    cap = _main_copy_cap(target_card, rules=rules)
    if strict_owned:
        cap = min(cap, max(0, int(owned.get(target, 0) or 0)))
    main.pop(source, None)
    replacement_qty = min(qty, cap)
    if replacement_qty > 0:
        main[target] = replacement_qty
    return DeckPayload(
        name=canonical.name,
        source=canonical.source,
        format=canonical.format,
        legendTitle=canonical.legend_title,
        chosenChampionTitle=canonical.chosen_champion_title,
        main=main,
        runes=dict(canonical.runes or {}),
        battlefields=list(canonical.battlefields or []),
        sideboard=dict(canonical.sideboard or {}),
    )


def solve_wizard_deck(
    *,
    legend_title: str,
    chosen_champion_title: str,
    format_name: str,
    owned: dict[str, int],
    rules: FormatRules,
    cards: CardCatalog,
    reference_deck: DeckPayload | None = None,
    current_deck: DeckPayload | None = None,
    swaps: list[dict[str, str]] | None = None,
) -> WizardSolveResult:
    canonical_owned = _canonical_owned(owned, cards=cards)
    seed = reference_deck or current_deck or DeckPayload()
    seed = _canonical_deck(seed, cards=cards, format_name=format_name)
    legend = cards.resolve_title(legend_title or seed.legend_title)
    champion = cards.resolve_title(chosen_champion_title or seed.chosen_champion_title)
    seed = DeckPayload(
        name=seed.name or "Guided Deck",
        source="wizard",
        format=format_name or seed.format,
        legendTitle=legend,
        chosenChampionTitle=champion,
        main=dict(seed.main or {}),
        runes=dict(seed.runes or {}),
        battlefields=list(seed.battlefields or []),
        sideboard={},
    )
    reference = _canonical_deck(reference_deck, cards=cards, format_name=seed.format) if reference_deck is not None else None
    current = _canonical_deck(current_deck, cards=cards, format_name=seed.format) if current_deck is not None else seed

    main_size = rules.int_constraint("main_deck_size_exact", 40)
    main: Counter[str] = Counter()
    explanations: list[str] = []

    def add_card(title: str, requested: int) -> int:
        clean = cards.resolve_title(title)
        card = cards.get(clean)
        if card is None or requested <= 0:
            return 0
        if not _is_legal_main_candidate(card, seed, rules=rules, cards=cards):
            return 0
        cap = min(
            _main_copy_cap(card, rules=rules),
            max(0, int(canonical_owned.get(clean, 0) or 0)),
        )
        room = max(0, cap - int(main.get(clean, 0) or 0))
        deck_room = max(0, main_size - sum(main.values()))
        add = min(max(0, int(requested)), room, deck_room)
        if add > 0:
            main[clean] += add
        return add

    if champion:
        if add_card(champion, 1) <= 0:
            explanations.append(f"Chosen champion '{champion}' is not available from the owned pool.")

    for source in [reference, current]:
        if source is None:
            continue
        for title, qty in sorted(dict(source.main or {}).items(), key=lambda row: (row[0] != champion, row[0].lower())):
            add_card(title, int(qty or 0))
            if sum(main.values()) >= main_size:
                break
        if sum(main.values()) >= main_size:
            break

    reference_counts = dict(reference.main or {}) if reference is not None else {}
    current_counts = dict(current.main or {}) if current is not None else {}

    def fill_score(card: CardRecord) -> tuple[int, int, int, str]:
        return (
            int(reference_counts.get(card.title, 0) or 0),
            int(current_counts.get(card.title, 0) or 0),
            int(canonical_owned.get(card.title, 0) or 0),
            card.title.lower(),
        )

    fill_cards = [
        card
        for card in cards.cards
        if canonical_owned.get(card.title, 0) > 0 and _is_legal_main_candidate(card, seed, rules=rules, cards=cards)
    ]
    fill_cards.sort(key=fill_score, reverse=True)
    while sum(main.values()) < main_size:
        progressed = False
        for card in fill_cards:
            if sum(main.values()) >= main_size:
                break
            if add_card(card.title, 1) > 0:
                progressed = True
        if not progressed:
            break

    solved_main = dict(sorted((title, qty) for title, qty in main.items() if qty > 0))
    runes, battlefields = _support_from_seed(seed, rules=rules, cards=cards)
    solved = DeckPayload(
        name=current.name or seed.name or "Guided Deck",
        source="wizard",
        format=seed.format or format_name,
        legendTitle=legend,
        chosenChampionTitle=champion,
        main=solved_main,
        runes=runes,
        battlefields=battlefields,
        sideboard={},
    )

    for swap in swaps or []:
        solved = apply_wizard_main_swap(
            solved,
            str(swap.get("from") or swap.get("from_card") or ""),
            str(swap.get("to") or swap.get("to_card") or ""),
            owned=canonical_owned,
            rules=rules,
            cards=cards,
            strict_owned=True,
        )

    validation = validate_deck(solved, rules=rules, cards=cards)
    metrics = _completion_metrics(solved, owned=canonical_owned)
    metrics["competitiveScore"] = 0.0
    metrics["mainDeckSize"] = sum(int(qty or 0) for qty in solved.main.values())
    status = "optimal" if validation.is_valid and metrics["isFullyOwned"] else "feasible"
    if not validation.is_valid or sum(solved.main.values()) < main_size:
        status = "infeasible_owned_only"
    if status == "infeasible_owned_only":
        explanations.append("Could not find a full legal main deck from owned cards only.")
    elif reference is not None:
        explanations.append("Projected the reference list onto owned cards with copy limits enforced.")

    diff = _diff_main(dict(current.main or {}), dict(solved.main or {}))
    replacement_clusters = _replacement_clusters_from_diff(
        diff,
        validation=validation,
        metrics=metrics,
        solver_status=status,
    )

    return WizardSolveResult(
        deck=solved,
        validation=validation,
        metrics=metrics,
        diff=diff,
        explanations=explanations,
        playlist=build_wizard_playlist(reference, solved, owned=canonical_owned),
        replacement_clusters=replacement_clusters,
        solver_status=status,
    )
