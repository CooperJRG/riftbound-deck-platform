import json
from collections import Counter

from app.core.config import load_config
from app.domain.normalization import coerce_cards_map
from app.domain.rules import load_format_rules
from app.domain.validator import validate_deck, validate_deck_for_meta_index
from app.infra.cards_repo import load_card_catalog
from app.infra.meta_repo import DeckPayload, _infer_champion, _split_components

config = load_config()
rules = load_format_rules(config.rules_profile_path)
cards = load_card_catalog(config.cards_path)
rows = json.loads(config.meta_index_path.read_text(encoding="utf-8"))
issue_counts: Counter[str] = Counter()
valid = 0
unl_ok = 0
unl_fail = 0
for row in rows:
    cards_map = coerce_cards_map(row.get("cards"))
    has_unl = any(
        (card := cards.get(title)) is not None and str(card.set_name).lower().startswith("unl")
        for title in cards_map
    )
    legend, main, runes, bfs = _split_components(
        cards_map, catalog=cards, leader_title=str(row.get("leaderTitle") or "")
    )
    chosen = _infer_champion(main, legend=legend, catalog=cards)
    payload = DeckPayload(
        name=str(row.get("name") or ""),
        source="meta",
        format="constructed",
        legendTitle=legend,
        chosenChampionTitle=chosen,
        main=main,
        runes=runes,
        battlefields=bfs,
        sideboard={},
    )
    result = validate_deck_for_meta_index(payload, rules=rules, cards=cards)
    if result.is_valid:
        valid += 1
        if has_unl:
            unl_ok += 1
    else:
        if has_unl:
            unl_fail += 1
        for issue in result.issues[:4]:
            issue_counts[issue.message[:80]] += 1

print("raw", len(rows), "valid", valid, "unl_ok", unl_ok, "unl_fail", unl_fail)
print("top issues:")
for msg, count in issue_counts.most_common(15):
    print(count, msg)
