from __future__ import annotations

from app.domain.models import AutoBuilderRecommendationRequest, ModelObservationTrainingRequest


def test_auto_builder_request_accepts_camel_case_without_mutating_card_titles() -> None:
    body = AutoBuilderRecommendationRequest.model_validate(
        {
            "rankingMode": "collection",
            "collectionOverride": {
                "Mind Spell": 2,
                "Champion A": 1,
            },
        }
    )
    assert body.ranking_mode == "collection"
    assert body.collection_override == {
        "Mind Spell": 2,
        "Champion A": 1,
    }


def test_model_observation_training_request_accepts_camel_case_nested_payloads() -> None:
    body = ModelObservationTrainingRequest.model_validate(
        {
            "torchDevice": "cpu",
            "minWinConditionCount": 12,
            "syntheticCollection": {
                "packMin": 24,
                "packMax": 32,
                "scenarioCount": 2,
                "runeUnlimited": True,
            },
        }
    )
    assert body.torch_device == "cpu"
    assert body.min_win_condition_count == 12
    assert body.synthetic_collection is not None
    assert body.synthetic_collection.pack_min == 24
    assert body.synthetic_collection.pack_max == 32
    assert body.synthetic_collection.scenario_count == 2
    assert body.synthetic_collection.rune_unlimited is True
