"""Test fixtures.

Deliberately tiny and pure. In v2 the API test fixture called
``train_auto_builder_artifacts(...)`` -- it trained an NMF + MoE model before every
test -- so one numerical bug in the ML pipeline took down sixteen unrelated tests
covering auth, deck visibility and collection import. Nothing here loads a bundle,
touches the network, or imports a machine-learning library.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from riftbound.domain.cards import Card, Printing, build_catalog  # noqa: E402
from riftbound.domain.rules import FormatRules  # noqa: E402


def make_card(
    card_id: str,
    name: str = "",
    *,
    card_type: str = "Unit",
    super_type: str = "",
    domains: tuple[str, ...] = ("Fury",),
    domains_ok: bool = True,
    cost: int | None = 2,
    might: int | None = 2,
    tags: tuple[str, ...] = (),
    champion_tags: tuple[str, ...] = (),
    unique: bool = False,
    rarity: str = "Common",
    set_code: str = "OGN",
    promo: bool = False,
) -> Card:
    return Card(
        card_id=card_id,
        name=name or card_id.replace("-", " ").title(),
        card_type=card_type,
        super_type=super_type,
        domains=domains,
        domains_ok=domains_ok,
        cost=cost,
        might=might,
        tags=tags,
        champion_tags=champion_tags,
        effect="",
        flavor="",
        unique=unique,
        printings=(
            Printing(
                print_id=f"{set_code.lower()}-001-{card_id}",
                card_id=card_id,
                title=name or card_id,
                set_code=set_code,
                set_name=set_code,
                card_number="001",
                rarity=rarity,
                promo=promo,
                image_url="",
            ),
        ),
    )


@pytest.fixture()
def catalog():
    """A minimal but realistic catalogue: one legend, its champion, filler, runes."""
    cards = [
        make_card(
            "vi-piltover-enforcer", "Vi - Piltover Enforcer",
            card_type="Legend", domains=("Fury",), cost=None, might=None,
            tags=("Vi", "Piltover"), champion_tags=("Vi",),
        ),
        make_card(
            "vi-destructive", "Vi - Destructive",
            super_type="Champion", domains=("Fury",),
            tags=("Vi", "Piltover"), champion_tags=("Vi",), rarity="Rare",
        ),
        make_card("brazen-buccaneer", "Brazen Buccaneer", domains=("Fury",)),
        make_card("harpoon-squad", "Harpoon Squad", domains=("Fury",), rarity="Epic"),
        make_card("calm-intruder", "Calm Intruder", domains=("Calm",)),
        make_card(
            "singular-relic", "Singular Relic",
            card_type="Gear", domains=("Fury",), unique=True,
        ),
        make_card(
            "fury-rune", "Fury Rune",
            card_type="Rune", super_type="Basic", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "calm-rune", "Calm Rune",
            card_type="Rune", super_type="Basic", domains=("Calm",), cost=None, might=None,
        ),
        make_card(
            "the-arena", "The Arena",
            card_type="Battlefield", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "the-forge", "The Forge",
            card_type="Battlefield", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "the-spire", "The Spire",
            card_type="Battlefield", domains=("Fury",), cost=None, might=None,
        ),
        make_card(
            "showcase-only", "Showcase Only",
            domains=("Fury",), rarity="Showcase", promo=True, set_code="UNL",
        ),
        make_card("banned-blade", "Banned Blade", domains=("Fury",)),
    ]
    # Filler so a test deck can reach a legal 40 cards without noise.
    cards += [
        make_card(f"filler-{i:02d}", f"Filler {i:02d}", domains=("Fury",))
        for i in range(1, 10)
    ]
    return build_catalog(cards)


@pytest.fixture()
def rules():
    return FormatRules(
        format_name="constructed",
        description="test profile",
        constraints={
            "legend_required": True,
            "legend_card_type": "Legend",
            "chosen_champion_required": True,
            "champion_super_type": "Champion",
            "main_deck_size_exact": 40,
            "rune_count_exact": 12,
            "battlefield_count_exact": 3,
            "battlefield_unique_required": True,
            "main_copy_limit": 3,
            "combined_main_sideboard_copy_limit": 3,
            "sideboard_max": 8,
            "signature_max_total": 3,
            "domain_identity_enforced": True,
            "rune_card_type": "Rune",
            "battlefield_card_type": "Battlefield",
            "allowed_main_card_types": ["Unit", "Gear", "Spell"],
            "allowed_sideboard_card_types": ["Unit", "Gear", "Spell"],
            "banned_cards": ["Banned Blade"],
        },
        rule_refs={
            "main_deck_size": ["TR 402.1", "TR 601.1.b"],
            "main_copy_limit": ["CR 103.2.b"],
            "legend_required": ["CR 103.1"],
        },
    )


@pytest.fixture()
def bound_rules(rules, catalog):
    return rules.bind(catalog)


@pytest.fixture()
def legal_deck(catalog):
    """A deck that passes every check, for tests to perturb."""
    from riftbound.domain.deck import Deck

    main = {
        "vi-destructive": 3,
        "brazen-buccaneer": 3,
        "harpoon-squad": 3,
        "singular-relic": 1,
        "showcase-only": 3,
    }
    main.update({f"filler-{i:02d}": 3 for i in range(1, 10)})  # 13 + 27 = 40
    return Deck.make(
        name="Test Deck",
        legend_id="vi-piltover-enforcer",
        champion_id="vi-destructive",
        main=main,
        runes={"fury-rune": 12},
        battlefields=["the-arena", "the-forge", "the-spire"],
    )
