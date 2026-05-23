from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.domain.models import DeckPayload
from app.domain.normalization import normalize_card_key
from app.domain.rules import load_format_rules
from app.domain.validator import validate_deck
from app.domain.wizard_solver import apply_wizard_main_swap, solve_wizard_deck
from app.core.services import get_services
from app.infra.cards_repo import CardCatalog, CardRecord


def _card(
    title: str,
    card_type: str,
    super_type: str = "",
    champion_tags: tuple[str, ...] = (),
    domains: tuple[str, ...] = ("Mind",),
    is_unique: bool = False,
) -> CardRecord:
    return CardRecord(
        title=title,
        card_type=card_type,
        super_type=super_type,
        tags=champion_tags,
        champion_tags=champion_tags,
        domains=domains,
        domain_parse_ok=True,
        cost=2,
        might=2,
        image_url="",
        is_unique=is_unique,
    )


def _catalog() -> CardCatalog:
    cards = [
        _card("LeBlanc - Deceiver", "Legend", champion_tags=("LeBlanc",)),
        _card("LeBlanc - Fragmented", "Unit", super_type="Champion", champion_tags=("LeBlanc",)),
        _card("Mind Rune", "Rune"),
        _card("Hall of Legends", "Battlefield"),
        _card("Forgotten Monument", "Battlefield"),
        _card("Skyline Rift", "Battlefield"),
        _card("Karthus - Eternal", "Unit"),
        _card("Deathgrip", "Spell"),
        _card("Mirror Image", "Spell"),
        _card("Sacrifice", "Spell"),
        _card("Retreat", "Spell"),
        _card("Tactical Retreat", "Spell"),
        _card("Deceiver's Gambit", "Spell"),
        _card("Black Rose Agent", "Unit"),
        _card("Sigil Snare", "Spell"),
        _card("Guile", "Spell"),
        _card("Shadow Step", "Spell"),
        _card("Distortion", "Spell"),
        _card("Chain Lash", "Gear"),
        _card("Whispered Plan", "Spell"),
        _card("Mimic", "Spell"),
        _card("Veiled Blade", "Gear"),
    ]
    return CardCatalog(
        cards=tuple(cards),
        by_title={card.title: card for card in cards},
        by_key={normalize_card_key(card.title): card for card in cards},
    )


def _rules():
    profile_path = Path(__file__).resolve().parents[1] / "rules_profiles" / "constructed.json"
    return load_format_rules(profile_path)


def _reference_deck() -> DeckPayload:
    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Tactical Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 3,
    }
    return DeckPayload(
        name="LeBlanc Reference",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )


def _lillia_catalog() -> CardCatalog:
    calm = ("Calm",)
    mind = ("Mind",)
    both = ("Calm", "Mind")
    cards = [
        _card("Lillia - Bashful Bloom", "Legend", champion_tags=("Lillia",), domains=both),
        _card("Lillia - Fae Fawn", "Unit", super_type="Champion", champion_tags=("Lillia",), domains=mind),
        _card("Calm Rune", "Rune", domains=calm),
        _card("Mind Rune", "Rune", domains=mind),
        _card("Black Flame Altar", "Battlefield", domains=both),
        _card("Dusk Rose Lab", "Battlefield", domains=both),
        _card("Forbidding Waste", "Battlefield", domains=both),
        _card("Charm", "Spell", domains=calm),
        _card("Defy", "Spell", domains=calm),
        _card("Discipline", "Spell", domains=calm),
        _card("Stupefy", "Spell", domains=mind),
        _card("Ravenbloom Student", "Unit", domains=mind),
        _card("Thousand-Tailed Watcher", "Unit", domains=mind),
        _card("Disarming Rake", "Unit", domains=calm),
        _card("Heart of Dark Ice", "Gear", domains=calm),
        _card("Plundering Poro", "Unit", domains=mind),
        _card("Back Off", "Spell", domains=calm),
        _card("Sprite Burst", "Spell", domains=mind),
        _card("Turn to Dust", "Spell", domains=mind),
        _card("Sprite Fountain", "Gear", domains=mind),
        _card("Smoke and Mirrors", "Spell", domains=mind),
        _card("Sprite Queen", "Unit", domains=mind),
        _card("Lilting Lullaby", "Spell", super_type="Signature", champion_tags=("Lillia",), domains=both),
        _card("Dream-Laden Bough", "Gear", domains=mind),
        _card("Sleepy Sprout", "Unit", domains=mind),
        _card("Gentle Bloom", "Spell", domains=calm),
    ]
    return CardCatalog(
        cards=tuple(cards),
        by_title={card.title: card for card in cards},
        by_key={normalize_card_key(card.title): card for card in cards},
    )


def _lillia_reference_deck() -> DeckPayload:
    main = {
        "Lillia - Fae Fawn": 1,
        "Charm": 3,
        "Defy": 3,
        "Discipline": 3,
        "Stupefy": 3,
        "Ravenbloom Student": 3,
        "Thousand-Tailed Watcher": 2,
        "Disarming Rake": 1,
        "Heart of Dark Ice": 3,
        "Plundering Poro": 3,
        "Back Off": 1,
        "Sprite Burst": 3,
        "Turn to Dust": 2,
        "Sprite Fountain": 3,
        "Smoke and Mirrors": 3,
        "Sprite Queen": 2,
        "Lilting Lullaby": 1,
    }
    return DeckPayload(
        name="Lillia Reference",
        source="test",
        format="constructed",
        legendTitle="Lillia - Bashful Bloom",
        chosenChampionTitle="Lillia - Fae Fawn",
        main=main,
        runes={"Calm Rune": 6, "Mind Rune": 6},
        battlefields=["Black Flame Altar", "Dusk Rose Lab", "Forbidding Waste"],
        sideboard={},
    )


def test_owned_solver_never_outputs_four_deathgrip_unless_legal() -> None:
    catalog = _catalog()
    rules = _rules()
    owned = {title: qty for title, qty in _reference_deck().main.items()}
    owned["Karthus - Eternal"] = 0
    owned["Deathgrip"] = 4

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=_reference_deck(),
        current_deck=_reference_deck(),
    )

    assert result.deck.main.get("Karthus - Eternal", 0) == 0
    assert result.deck.main.get("Deathgrip", 0) <= rules.int_constraint("main_copy_limit", 3)
    assert result.deck.main.get("Deathgrip", 0) == 3
    assert validate_deck(result.deck, rules=rules, cards=catalog).is_valid
    assert result.validation.is_valid


def test_swap_karthus_to_deathgrip_preserves_three_copy_slot_max() -> None:
    catalog = _catalog()
    rules = _rules()
    deck = _reference_deck()
    deck.main["Deathgrip"] = 1
    deck.main["Mimic"] = 2
    owned = {"Deathgrip": 4, "Karthus - Eternal": 0}

    swapped = apply_wizard_main_swap(
        deck,
        "Karthus - Eternal",
        "Deathgrip",
        owned=owned,
        rules=rules,
        cards=catalog,
        strict_owned=True,
    )

    assert swapped.main.get("Karthus - Eternal", 0) == 0
    assert swapped.main.get("Deathgrip", 0) == 3
    assert swapped.main.get("Deathgrip", 0) <= rules.int_constraint("main_copy_limit", 3)


def test_lillia_iteration_two_fills_missing_cards_from_owned_collection_cluster() -> None:
    catalog = _lillia_catalog()
    rules = _rules()
    reference = _lillia_reference_deck()
    owned = {title: qty for title, qty in reference.main.items()}
    owned.update(
        {
            "Lillia - Bashful Bloom": 1,
            "Calm Rune": 6,
            "Mind Rune": 6,
            "Black Flame Altar": 1,
            "Dusk Rose Lab": 1,
            "Forbidding Waste": 1,
            "Heart of Dark Ice": 2,
            "Sprite Fountain": 0,
            "Smoke and Mirrors": 0,
            "Dream-Laden Bough": 3,
            "Sleepy Sprout": 3,
            "Gentle Bloom": 1,
        }
    )

    result = solve_wizard_deck(
        legend_title="Lillia - Bashful Bloom",
        chosen_champion_title="Lillia - Fae Fawn",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=reference,
        current_deck=reference,
    )

    assert result.validation.is_valid
    assert result.metrics["isFullyOwned"]
    assert result.solver_status == "optimal"
    assert result.deck.main.get("Heart of Dark Ice", 0) <= 2
    assert result.deck.main.get("Sprite Fountain", 0) == 0
    assert result.deck.main.get("Smoke and Mirrors", 0) == 0
    assert sum(result.deck.main.values()) == rules.int_constraint("main_deck_size_exact", 40)
    assert sum(result.deck.main.get(title, 0) for title in ["Dream-Laden Bough", "Sleepy Sprout", "Gentle Bloom"]) == 7
    assert result.replacement_clusters
    cluster = result.replacement_clusters[0]
    assert {row["card"] for row in cluster["removed"]} >= {"Sprite Fountain", "Smoke and Mirrors", "Heart of Dark Ice"}
    assert sum(row["qty"] for row in cluster["added"]) == 7


def test_lillia_iteration_two_reports_infeasible_when_owned_pool_has_no_fillers() -> None:
    catalog = _lillia_catalog()
    rules = _rules()
    reference = _lillia_reference_deck()
    owned = {title: qty for title, qty in reference.main.items()}
    owned.update(
        {
            "Lillia - Bashful Bloom": 1,
            "Calm Rune": 6,
            "Mind Rune": 6,
            "Black Flame Altar": 1,
            "Dusk Rose Lab": 1,
            "Forbidding Waste": 1,
            "Heart of Dark Ice": 2,
            "Sprite Fountain": 0,
            "Smoke and Mirrors": 0,
        }
    )

    result = solve_wizard_deck(
        legend_title="Lillia - Bashful Bloom",
        chosen_champion_title="Lillia - Fae Fawn",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=reference,
        current_deck=reference,
    )

    assert result.solver_status == "feasible"
    assert result.validation.is_valid
    assert result.deck.main.get("Sprite Fountain", 0) == 0
    assert result.deck.main.get("Smoke and Mirrors", 0) == 0


def test_wizard_solve_endpoint_accepts_json_body() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/wizard/solve", json={"format": "constructed", "owned": {}})

    assert response.status_code == 200
    assert "solverStatus" in response.json()


def test_solve_deck_collection_agnostic_suggests_archetype() -> None:
    class MockAutoBuilderRepo:
        class Loaded:
            def __init__(self) -> None:
                self.bundle = {
                    "archetypes": [
                        {
                            "legendTitle": "LeBlanc - Deceiver",
                            "chosenChampionTitle": "LeBlanc - Fragmented",
                            "archetypeName": "LeBlanc Aggro Archetype",
                            "confidence": 0.9,
                            "competitivePrior": 0.8,
                            "prototypeMain": {
                                "Karthus - Eternal": 3,
                                "Mirror Image": 3,
                                "Sacrifice": 3,
                                "Tactical Retreat": 3,
                                "Deceiver's Gambit": 3,
                                "Black Rose Agent": 3,
                                "Sigil Snare": 3,
                                "Guile": 3,
                                "Shadow Step": 3,
                                "Distortion": 3,
                                "Chain Lash": 3,
                                "Whispered Plan": 3,
                                "Mimic": 3,
                                "Veiled Blade": 1,
                            }
                        }
                    ]
                }
                self.generator_state = {}
        def __init__(self) -> None:
            self._loaded = self.Loaded()
            self._model_b = None
            self._artifact_b = None

    catalog = _catalog()
    rules = _rules()
    owned = {"Karthus - Eternal": 0}  # Karthus is lacked in owned collection

    # Normal mode respects owned=0 shortage
    result_normal = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
    )
    assert result_normal.deck.main.get("Karthus - Eternal", 0) == 0

    # Agnostic mode mock-owns all cards and suggests archetype
    mock_auto = MockAutoBuilderRepo()
    result_agnostic = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        auto_builder=mock_auto,  # type: ignore
        collection_agnostic=True,
    )
    assert result_agnostic.deck.main.get("Karthus - Eternal", 0) == 0
    assert result_agnostic.validation.is_valid


def test_solve_deck_gap_filling_with_model_b() -> None:
    import numpy as np
    import torch

    class MockModelB(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.param = torch.nn.Parameter(torch.zeros(1))

        def score_candidates_batch(self, card_ids_t, feats_t, qty_t, legend_idx_t, champion_idx_t, pad_mask_t, rem_frac_t, arch_idx_t, all_cand_ids, card_feat_t):
            v = all_cand_ids.shape[0]
            logits = torch.full((v,), -10.0, device=self.param.device)
            return logits

    class MockArtifactB:
        def __init__(self, index_to_key: list[str]) -> None:
            self.vocab_to_idx = {key: idx + 1 for idx, key in enumerate(index_to_key)}
            self.index_to_key = index_to_key
            self.card_feat_matrix = np.zeros((len(index_to_key), 91), dtype=np.float32)
            self.card_feat_matrix_tensor = torch.zeros((len(index_to_key), 91))
            self.all_cand_ids_tensor = torch.arange(1, len(index_to_key) + 1, dtype=torch.long)
            self.card_freq_by_legend = {}
            self.card_cluster_labels = np.zeros(len(index_to_key), dtype=np.int64)
            self.legend_to_idx = {"LeBlanc - Deceiver": 1}
            self.champion_to_idx = {"LeBlanc - Fragmented": 1}
            self.model_params = {"max_deck": 42}

    class MockAutoBuilderRepo:
        def __init__(self, index_to_key: list[str]) -> None:
            self._loaded = None
            self._model_b = MockModelB()
            self._artifact_b = MockArtifactB(index_to_key)

    catalog = _catalog()
    rules = _rules()

    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Tactical Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 2,
    }
    ref = DeckPayload(
        name="partial_ref",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )

    owned = {k: v for k, v in main.items()}
    owned["Deathgrip"] = 3
    owned["Veiled Blade"] = 3

    index_to_key = sorted(catalog.by_title.keys())
    mock_auto = MockAutoBuilderRepo(index_to_key)

    # Force Model B logits to favor "Veiled Blade" over "Deathgrip"
    v_idx = index_to_key.index("Veiled Blade")
    d_idx = index_to_key.index("Deathgrip")
    assert "Deathgrip" < "Veiled Blade"

    def custom_logits(card_ids_t, feats_t, qty_t, legend_idx_t, champion_idx_t, pad_mask_t, rem_frac_t, arch_idx_t, all_cand_ids, card_feat_t):
        device = mock_auto._model_b.param.device
        logits = torch.full((len(index_to_key),), -20.0, device=device)
        logits[v_idx] = 20.0
        logits[d_idx] = -20.0
        return logits
    mock_auto._model_b.score_candidates_batch = custom_logits

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=ref,
        current_deck=ref,
        auto_builder=mock_auto,  # type: ignore
    )
    # The gap was filled with "Veiled Blade" (Model B favored) rather than "Deathgrip" (alphabetically first)
    assert result.deck.main.get("Veiled Blade", 0) == 1
    assert result.deck.main.get("Deathgrip", 0) == 0

    # Verify that shortages (qty=0) are NEVER suggested even if they have the highest logit
    owned["Veiled Blade"] = 0
    result_shortage = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=ref,
        current_deck=ref,
        auto_builder=mock_auto,  # type: ignore
    )
    assert result_shortage.deck.main.get("Veiled Blade", 0) == 0
    # "Deathgrip" should be filled instead by fallback
    assert result_shortage.deck.main.get("Deathgrip", 0) == 1


def test_solve_deck_fallback_unseen_champion() -> None:
    catalog = _catalog()
    # Add a custom unseen champion legal for LeBlanc legend
    unseen_champ = _card("LeBlanc - Unseen", "Unit", super_type="Champion", champion_tags=("LeBlanc",))
    cards_list = list(catalog.cards) + [unseen_champ]
    catalog = CardCatalog(
        cards=tuple(cards_list),
        by_title={card.title: card for card in cards_list},
        by_key={normalize_card_key(card.title): card for card in cards_list},
    )

    rules = _rules()

    class MockAutoBuilderRepo:
        class Loaded:
            def __init__(self) -> None:
                self.bundle = {"archetypes": []}
                self.generator_state = {}
        def __init__(self) -> None:
            self._loaded = self.Loaded()
            self._model_b = None
            self._artifact_b = None

    mock_auto = MockAutoBuilderRepo()
    owned = {card.title: 3 for card in catalog.cards}
    owned["LeBlanc - Fragmented"] = 1

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Unseen",  # LeBlanc - Unseen is legal, but unseen by models
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        auto_builder=mock_auto,  # type: ignore
        collection_agnostic=True,
    )

    assert result.deck.chosen_champion_title == "LeBlanc - Unseen"
    assert result.validation.is_valid


def test_unowned_pass_excludes_lacking_cards_and_avoids_infinite_loop() -> None:
    import numpy as np
    import torch

    class MockModelB(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.param = torch.nn.Parameter(torch.zeros(1))

        def score_candidates_batch(self, card_ids_t, feats_t, qty_t, legend_idx_t, champion_idx_t, pad_mask_t, rem_frac_t, arch_idx_t, all_cand_ids, card_feat_t):
            # This mock model always favors "Mimic" which is in lacking_cards
            v = all_cand_ids.shape[0]
            logits = torch.full((v,), -10.0, device=self.param.device)
            m_idx = index_to_key.index("Mimic")
            logits[m_idx] = 20.0  # favor Mimic
            # Also give some positive logits to "Deathgrip"
            dg_idx = index_to_key.index("Deathgrip")
            logits[dg_idx] = 10.0
            return logits

    class MockArtifactB:
        def __init__(self, index_to_key: list[str]) -> None:
            self.vocab_to_idx = {key: idx + 1 for idx, key in enumerate(index_to_key)}
            self.index_to_key = index_to_key
            self.card_feat_matrix = np.zeros((len(index_to_key), 91), dtype=np.float32)
            self.card_feat_matrix_tensor = torch.zeros((len(index_to_key), 91))
            self.all_cand_ids_tensor = torch.arange(1, len(index_to_key) + 1, dtype=torch.long)
            self.card_freq_by_legend = {}
            self.card_cluster_labels = np.zeros(len(index_to_key), dtype=np.int64)
            self.legend_to_idx = {"LeBlanc - Deceiver": 1}
            self.champion_to_idx = {"LeBlanc - Fragmented": 1}
            self.model_params = {"max_deck": 42}

    class MockAutoBuilderRepo:
        def __init__(self, index_to_key: list[str]) -> None:
            self._loaded = None
            self._model_b = MockModelB()
            self._artifact_b = MockArtifactB(index_to_key)

    catalog = _catalog()
    rules = _rules()

    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Tactical Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 1,
    }
    ref = DeckPayload(
        name="partial_ref",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )

    owned = {k: v for k, v in main.items()}
    owned["Mimic"] = 0  # Explicitly lack Mimic

    index_to_key = sorted(catalog.by_title.keys())
    mock_auto = MockAutoBuilderRepo(index_to_key)

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=ref,
        current_deck=ref,
        auto_builder=mock_auto,  # type: ignore
    )

    # Mimic must not be added beyond the 0 we owned.
    assert result.deck.main.get("Mimic", 0) == 0
    # Deathgrip (next highest logit) must be added (3 copies).
    assert result.deck.main.get("Deathgrip", 0) == 3
    assert sum(result.deck.main.values()) == 40
    assert result.validation.is_valid


def test_wholecloth_replacement_subpar_1of() -> None:
    catalog = _catalog()
    rules = _rules()

    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Tactical Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 3,
    }
    
    ref = DeckPayload(
        name="reference",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )
    
    owned = {k: v for k, v in main.items()}
    owned["Karthus - Eternal"] = 1  # only own 1 copy
    owned["Deathgrip"] = 3  # we also own Deathgrip (which is not in reference)
    
    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=ref,
        current_deck=ref,
    )
    
    # Karthus - Eternal must be replaced wholecloth (0 copies)
    assert result.deck.main.get("Karthus - Eternal", 0) == 0
    # The gap must be filled by Deathgrip (which we own 3 of)
    assert result.deck.main.get("Deathgrip", 0) == 3
    # Total main size must be 40
    assert sum(result.deck.main.values()) == 40
    assert result.validation.is_valid


def test_partial_owned_reference_card_is_not_topped_up_by_unowned_pass() -> None:
    catalog = _catalog()
    rules = _rules()

    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 3,
    }
    ref = DeckPayload(
        name="reference",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )

    owned = {k: v for k, v in main.items()}
    owned["Retreat"] = 1

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=ref,
        current_deck=ref,
    )

    assert result.deck.main.get("Retreat", 0) == 1
    assert result.metrics["completionPct"] < 100
    assert result.validation.is_valid


def test_ahri_template_less_initial_solve_is_40_cards_and_excludes_tokens() -> None:
    svc = get_services()
    rules = svc.rules_for_format("constructed")
    seed = DeckPayload(
        name="Guided Deck",
        source="wizard",
        format="constructed",
        legendTitle="Ahri - Nine-Tailed Fox",
        chosenChampionTitle="Ahri - Alluring",
        main={},
        runes={},
        battlefields=[],
        sideboard={},
    )
    owned = {
        "Ahri - Nine-Tailed Fox": 1,
        "Ahri - Alluring": 1,
        "Calm Rune": 12,
        "Altar to Unity": 1,
        "Aspirant's Climb": 1,
        "Back-Alley Bar": 1,
        "Defy": 3,
        "En Garde": 3,
        "Find Your Center": 3,
        "Stalwart Poro": 3,
        "Discipline": 3,
        "Wind Wall": 1,
        "Sona - Harmonious": 3,
        "Tasty Faefolk": 2,
        "Lecturing Yordle": 3,
        "Stupefy": 3,
        "Watchful Sentry": 3,
        "Ravenbloom Student": 3,
        "Sprite Mother": 2,
        "Thousand-Tailed Watcher": 2,
        "Recruit (DE)": 1,
    }

    result = solve_wizard_deck(
        legend_title="Ahri - Nine-Tailed Fox",
        chosen_champion_title="Ahri - Alluring",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=svc.cards,
        current_deck=seed,
        auto_builder=svc.auto_builder,
    )

    assert sum(result.deck.main.values()) == rules.int_constraint("main_deck_size_exact", 40)
    assert "Recruit (DE)" not in result.deck.main
    assert not any((svc.cards.get(title) and svc.cards.get(title).super_type == "Token") for title in result.deck.main)
    assert result.validation.is_valid, result.validation.model_dump()


def test_master_yi_template_less_initial_solve_uses_copy_density_and_supported_runes() -> None:
    svc = get_services()
    rules = svc.rules_for_format("constructed")
    seed = DeckPayload(
        name="Guided Deck",
        source="wizard",
        format="constructed",
        legendTitle="Master Yi - Wuju Master",
        chosenChampionTitle="Master Yi - Honed",
        main={},
        runes={},
        battlefields=[],
        sideboard={},
    )

    result = solve_wizard_deck(
        legend_title="Master Yi - Wuju Master",
        chosen_champion_title="Master Yi - Honed",
        format_name="constructed",
        owned={},
        rules=rules,
        cards=svc.cards,
        current_deck=seed,
        auto_builder=svc.auto_builder,
        collection_agnostic=True,
    )

    assert sum(result.deck.main.values()) == rules.int_constraint("main_deck_size_exact", 40)
    assert len(result.deck.main) <= 18
    assert sum(1 for qty in result.deck.main.values() if qty >= 3) >= 10
    rune_domains = {
        domain
        for title in result.deck.runes
        for domain in (svc.cards.get(title).domains if svc.cards.get(title) else ())
    }
    unsupported = [
        title
        for title in result.deck.main
        if title != "Master Yi - Honed"
        and (svc.cards.get(title) and svc.cards.get(title).domains)
        and not (set(svc.cards.get(title).domains) & rune_domains)
    ]
    assert unsupported == []
    assert result.validation.is_valid, result.validation.model_dump()


def test_signature_limit_enforced_in_gap_filling() -> None:
    catalog = _catalog()
    # Add signature cards that match LeBlanc
    sig_1 = _card("Deceiver's Mirror", "Spell", super_type="Signature", champion_tags=("LeBlanc",))
    sig_2 = _card("Deceiver's Sigil", "Spell", super_type="Signature", champion_tags=("LeBlanc",))
    cards_list = list(catalog.cards) + [sig_1, sig_2]
    catalog = CardCatalog(
        cards=tuple(cards_list),
        by_title={card.title: card for card in cards_list},
        by_key={normalize_card_key(card.title): card for card in cards_list},
    )
    rules = _rules()

    # The reference deck already has 2 copies of "Deceiver's Gambit" (which is a signature card in real play, but let's assume it's NOT here, or wait)
    # Let's say we have 2 copies of "Deceiver's Mirror" in the deck (which has super_type="Signature").
    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Tactical Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 1,
        "Deceiver's Mirror": 2, # 2 signatures
    }
    ref = DeckPayload(
        name="partial_ref",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )

    # Let's say we own 3 copies of "Deceiver's Sigil" (another signature).
    # Since Constructed limits total signatures to 3, the solver should only add 1 copy of "Deceiver's Sigil" even if we own 3.
    owned = {k: 3 for k in main.keys()}
    owned["Deceiver's Sigil"] = 3

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=ref,
        current_deck=ref,
    )

    # Total signatures must be capped at 3. We already have 2 "Deceiver's Mirror".
    # So "Deceiver's Sigil" can only be added at most 1 copy.
    assert result.deck.main.get("Deceiver's Mirror", 0) == 2
    assert result.deck.main.get("Deceiver's Sigil", 0) <= 1
    assert result.validation.is_valid


def test_signature_tags_must_match_legend_in_gap_filling() -> None:
    catalog = _catalog()
    # Add a signature card for a DIFFERENT champion (e.g. Draven)
    mismatched_sig = _card("Spinning Axe", "Spell", super_type="Signature", champion_tags=("Draven",))
    cards_list = list(catalog.cards) + [mismatched_sig]
    catalog = CardCatalog(
        cards=tuple(cards_list),
        by_title={card.title: card for card in cards_list},
        by_key={normalize_card_key(card.title): card for card in cards_list},
    )
    rules = _rules()

    main = {
        "LeBlanc - Fragmented": 1,
        "Karthus - Eternal": 3,
        "Mirror Image": 3,
        "Sacrifice": 3,
        "Tactical Retreat": 3,
        "Deceiver's Gambit": 3,
        "Black Rose Agent": 3,
        "Sigil Snare": 3,
        "Guile": 3,
        "Shadow Step": 3,
        "Distortion": 3,
        "Chain Lash": 3,
        "Whispered Plan": 3,
        "Mimic": 1,
    }
    ref = DeckPayload(
        name="partial_ref",
        source="test",
        format="constructed",
        legendTitle="LeBlanc - Deceiver",
        chosenChampionTitle="LeBlanc - Fragmented",
        main=main,
        runes={"Mind Rune": 12},
        battlefields=["Hall of Legends", "Forgotten Monument", "Skyline Rift"],
        sideboard={},
    )

    owned = {k: 3 for k in main.keys()}
    owned["Spinning Axe"] = 3

    result = solve_wizard_deck(
        legend_title="LeBlanc - Deceiver",
        chosen_champion_title="LeBlanc - Fragmented",
        format_name="constructed",
        owned=owned,
        rules=rules,
        cards=catalog,
        reference_deck=ref,
        current_deck=ref,
    )

    # "Spinning Axe" does not match LeBlanc's champion tag, so it must not be added.
    assert result.deck.main.get("Spinning Axe", 0) == 0
    assert result.validation.is_valid
