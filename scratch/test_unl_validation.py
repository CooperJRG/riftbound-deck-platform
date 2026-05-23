import json
from pathlib import Path
from app.core.config import load_config
from app.infra.cards_repo import load_card_catalog
from app.domain.rules import load_format_rules
from app.domain.validator import validate_deck
from app.infra.meta_repo import _split_components, _infer_champion, DeckPayload

config = load_config()
rules = load_format_rules(config.rules_profile_path)
cards = load_card_catalog(config.cards_path)

print("Loaded card catalog path:", config.cards_path)
print("Loaded rules profile path:", config.rules_profile_path)

meta_index_path = config.meta_index_path
print("Meta index JSON path:", meta_index_path)

if not meta_index_path.is_file():
    print("Meta index JSON file not found!")
    exit(1)

with open(meta_index_path, "r", encoding="utf-8") as f:
    rows = json.load(f)

print(f"Total raw meta deck rows: {len(rows)}")

skipped = 0
unl_count = 0
valid_unl_count = 0
skipped_issues = []

for idx, row in enumerate(rows):
    source = str(row.get("source") or "").strip()
    deck_name = str(row.get("name") or row.get("deckName") or "").strip()
    leader_title = str(row.get("leaderTitle") or "").strip()
    
    # Check if contains Unleashed cards
    has_unl = False
    raw_cards = row.get("cards", {})
    if isinstance(raw_cards, dict):
        for raw_title in raw_cards.keys():
            card = cards.get(raw_title)
            if card and "unleashed" in str(card.set_name).lower():
                has_unl = True
                break
    elif isinstance(raw_cards, list):
        for item in raw_cards:
            if not isinstance(item, dict):
                continue
            t = item.get("card") or item.get("name") or ""
            card = cards.get(t)
            if card and "unleashed" in str(card.set_name).lower():
                has_unl = True
                break

    if has_unl:
        unl_count += 1

    from app.domain.normalization import coerce_cards_map
    cards_map = coerce_cards_map(row.get("cards"))
    legend, main, runes, battlefields = _split_components(cards_map, catalog=cards, leader_title=leader_title)
    chosen = _infer_champion(main, legend=legend, catalog=cards)

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
    validation = validate_deck(deck_payload, rules=rules, cards=cards)
    if not validation.is_valid:
        skipped += 1
        if has_unl:
            skipped_issues.append((deck_name, [i.message for i in validation.issues]))
    else:
        if has_unl:
            valid_unl_count += 1

print(f"Skipped decks due to validation: {skipped} / {len(rows)}")
print(f"Total Unleashed decks found in raw data: {unl_count}")
print(f"Valid Unleashed decks: {valid_unl_count}")
print(f"Skipped Unleashed decks issues (first 10):")
for name, iss in skipped_issues[:10]:
    print(f"  {name}: {iss}")
