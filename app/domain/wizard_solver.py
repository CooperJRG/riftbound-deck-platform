from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.infra.auto_builder_repo import AutoBuilderRepository

from app.domain.models import DeckPayload, DeckValidationResult
from app.domain.normalization import canonicalize_titles, coerce_cards_map, normalize_card_key
from app.domain.rules import FormatRules
from app.domain.validator import validate_deck
from app.infra.cards_repo import BASE_DOMAINS, CardCatalog, CardRecord


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
    return set(card.domains).issubset(domains)


def _is_token_card(card: CardRecord) -> bool:
    return card.card_type == "Token" or card.super_type == "Token"



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
    if _is_token_card(card):
        return False
    allowed_types = set(rules.list_constraint("allowed_main_card_types"))
    if allowed_types and card.card_type not in allowed_types:
        return False
    if card.title in _banned_titles(rules=rules, cards=cards):
        return False
    if card.super_type == "Signature":
        legend_card = cards.get(deck.legend_title)
        if legend_card is not None and legend_card.champion_tags:
            legend_tags = set(legend_card.champion_tags)
            if not (legend_tags & set(card.champion_tags)):
                return False
    return _domain_legal(card, _legend_domains(deck, cards=cards))



def _support_from_seed(seed: DeckPayload, *, rules: FormatRules, cards: CardCatalog, main: dict[str, int] | None = None) -> tuple[dict[str, int], list[str]]:
    runes = dict(seed.runes or {})
    battlefields = [title for title in list(seed.battlefields or []) if str(title).strip()]
    legend_domains = _legend_domains(seed, cards=cards)
    banned = _banned_titles(rules=rules, cards=cards)

    rune_exact = rules.int_constraint("rune_count_exact", 12)
    if sum(runes.values()) != rune_exact:
        runes = _runes_for_main(seed, main=dict(main or {}), rules=rules, cards=cards, banned=banned)

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


def _runes_for_main(
    seed: DeckPayload,
    *,
    main: dict[str, int],
    rules: FormatRules,
    cards: CardCatalog,
    banned: set[str],
) -> dict[str, int]:
    rune_exact = rules.int_constraint("rune_count_exact", 12)
    rune_type = str(rules.constraints.get("rune_card_type") or "Rune").strip()
    legend_domains = _legend_domains(seed, cards=cards)
    rune_by_domain: dict[str, str] = {}
    for card in cards.cards:
        if card.card_type != rune_type:
            continue
        if card.title in banned or not _domain_legal(card, legend_domains):
            continue
        if len(card.domains) == 1:
            rune_by_domain[card.domains[0]] = card.title

    if not rune_by_domain:
        return {}

    weights: Counter[str] = Counter()
    for title, qty in dict(main or {}).items():
        card = cards.get(title)
        if card is None or not card.domains:
            continue
        domains = [domain for domain in card.domains if domain in rune_by_domain]
        if not domains:
            continue
        weight = max(1, int(card.cost or 1)) * max(0, int(qty or 0))
        for domain in domains:
            weights[domain] += float(weight) / float(len(domains))

    if not weights:
        preferred = next((domain for domain in BASE_DOMAINS if domain in rune_by_domain), next(iter(rune_by_domain)))
        return {rune_by_domain[preferred]: rune_exact}

    total = float(sum(weights.values()))
    raw = {domain: (float(weight) / total) * float(rune_exact) for domain, weight in weights.items()}
    rounded = {domain: int(value) for domain, value in raw.items()}
    remaining = rune_exact - sum(rounded.values())
    for domain, _value in sorted(raw.items(), key=lambda row: (-(row[1] - int(row[1])), row[0])):
        if remaining <= 0:
            break
        rounded[domain] = rounded.get(domain, 0) + 1
        remaining -= 1

    return {
        rune_by_domain[domain]: qty
        for domain, qty in sorted(rounded.items(), key=lambda row: BASE_DOMAINS.index(row[0]) if row[0] in BASE_DOMAINS else 999)
        if qty > 0 and domain in rune_by_domain
    }


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
    auto_builder: AutoBuilderRepository | None = None,
    collection_agnostic: bool = False,
) -> WizardSolveResult:
    if collection_agnostic:
        canonical_owned = {card.title: 3 for card in cards.cards}
        if owned:
            for k, v in owned.items():
                clean = cards.resolve_title(k)
                if clean:
                    canonical_owned[clean] = max(0, int(v or 0))
        lacking_cards = {cards.resolve_title(k) for k, v in (owned or {}).items() if int(v or 0) <= 0}
        lacking_cards = {x for x in lacking_cards if x is not None}
    else:
        canonical_owned = _canonical_owned(owned, cards=cards)
        lacking_cards = {cards.resolve_title(k) for k, v in (owned or {}).items() if int(v or 0) <= 0}
        lacking_cards = {x for x in lacking_cards if x is not None}

    seed = reference_deck or current_deck or DeckPayload()
    seed = _canonical_deck(seed, cards=cards, format_name=format_name)
    legend = cards.resolve_title(legend_title or seed.legend_title)
    champion = cards.resolve_title(chosen_champion_title or seed.chosen_champion_title)

    # 1. Archetype lookup if collection_agnostic and auto_builder is available
    if collection_agnostic and auto_builder is not None and auto_builder._loaded is not None:
        bundle = auto_builder._loaded.bundle
        archetypes = bundle.get("archetypes") or []
        matching = []
        for arch in archetypes:
            arch_legend = cards.resolve_title(arch.get("legendTitle") or arch.get("legend_title") or "")
            arch_champ = cards.resolve_title(arch.get("chosenChampionTitle") or arch.get("chosen_champion_title") or "")
            if arch_legend == legend and arch_champ == champion:
                matching.append(arch)
        if matching:
            # Sort by confidence and competitivePrior descending
            matching.sort(key=lambda x: (
                -float(x.get("confidence", 0.0) or 0.0),
                -float(x.get("competitivePrior", x.get("competitive_prior", 0.0)) or 0.0)
            ))
            best_archetype = matching[0]
            proto_main = best_archetype.get("prototypeMain") or best_archetype.get("prototype_main") or {}
            reference_deck = DeckPayload(
                name=best_archetype.get("archetypeName") or best_archetype.get("archetype_name") or "Archetype Template",
                source="archetype",
                format=format_name,
                legendTitle=legend,
                chosenChampionTitle=champion,
                main={cards.resolve_title(k): int(v) for k, v in proto_main.items() if cards.resolve_title(k)},
                runes={},
                battlefields=[],
                sideboard={}
            )

    # Re-evaluate seed, reference, and current if reference_deck was loaded/updated
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
    seedless_main = not dict(reference.main or {}) if reference is not None else not dict(current.main or {})
    explicit_owned_titles = {
        cards.resolve_title(title)
        for title in (owned or {}).keys()
        if str(title or "").strip()
    }
    partial_reference_shortages: set[str] = set()
    if reference is not None:
        for title, qty in dict(reference.main or {}).items():
            clean = cards.resolve_title(title)
            card = cards.get(clean)
            requested = max(0, int(qty or 0))
            owned_qty = max(0, int(canonical_owned.get(clean, 0) or 0))
            if (
                clean
                and clean in explicit_owned_titles
                and card is not None
                and requested >= 2
                and 0 < owned_qty < requested
                and not bool(card.is_unique)
                and card.super_type != "Champion"
            ):
                partial_reference_shortages.add(clean)

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
        if card.super_type == "Signature":
            sig_limit = rules.int_constraint("signature_max_total", 0)
            if sig_limit > 0:
                current_sigs = sum(v for k, v in main.items() if (cards.get(k) and cards.get(k).super_type == "Signature"))
                sig_room = max(0, sig_limit - current_sigs)
                add = min(add, sig_room)
        if add > 0:
            main[clean] += add
        return add

    def add_unowned_card(title: str, requested: int) -> int:
        clean = cards.resolve_title(title)
        card = cards.get(clean)
        if card is None or requested <= 0:
            return 0
        if clean in lacking_cards or clean in partial_reference_shortages:
            return 0
        if not _is_legal_main_candidate(card, seed, rules=rules, cards=cards):
            return 0
        cap = _main_copy_cap(card, rules=rules)
        room = max(0, cap - int(main.get(clean, 0) or 0))
        deck_room = max(0, main_size - sum(main.values()))
        add = min(max(0, int(requested)), room, deck_room)
        if card.super_type == "Signature":
            sig_limit = rules.int_constraint("signature_max_total", 0)
            if sig_limit > 0:
                current_sigs = sum(v for k, v in main.items() if (cards.get(k) and cards.get(k).super_type == "Signature"))
                sig_room = max(0, sig_limit - current_sigs)
                add = min(add, sig_room)
        if add > 0:
            main[clean] += add
        return add

    def seedless_card_score(card: CardRecord) -> tuple[int, int, int, int, int, str]:
        champion_card = cards.get(champion)
        primary_domains = set(champion_card.domains) if champion_card is not None and champion_card.domains else set()
        legend_domain_set = _legend_domains(seed, cards=cards)
        card_domains = set(card.domains)
        if primary_domains and card_domains and card_domains.issubset(primary_domains):
            domain_score = 6
        elif primary_domains and card_domains & primary_domains:
            domain_score = 5
        elif legend_domain_set and card_domains and card_domains.issubset(legend_domain_set):
            domain_score = 3
        else:
            domain_score = 0
        type_score = 2 if card.card_type == "Unit" else 1 if card.card_type == "Gear" else 0
        cost = int(card.cost or 0)
        curve_score = 4 - min(4, abs(cost - 3)) if cost > 0 else 0
        owned_score = min(_main_copy_cap(card, rules=rules), max(0, int(canonical_owned.get(card.title, 0) or 0)))
        non_champion_score = 0 if card.super_type == "Champion" else 1
        return (domain_score, non_champion_score, owned_score, type_score, curve_score, card.title.lower())

    def fill_seedless_main_from_focused_pool() -> bool:
        candidates = [
            card
            for card in cards.cards
            if card.title != champion
            and card.super_type != "Champion"
            and max(0, int(canonical_owned.get(card.title, 0) or 0)) > 0
            and _is_legal_main_candidate(card, seed, rules=rules, cards=cards)
        ]
        candidates.sort(key=seedless_card_score, reverse=True)
        for card in candidates:
            if sum(main.values()) >= main_size:
                break
            cap = min(_main_copy_cap(card, rules=rules), max(0, int(canonical_owned.get(card.title, 0) or 0)))
            if cap <= 0:
                continue
            add_card(card.title, cap)
        return sum(main.values()) >= main_size


    # Calculate total available owned copies of legal cards
    total_available_owned = 0
    dropped_wholecloth: set[str] = set()
    for c in cards.cards:
        if _is_legal_main_candidate(c, seed, rules=rules, cards=cards):
            cap = min(_main_copy_cap(c, rules=rules), max(0, int(canonical_owned.get(c.title, 0) or 0)))
            total_available_owned += cap

    if champion:
        if add_card(champion, 1) <= 0:
            explanations.append(f"Chosen champion '{champion}' is not available from the owned pool.")

    for source in [reference, current]:
        if source is None:
            continue
        for title, qty in sorted(dict(source.main or {}).items(), key=lambda row: (row[0] != champion, row[0].lower())):
            clean = cards.resolve_title(title)
            card = cards.get(clean)
            owned_qty = max(0, int(canonical_owned.get(clean, 0) or 0))
            ref_qty = reference.main.get(clean, 0) if reference is not None else 0
            if (
                clean in dropped_wholecloth
                or (
                    card is not None
                    and clean != champion
                    and not bool(card.is_unique)
                    and owned_qty == 1
                    and ref_qty >= 2
                    and (total_available_owned - 1) >= main_size
                )
            ):
                if clean not in dropped_wholecloth:
                    total_available_owned -= 1
                    dropped_wholecloth.add(clean)
                continue
            add_card(title, int(qty or 0))
            if sum(main.values()) >= main_size:
                break
        if sum(main.values()) >= main_size:
            break

    if seedless_main and sum(main.values()) < main_size:
        fill_seedless_main_from_focused_pool()

    # -- Model B / Model A Refinement and Gap Filling --------------------------
    # Try Model B (Transformer) first
    model_b_success = False
    if auto_builder is not None and getattr(auto_builder, "_model_b", None) is not None and getattr(auto_builder, "_artifact_b", None) is not None:
        model_b = auto_builder._model_b
        artifact_b = auto_builder._artifact_b
        device = next(model_b.parameters()).device
        vocab_to_idx = artifact_b.vocab_to_idx
        index_to_key = artifact_b.index_to_key
        card_feat_t = artifact_b.card_feat_matrix_tensor
        all_cand_ids = artifact_b.all_cand_ids_tensor
        freq_by_legend = artifact_b.card_freq_by_legend
        card_cluster_labels = getattr(artifact_b, "card_cluster_labels", None)
        
        legend_to_idx = artifact_b.legend_to_idx
        champion_to_idx = artifact_b.champion_to_idx
        legend_idx_val = legend_to_idx.get(legend, 0)
        champion_idx_val = champion_to_idx.get(champion, 0)
        
        import torch
        legend_idx_t = torch.tensor([legend_idx_val], dtype=torch.long, device=device)
        champion_idx_t = torch.tensor([champion_idx_val], dtype=torch.long, device=device)
        
        from app.domain.auto_builder_model_b import deck_to_tensors, _deck_archetype_idx, _prior_score, _sigmoid
        
        try:
            while sum(main.values()) < main_size:
                remaining = main_size - sum(main.values())
                card_ids_t, feats_t, qty_t, pad_mask_t = deck_to_tensors(
                    dict(main), vocab_to_idx, artifact_b.card_feat_matrix, artifact_b.model_params["max_deck"], device
                )
                rem_frac_t = torch.tensor([remaining / main_size], dtype=torch.float32, device=device)
                
                arch_idx_val = 0
                if card_cluster_labels is not None:
                    arch_idx_val = _deck_archetype_idx(dict(main), vocab_to_idx, card_cluster_labels)
                arch_idx_t = torch.tensor([arch_idx_val], dtype=torch.long, device=device)
                
                logits = model_b.score_candidates_batch(
                    card_ids_t, feats_t, qty_t, legend_idx_t, champion_idx_t,
                    pad_mask_t, rem_frac_t, arch_idx_t, all_cand_ids, card_feat_t,
                ).cpu().numpy()
                
                scored_candidates = []
                for vocab_pos, logit in enumerate(logits):
                    key = index_to_key[vocab_pos] if vocab_pos < len(index_to_key) else ""
                    if not key or key in dropped_wholecloth:
                        continue
                    card = cards.get(key)
                    if card is None:
                        continue
                    if not _is_legal_main_candidate(card, seed, rules=rules, cards=cards):
                        continue
                    cap = min(
                        _main_copy_cap(card, rules=rules),
                        max(0, int(canonical_owned.get(key, 0) or 0)),
                    )
                    room = max(0, cap - int(main.get(key, 0) or 0))
                    if room <= 0:
                        continue
                    prior = _prior_score(key, legend, freq_by_legend)
                    score = 0.75 * _sigmoid(float(logit)) + 0.25 * min(1.0, prior)
                    scored_candidates.append((score, key))
                
                scored_candidates.sort(key=lambda x: (-x[0], x[1]))
                added_any = False
                for score, key in scored_candidates:
                    if add_card(key, 1) > 0:
                        added_any = True
                        break
                if not added_any:
                    break
            model_b_success = True
        except Exception as b_exc:
            # Fall back to Model A or original solver
            pass

    # Try Model A (MoE model) if Model B is not available or failed
    if not model_b_success and auto_builder is not None and auto_builder._loaded is not None:
        bundle = auto_builder._loaded.bundle
        generator_state = auto_builder._loaded.generator_state
        
        from app.domain.auto_builder_types import GenerationPlan
        shell_id = f"{normalize_card_key(legend)}::{normalize_card_key(champion)}"
        shell_label = f"{legend} / {champion}"
        plan = GenerationPlan(
            shell_id=shell_id,
            shell_label=shell_label,
            archetype_id=f"{shell_id}::default",
            archetype_name=f"{champion} Default Archetype",
            archetype_confidence=0.5,
            win_condition_id=0,
            win_condition_label="WC01",
            legend_title=legend,
            chosen_champion_title=champion,
            synergy_cluster_ids=(),
            synergy_cluster_labels=(),
            win_condition_vector=(),
            source_breakdown={},
            seed_decks=(),
        )

        from app.domain.auto_builder_generation import (
            _load_generator_model,
            _bundle_runtime,
            _score_candidate_keys,
        )
        
        try:
            model_a = _load_generator_model(generator_state)
            runtime_cache = _bundle_runtime(bundle, cards)
            embeddings = runtime_cache["embeddings"]
            
            while sum(main.values()) < main_size:
                eligible_keys = []
                for card in cards.cards:
                    key = card.title
                    if key in dropped_wholecloth:
                        continue
                    if not _is_legal_main_candidate(card, seed, rules=rules, cards=cards):
                        continue
                    cap = min(
                        _main_copy_cap(card, rules=rules),
                        max(0, int(canonical_owned.get(key, 0) or 0)),
                    )
                    room = max(0, cap - int(main.get(key, 0) or 0))
                    if room > 0:
                        eligible_keys.append(key)
                
                if not eligible_keys:
                    break
                
                scored = _score_candidate_keys(
                    model=model_a,
                    generator_state=generator_state,
                    plan=plan,
                    partial_main=dict(main),
                    candidate_keys=eligible_keys,
                    bundle=bundle,
                    cards=cards,
                    embeddings=embeddings,
                    static_features=runtime_cache["staticFeatures"],
                    cluster_by_card=runtime_cache["clusterByCard"],
                    collection_by_key={normalize_card_key(k): int(v) for k, v in canonical_owned.items()},
                    runtime_cache=runtime_cache,
                )
                
                scored.sort(key=lambda row: (-row[0], row[1]))
                added_any = False
                for score, key in scored:
                    if add_card(key, 1) > 0:
                        added_any = True
                        break
                if not added_any:
                    break
        except Exception as moe_exc:
            pass

    # Fall back to original greedy alphabetical solver if there is still room
    if sum(main.values()) < main_size:
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
            if card.title not in dropped_wholecloth and canonical_owned.get(card.title, 0) > 0 and _is_legal_main_candidate(card, seed, rules=rules, cards=cards)
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

    # -- Pass 2: Unowned gap-filling pass (only if deck is still under main_size)
    if sum(main.values()) < main_size:
        # Try Model B first for unowned filling
        model_b_success = False
        if auto_builder is not None and getattr(auto_builder, "_model_b", None) is not None and getattr(auto_builder, "_artifact_b", None) is not None:
            model_b = auto_builder._model_b
            artifact_b = auto_builder._artifact_b
            device = next(model_b.parameters()).device
            vocab_to_idx = artifact_b.vocab_to_idx
            index_to_key = artifact_b.index_to_key
            card_feat_t = artifact_b.card_feat_matrix_tensor
            all_cand_ids = artifact_b.all_cand_ids_tensor
            freq_by_legend = artifact_b.card_freq_by_legend
            card_cluster_labels = getattr(artifact_b, "card_cluster_labels", None)
            
            legend_to_idx = artifact_b.legend_to_idx
            champion_to_idx = artifact_b.champion_to_idx
            legend_idx_val = legend_to_idx.get(legend, 0)
            champion_idx_val = champion_to_idx.get(champion, 0)
            
            import torch
            legend_idx_t = torch.tensor([legend_idx_val], dtype=torch.long, device=device)
            champion_idx_t = torch.tensor([champion_idx_val], dtype=torch.long, device=device)
            
            from app.domain.auto_builder_model_b import deck_to_tensors, _deck_archetype_idx, _prior_score, _sigmoid
            
            try:
                while sum(main.values()) < main_size:
                    remaining = main_size - sum(main.values())
                    card_ids_t, feats_t, qty_t, pad_mask_t = deck_to_tensors(
                        dict(main), vocab_to_idx, artifact_b.card_feat_matrix, artifact_b.model_params["max_deck"], device
                    )
                    rem_frac_t = torch.tensor([remaining / main_size], dtype=torch.float32, device=device)
                    
                    arch_idx_val = 0
                    if card_cluster_labels is not None:
                        arch_idx_val = _deck_archetype_idx(dict(main), vocab_to_idx, card_cluster_labels)
                    arch_idx_t = torch.tensor([arch_idx_val], dtype=torch.long, device=device)
                    
                    logits = model_b.score_candidates_batch(
                        card_ids_t, feats_t, qty_t, legend_idx_t, champion_idx_t,
                        pad_mask_t, rem_frac_t, arch_idx_t, all_cand_ids, card_feat_t,
                    ).cpu().numpy()
                    
                    scored_candidates = []
                    for vocab_pos, logit in enumerate(logits):
                        key = index_to_key[vocab_pos] if vocab_pos < len(index_to_key) else ""
                        if not key or key in lacking_cards or key in partial_reference_shortages or key in dropped_wholecloth:
                            continue
                        card = cards.get(key)
                        if card is None:
                            continue
                        if not _is_legal_main_candidate(card, seed, rules=rules, cards=cards):
                            continue
                        cap = _main_copy_cap(card, rules=rules)
                        room = max(0, cap - int(main.get(key, 0) or 0))
                        if room <= 0:
                            continue
                        prior = _prior_score(key, legend, freq_by_legend)
                        score = 0.75 * _sigmoid(float(logit)) + 0.25 * min(1.0, prior)
                        scored_candidates.append((score, key))
                    
                    scored_candidates.sort(key=lambda x: (-x[0], x[1]))
                    added_any = False
                    for score, key in scored_candidates:
                        if add_unowned_card(key, 1) > 0:
                            added_any = True
                            break
                    if not added_any:
                        break
                model_b_success = True
            except Exception as b_exc:
                pass

        # Try Model A next for unowned filling
        if not model_b_success and auto_builder is not None and auto_builder._loaded is not None:
            bundle = auto_builder._loaded.bundle
            generator_state = auto_builder._loaded.generator_state
            
            from app.domain.auto_builder_types import GenerationPlan
            shell_id = f"{normalize_card_key(legend)}::{normalize_card_key(champion)}"
            shell_label = f"{legend} / {champion}"
            plan = GenerationPlan(
                shell_id=shell_id,
                shell_label=shell_label,
                archetype_id=f"{shell_id}::default",
                archetype_name=f"{champion} Default Archetype",
                archetype_confidence=0.5,
                win_condition_id=0,
                win_condition_label="WC01",
                legend_title=legend,
                chosen_champion_title=champion,
                synergy_cluster_ids=(),
                synergy_cluster_labels=(),
                win_condition_vector=(),
                source_breakdown={},
                seed_decks=(),
            )

            from app.domain.auto_builder_generation import (
                _load_generator_model,
                _bundle_runtime,
                _score_candidate_keys,
            )
            
            try:
                model_a = _load_generator_model(generator_state)
                runtime_cache = _bundle_runtime(bundle, cards)
                embeddings = runtime_cache["embeddings"]
                
                while sum(main.values()) < main_size:
                    eligible_keys = []
                    for card in cards.cards:
                        key = card.title
                        if key in lacking_cards or key in partial_reference_shortages or key in dropped_wholecloth:
                            continue
                        if not _is_legal_main_candidate(card, seed, rules=rules, cards=cards):
                            continue
                        cap = _main_copy_cap(card, rules=rules)
                        room = max(0, cap - int(main.get(key, 0) or 0))
                        if room > 0:
                            eligible_keys.append(key)
                    
                    if not eligible_keys:
                        break
                    
                    full_owned_by_key = {normalize_card_key(card.title): 3 for card in cards.cards}
                    scored = _score_candidate_keys(
                        model=model_a,
                        generator_state=generator_state,
                        plan=plan,
                        partial_main=dict(main),
                        candidate_keys=eligible_keys,
                        bundle=bundle,
                        cards=cards,
                        embeddings=embeddings,
                        static_features=runtime_cache["staticFeatures"],
                        cluster_by_card=runtime_cache["clusterByCard"],
                        collection_by_key=full_owned_by_key,
                        runtime_cache=runtime_cache,
                    )
                    
                    scored.sort(key=lambda row: (-row[0], row[1]))
                    added_any = False
                    for score, key in scored:
                        if add_unowned_card(key, 1) > 0:
                            added_any = True
                            break
                    if not added_any:
                        break
            except Exception as moe_exc:
                pass

        # Fall back to original greedy alphabetical solver (unowned)
        if sum(main.values()) < main_size:
            reference_counts = dict(reference.main or {}) if reference is not None else {}
            current_counts = dict(current.main or {}) if current is not None else {}

            def fill_score_unowned(card: CardRecord) -> tuple[int, int, int, str]:
                return (
                    int(reference_counts.get(card.title, 0) or 0),
                    int(current_counts.get(card.title, 0) or 0),
                    1,
                    card.title.lower(),
                )

            fill_cards = [
                card
                for card in cards.cards
                if card.title not in lacking_cards
                and card.title not in partial_reference_shortages
                and card.title not in dropped_wholecloth
                and _is_legal_main_candidate(card, seed, rules=rules, cards=cards)
            ]
            fill_cards.sort(key=fill_score_unowned, reverse=True)
            while sum(main.values()) < main_size:
                progressed = False
                for card in fill_cards:
                    if sum(main.values()) >= main_size:
                        break
                    if add_unowned_card(card.title, 1) > 0:
                        progressed = True
                if not progressed:
                    break

    solved_main = dict(sorted((title, qty) for title, qty in main.items() if qty > 0))
    runes, battlefields = _support_from_seed(seed, rules=rules, cards=cards, main=solved_main)
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
