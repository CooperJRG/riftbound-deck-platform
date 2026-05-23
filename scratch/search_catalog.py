import json
from pathlib import Path

ROOT = Path(r"c:\Users\coope\Documents\Riftbound Test\riftbound-deck-platform-v2")
with open(ROOT / "riftbound-cards.json", "r", encoding="utf-8") as f:
    cards = json.load(f)

print("Total cards in json:", len(cards))
titles = [c.get("title") for c in cards if isinstance(c, dict)]
print("Sample titles:", titles[:15])

import json
from pathlib import Path

ROOT = Path(r"c:\Users\coope\Documents\Riftbound Test\riftbound-deck-platform-v2")
with open(ROOT / "riftbound-cards.json", "r", encoding="utf-8") as f:
    cards = json.load(f)

print("Total cards in json:", len(cards))

target_titles = ["Gold", "Obelisk of Power", "The Dreaming Tree"]
for t in target_titles:
    matches = [c for c in cards if t.lower() in str(c.get("title")).lower()]
    print(f"\nSearching for '{t}':")
    for m in matches:
        print(f"  Found: Title: {m.get('title')}, Set: {m.get('set')}, CardNumber: {m.get('cardNumber')}, Domains: {m.get('domains')}, Rarity: {m.get('rarity')}, CardType: {m.get('cardType')}")
