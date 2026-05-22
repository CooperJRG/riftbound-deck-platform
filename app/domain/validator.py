from __future__ import annotations

from collections import Counter

from app.domain.models import DeckPayload, DeckValidationResult, ValidationIssue
from app.domain.normalization import canonicalize_titles, coerce_cards_map
from app.domain.rules import FormatRules
from app.infra.cards_repo import CardCatalog, CardRecord


def _subset_of_identity(card: CardRecord, legend_domains: set[str]) -> bool:
    if not legend_domains:
        return True
    if not card.domain_parse_ok:
        return True
    return set(card.domains).issubset(legend_domains)


def validate_deck(deck: DeckPayload, *, rules: FormatRules, cards: CardCatalog) -> DeckValidationResult:
    issues: list[ValidationIssue] = []

    def add_issue(code: str, field: str, message: str, ref_key: str) -> None:
        issues.append(
            ValidationIssue(
                code=code,
                field=field,
                message=message,
                rule_refs=rules.refs(ref_key),
            )
        )

    resolve_title = cards.resolve_title
    legend_title = resolve_title(deck.legend_title)
    chosen_title = resolve_title(deck.chosen_champion_title)
    main = canonicalize_titles(coerce_cards_map(deck.main), resolve_title=resolve_title)
    runes = canonicalize_titles(coerce_cards_map(deck.runes), resolve_title=resolve_title)
    sideboard = canonicalize_titles(coerce_cards_map(deck.sideboard), resolve_title=resolve_title)
    battlefields = [resolve_title(title) for title in deck.battlefields if str(title).strip()]

    legend_required = rules.bool_constraint("legend_required", True)
    champion_required = rules.bool_constraint("chosen_champion_required", True)
    domain_enforced = rules.bool_constraint("domain_identity_enforced", True)
    allowed_main_types = set(rules.list_constraint("allowed_main_card_types"))
    allowed_sideboard_types = set(rules.list_constraint("allowed_sideboard_card_types"))

    main_size_exact = rules.int_constraint("main_deck_size_exact", 0)
    runes_exact = rules.int_constraint("rune_count_exact", 0)
    battlefields_exact = rules.int_constraint("battlefield_count_exact", 0)
    battlefields_unique_required = rules.bool_constraint("battlefield_unique_required", False)
    main_copy_limit = rules.int_constraint("main_copy_limit", 0)
    sideboard_max = rules.int_constraint("sideboard_max", 0)
    combined_copy_limit = rules.int_constraint("combined_main_sideboard_copy_limit", 0)
    signature_limit = rules.int_constraint("signature_max_total", 0)

    legend_type = str(rules.constraints.get("legend_card_type") or "Legend").strip()
    champion_super_type = str(rules.constraints.get("champion_super_type") or "Champion").strip()
    rune_type = str(rules.constraints.get("rune_card_type") or "Rune").strip()
    battlefield_type = str(rules.constraints.get("battlefield_card_type") or "Battlefield").strip()

    legend_card = cards.get(legend_title) if legend_title else None
    legend_domains: set[str] = set()
    legend_tags: set[str] = set()

    if legend_required and not legend_title:
        add_issue("LEGEND_REQUIRED", "legendTitle", "Legend is required.", "legend_required")
    if legend_title and legend_card is None:
        add_issue("LEGEND_UNKNOWN", "legendTitle", f"Unknown legend card '{legend_title}'.", "legend_type")
    if legend_card is not None:
        if legend_card.card_type != legend_type:
            add_issue("LEGEND_TYPE", "legendTitle", f"Legend slot must contain a {legend_type}.", "legend_type")
        if legend_card.domain_parse_ok:
            legend_domains = set(legend_card.domains)
        legend_tags = set(legend_card.champion_tags)

    chosen_card = cards.get(chosen_title) if chosen_title else None
    if champion_required and not chosen_title:
        add_issue(
            "CHAMPION_REQUIRED",
            "chosenChampionTitle",
            "Chosen Champion is required for this format.",
            "chosen_champion_required",
        )
    if chosen_title and chosen_card is None:
        add_issue(
            "CHAMPION_UNKNOWN",
            "chosenChampionTitle",
            f"Unknown chosen champion '{chosen_title}'.",
            "chosen_champion_type",
        )
    if chosen_card is not None:
        if chosen_card.card_type != "Unit" or chosen_card.super_type != champion_super_type:
            add_issue(
                "CHAMPION_TYPE",
                "chosenChampionTitle",
                f"Chosen Champion must be a {champion_super_type} Unit.",
                "chosen_champion_type",
            )
        if legend_tags and not (legend_tags & set(chosen_card.champion_tags)):
            add_issue(
                "CHAMPION_TAG",
                "chosenChampionTitle",
                "Chosen Champion tag must match Legend champion tag.",
                "chosen_champion_tag_match",
            )

    main_total = sum(main.values())
    runes_total = sum(runes.values())
    sideboard_total = sum(sideboard.values())
    if main_size_exact and main_total != main_size_exact:
        add_issue(
            "MAIN_DECK_SIZE",
            "main",
            f"Main deck must contain exactly {main_size_exact} cards (found {main_total}).",
            "main_deck_size",
        )
    if runes_exact and runes_total != runes_exact:
        add_issue(
            "RUNE_DECK_SIZE",
            "runes",
            f"Rune deck must contain exactly {runes_exact} cards (found {runes_total}).",
            "rune_count",
        )
    if battlefields_exact and len(battlefields) != battlefields_exact:
        add_issue(
            "BATTLEFIELD_COUNT",
            "battlefields",
            f"Deck must contain exactly {battlefields_exact} battlefields (found {len(battlefields)}).",
            "battlefield_count",
        )
    if battlefields_unique_required and len(set(battlefields)) != len(battlefields):
        add_issue(
            "BATTLEFIELD_UNIQUE",
            "battlefields",
            "Battlefield names must be unique.",
            "battlefield_unique",
        )
    if sideboard_max and sideboard_total > sideboard_max:
        add_issue(
            "SIDEBOARD_MAX",
            "sideboard",
            f"Sideboard must contain at most {sideboard_max} cards (found {sideboard_total}).",
            "sideboard_max",
        )

    if chosen_title and main.get(chosen_title, 0) < 1:
        add_issue(
            "CHAMPION_IN_MAIN",
            "main",
            "Main deck must include at least one copy of the chosen champion.",
            "chosen_champion_in_main",
        )

    signature_total = 0
    for title, qty in sorted(main.items()):
        if main_copy_limit and qty > main_copy_limit:
            add_issue(
                "MAIN_COPY_LIMIT",
                "main",
                f"Card '{title}' exceeds copy limit ({qty} > {main_copy_limit}).",
                "main_copy_limit",
            )
        card = cards.get(title)
        if card is None:
            add_issue("MAIN_UNKNOWN_CARD", "main", f"Unknown card '{title}'.", "main_card_types")
            continue
        if allowed_main_types and card.card_type not in allowed_main_types:
            add_issue(
                "MAIN_CARD_TYPE",
                "main",
                f"Card '{title}' is not a legal main-deck type ({card.card_type}).",
                "main_card_types",
            )
        if domain_enforced and legend_domains:
            if not card.domains or not _subset_of_identity(card, legend_domains):
                add_issue(
                    "MAIN_DOMAIN",
                    "main",
                    f"Card '{title}' is outside legend domain identity.",
                    "domain_identity_main",
                )
        if card.super_type == "Signature":
            signature_total += qty
            if legend_tags and not (legend_tags & set(card.champion_tags)):
                add_issue(
                    "SIGNATURE_TAG",
                    "main",
                    f"Signature card '{title}' does not match legend champion tag.",
                    "signature_tag_match",
                )

    for title, qty in sorted(sideboard.items()):
        card = cards.get(title)
        if card is None:
            add_issue("SIDEBOARD_UNKNOWN_CARD", "sideboard", f"Unknown card '{title}'.", "sideboard_card_types")
            continue
        if allowed_sideboard_types and card.card_type not in allowed_sideboard_types:
            add_issue(
                "SIDEBOARD_CARD_TYPE",
                "sideboard",
                f"Card '{title}' is not a legal sideboard card type ({card.card_type}).",
                "sideboard_card_types",
            )
        if domain_enforced and legend_domains:
            if not card.domains or not _subset_of_identity(card, legend_domains):
                add_issue(
                    "SIDEBOARD_DOMAIN",
                    "sideboard",
                    f"Card '{title}' is outside legend domain identity.",
                    "domain_identity_sideboard",
                )
        if card.super_type == "Signature":
            signature_total += qty
            if legend_tags and not (legend_tags & set(card.champion_tags)):
                add_issue(
                    "SIGNATURE_TAG_SB",
                    "sideboard",
                    f"Signature sideboard card '{title}' does not match legend champion tag.",
                    "signature_tag_match",
                )
        if main_copy_limit and qty > main_copy_limit:
            add_issue(
                "SIDEBOARD_COPY_LIMIT",
                "sideboard",
                f"Card '{title}' exceeds copy limit ({qty} > {main_copy_limit}).",
                "main_copy_limit",
            )

    for title, qty in sorted(runes.items()):
        card = cards.get(title)
        if card is None:
            add_issue("RUNE_UNKNOWN_CARD", "runes", f"Unknown rune '{title}'.", "rune_card_type")
            continue
        if card.card_type != rune_type:
            add_issue(
                "RUNE_CARD_TYPE",
                "runes",
                f"Rune deck card '{title}' must be type {rune_type}.",
                "rune_card_type",
            )
        if domain_enforced and legend_domains and not _subset_of_identity(card, legend_domains):
            add_issue(
                "RUNE_DOMAIN",
                "runes",
                f"Rune '{title}' is outside legend domain identity.",
                "domain_identity_runes",
            )

    for title in battlefields:
        card = cards.get(title)
        if card is None:
            add_issue("BATTLEFIELD_UNKNOWN", "battlefields", f"Unknown battlefield '{title}'.", "battlefield_type")
            continue
        if card.card_type != battlefield_type:
            add_issue(
                "BATTLEFIELD_TYPE",
                "battlefields",
                f"Battlefield slot card '{title}' must be type {battlefield_type}.",
                "battlefield_type",
            )
        if domain_enforced and legend_domains and not _subset_of_identity(card, legend_domains):
            add_issue(
                "BATTLEFIELD_DOMAIN",
                "battlefields",
                f"Battlefield '{title}' is outside legend domain identity.",
                "domain_identity_battlefields",
            )

    if combined_copy_limit:
        combined = Counter(main)
        for title, qty in sideboard.items():
            combined[title] += qty
        for title, qty in sorted(combined.items()):
            if qty > combined_copy_limit:
                add_issue(
                    "COMBINED_COPY_LIMIT",
                    "sideboard",
                    (
                        f"Card '{title}' exceeds combined main+sideboard copy limit "
                        f"({qty} > {combined_copy_limit})."
                    ),
                    "combined_copy_limit",
                )

    combined_registered = Counter(main)
    for title, qty in sideboard.items():
        combined_registered[title] += qty
    for title, qty in sorted(combined_registered.items()):
        card = cards.get(title)
        if card is None or not bool(card.is_unique):
            continue
        if int(qty) <= 1:
            continue
        ref_key = "combined_copy_limit" if int(sideboard.get(title, 0)) > 0 else "main_copy_limit"
        field = "sideboard" if int(sideboard.get(title, 0)) > 0 else "main"
        add_issue(
            "UNIQUE_CARD_LIMIT",
            field,
            f"Card '{title}' is unique and your registered deck may contain only 1 copy ({qty} found).",
            ref_key,
        )

    if signature_limit and signature_total > signature_limit:
        add_issue(
            "SIGNATURE_LIMIT",
            "main",
            f"Deck contains {signature_total} signature cards (max {signature_limit}).",
            "signature_limit",
        )

    # Ban list check
    banned_cards_profile = rules.list_constraint("banned_cards")
    if banned_cards_profile:
        banned_list = set(cards.resolve_title(title) for title in banned_cards_profile)
    else:
        banned_list = {
            "Called Shot",
            "Draven - Vanquisher",
            "Fight or Flight",
            "Scrapheap",
            "Obelisk of Power",
            "Reaver's Row",
            "The Dreaming Tree"
        }

    banned_in_deck = []
    if legend_title and cards.resolve_title(legend_title) in banned_list:
        banned_in_deck.append((legend_title, "legendTitle"))
    if chosen_title and cards.resolve_title(chosen_title) in banned_list:
        banned_in_deck.append((chosen_title, "chosenChampionTitle"))
    for title in sorted(main.keys()):
        if cards.resolve_title(title) in banned_list:
            banned_in_deck.append((title, "main"))
    for title in sorted(sideboard.keys()):
        if cards.resolve_title(title) in banned_list:
            banned_in_deck.append((title, "sideboard"))
    for title in sorted(runes.keys()):
        if cards.resolve_title(title) in banned_list:
            banned_in_deck.append((title, "runes"))
    for title in sorted(battlefields):
        if cards.resolve_title(title) in banned_list:
            banned_in_deck.append((title, "battlefields"))

    for card_title, field in banned_in_deck:
        add_issue(
            "BANNED_CARD",
            field,
            f"Card '{card_title}' is banned.",
            "banned_list",
        )

    return DeckValidationResult(
        is_valid=len(issues) == 0,
        issues=issues,
        summary="Deck is valid." if not issues else f"{len(issues)} issue(s) found.",
    )


def validate_deck_for_meta_index(deck: DeckPayload, *, rules: FormatRules, cards: CardCatalog) -> DeckValidationResult:
    """Lenient validation for imported community/meta lists (browse-only, not tournament registration)."""
    issues: list[ValidationIssue] = []

    def add_issue(code: str, field: str, message: str) -> None:
        issues.append(ValidationIssue(code=code, field=field, message=message, rule_refs=()))

    resolve_title = cards.resolve_title
    legend_title = resolve_title(deck.legend_title)
    main = canonicalize_titles(coerce_cards_map(deck.main), resolve_title=resolve_title)
    runes = canonicalize_titles(coerce_cards_map(deck.runes), resolve_title=resolve_title)
    battlefields = [resolve_title(title) for title in deck.battlefields if str(title).strip()]

    main_total = sum(main.values())
    runes_total = sum(runes.values())
    if main_total < 30:
        add_issue("META_MAIN_TOO_SMALL", "main", f"Main deck has too few cards ({main_total}).")
    if main_total > 56:
        add_issue("META_MAIN_TOO_LARGE", "main", f"Main deck has too many cards ({main_total}).")
    if runes_total > 12:
        add_issue("META_RUNE_TOO_LARGE", "runes", f"Rune section exceeds 12 cards ({runes_total}).")

    unknown_main = 0
    for title, qty in main.items():
        if int(qty) <= 0:
            continue
        if cards.get(title) is None:
            unknown_main += int(qty)
    if main_total > 0 and unknown_main > max(12, int(main_total * 0.35)):
        add_issue(
            "META_TOO_MANY_UNKNOWN",
            "main",
            f"Too many unrecognized main-deck cards ({unknown_main}/{main_total}).",
        )

    if not legend_title:
        add_issue("META_LEGEND_MISSING", "legendTitle", "Deck is missing a recognizable legend.")

    return DeckValidationResult(
        is_valid=len(issues) == 0,
        issues=issues,
        summary="Deck is valid for meta browse." if not issues else f"{len(issues)} issue(s) found.",
    )
