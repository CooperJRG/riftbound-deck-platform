from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import platform
import pickle
from pathlib import Path
import threading
from typing import Any
import warnings

import numpy as np
import sklearn
import torch

from app.domain.analysis import analyze_collection_completion
from app.domain.auto_builder_features import build_card_static_features, deck_main_from_payload, deck_signature_from_main
from app.domain.auto_builder_generation import adapt_seed_candidate, build_candidate_payload, build_generation_plans, generate_pure_candidate, generation_defaults, prewarm_auto_builder_runtime, prototype_candidate, rank_replacements_for_missing_card
from app.domain.auto_builder_scoring import resolved_ranking_mode
from app.domain.auto_builder_training import _resolve_torch_device
from app.domain.auto_builder_types import LoadedAutoBuilderBundle
from app.domain.models import CardReplacementSuggestion, DeckPayload, ReplacementOption
from app.domain.normalization import normalize_card_key
from app.domain.validator import validate_deck
from app.infra.cards_repo import CardCatalog
from app.infra.meta_repo import MetaDeckIndexEntry, MetaDeckRepository
from app.infra.pricing_repo import BaseCardPriceRepository

logger = logging.getLogger(__name__)


def _runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": str(np.__version__),
        "sklearn": str(getattr(sklearn, "__version__", "")),
        "torch": str(getattr(torch, "__version__", "")),
    }


class AutoBuilderRepository:
    def __init__(self, path: Path, *, meta: MetaDeckRepository, cards: CardCatalog, rules, prices: BaseCardPriceRepository, enabled: bool = True):
        self._path = path
        self._meta = meta
        self._cards = cards
        self._rules = rules
        self._prices = prices
        self._enabled = bool(enabled)
        self._loaded: LoadedAutoBuilderBundle | None = None
        self._last_loaded_at: str | None = None
        self._last_error: str | None = None
        self._runtime_warnings: list[str] = []
        self._profiles_by_ref: dict[tuple[str, str], dict[str, Any]] = {}
        self._profiles_by_signature: dict[str, dict[str, Any]] = {}
        # Load bundle in background so app startup is fast; first recommend may wait for load.
        t = threading.Thread(target=self.refresh, kwargs={"force": True}, name="auto-builder-load", daemon=True)
        t.start()

    def refresh(self, *, force: bool = False) -> None:
        if not self._enabled:
            self._loaded = None
            self._last_error = None
            self._runtime_warnings = []
            return
        metadata_path = self._path / "metadata.json"
        bundle_path = self._path / "sklearn_bundle.joblib"
        embeddings_path = self._path / "card_embeddings.pt"
        generator_path = self._path / "generator_moe.pt"
        win_conditions_path = self._path / "win_condition_components.json"
        synergy_path = self._path / "synergy_clusters.json"
        shell_profiles_path = self._path / "shell_profiles.json"
        archetypes_path = self._path / "archetypes.json"
        if not metadata_path.is_file() or not bundle_path.is_file() or not embeddings_path.is_file() or not generator_path.is_file():
            self._last_error = None
            self._runtime_warnings = []
            return
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            runtime_versions = _runtime_versions()
            artifact_sklearn = str(metadata.get("sklearnVersion") or "")
            runtime_sklearn = runtime_versions["sklearn"]
            runtime_warnings: list[str] = []
            if artifact_sklearn and artifact_sklearn != runtime_sklearn:
                runtime_warnings.append(
                    f"sklearn artifact {artifact_sklearn} loaded on runtime {runtime_sklearn}; verify recommendations before promoting retrained artifacts."
                )
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")
                with bundle_path.open("rb") as fh:
                    bundle = pickle.load(fh)
                raw_embeddings = torch.load(embeddings_path, map_location="cpu")
                raw_generator = torch.load(generator_path, map_location="cpu")
            for item in caught_warnings:
                message = " ".join(str(item.message).split())
                if message and message not in runtime_warnings:
                    runtime_warnings.append(message)
            win_conditions = tuple(json.loads(win_conditions_path.read_text(encoding="utf-8"))) if win_conditions_path.is_file() else tuple()
            synergy_clusters = tuple(json.loads(synergy_path.read_text(encoding="utf-8"))) if synergy_path.is_file() else tuple()
            shell_profiles = tuple(json.loads(shell_profiles_path.read_text(encoding="utf-8"))) if shell_profiles_path.is_file() else tuple()
            archetypes = tuple(json.loads(archetypes_path.read_text(encoding="utf-8"))) if archetypes_path.is_file() else tuple()
            card_embeddings = {str(key): list(value) for key, value in dict(raw_embeddings.get("vectors") or {}).items()}
            bundle["cardEmbeddings"] = card_embeddings
            card_text_embeddings = {str(key): list(value) for key, value in dict(raw_embeddings.get("textVectors") or {}).items()}
            bundle["cardTextEmbeddings"] = card_text_embeddings
            bundle["generatorState"] = raw_generator
            bundle["winConditions"] = list(win_conditions)
            bundle["synergyClusters"] = list(synergy_clusters)
            if shell_profiles:
                bundle["shellProfiles"] = {str(item.get("shell_id", item.get("shellId", ""))): item for item in shell_profiles if str(item.get("shell_id", item.get("shellId", "")))}
            if archetypes:
                bundle["archetypes"] = list(archetypes)
            loaded = LoadedAutoBuilderBundle(
                metadata=metadata,
                bundle=bundle,
                card_embeddings=card_embeddings,
                generator_state=raw_generator,
                win_conditions=tuple(),
                synergy_clusters=tuple(),
            )
            profiles_by_ref: dict[tuple[str, str], dict[str, Any]] = {}
            profiles_by_signature: dict[str, dict[str, Any]] = {}
            for row in bundle.get("deckProfiles") or []:
                key = (str(row.get("source") or "").lower(), str(row.get("deckId") or "").lower())
                profiles_by_ref[key] = row
                signature = str(row.get("deckSignature") or "")
                if signature:
                    profiles_by_signature[signature] = row
            self._loaded = loaded
            self._last_loaded_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None
            self._runtime_warnings = runtime_warnings[:6]
            self._profiles_by_ref = profiles_by_ref
            self._profiles_by_signature = profiles_by_signature
            try:
                prewarm_auto_builder_runtime(bundle=loaded.bundle, generator_state=loaded.generator_state, cards=self._cards)
            except Exception as prewarm_exc:
                logger.warning("Auto Builder prewarm skipped: %s", prewarm_exc)
            for message in self._runtime_warnings:
                logger.warning("Auto Builder compatibility warning: %s", message)
        except Exception as exc:
            self._last_error = str(exc)
            self._runtime_warnings = []

    def status(self) -> dict[str, object]:
        meta = self._loaded.metadata if self._loaded is not None else {}
        defaults = generation_defaults()
        runtime_versions = _runtime_versions()
        generator_state = self._loaded.generator_state if self._loaded is not None else {}
        return {
            "enabled": bool(self._enabled),
            "modelDir": str(self._path),
            "generatedAt": meta.get("generatedAt"),
            "trainingDeckCount": int(meta.get("trainingDeckCount") or 0),
            "cardCount": int(meta.get("cardCount") or 0),
            "winConditionCount": int(meta.get("winConditionCount") or 0),
            "synergyClusterCount": int(meta.get("synergyClusterCount") or 0),
            "sourceCounts": dict(meta.get("sourceCounts") or {}),
            "uniqueShellCount": int(meta.get("uniqueShellCount") or 0),
            "archetypeCount": int(meta.get("archetypeCount") or 0),
            "defaultMinResults": int(meta.get("defaultMinResults") or defaults["minResultsTarget"]),
            "maxVariantsPerShell": int(meta.get("maxVariantsPerShell") or defaults["maxVariantsPerShell"]),
            "artifactSklearnVersion": str(meta.get("sklearnVersion") or ""),
            "runtimeSklearnVersion": runtime_versions["sklearn"],
            "artifactTorchVersion": str(meta.get("torchVersion") or ""),
            "runtimeTorchVersion": runtime_versions["torch"],
            "trainingTorchDevice": str(meta.get("torchDevice") or ""),
            "runtimeTorchDevice": _resolve_torch_device(None).type,
            "trainingMetrics": dict(meta.get("trainingMetrics") or {}),
            "selectedWinConditionCount": int(meta.get("selectedWinConditionCount") or meta.get("winConditionCount") or 0),
            "selectedSynergyClusterCount": int(meta.get("selectedSynergyClusterCount") or meta.get("synergyClusterCount") or 0),
            "candidateWinConditionCounts": [int(value) for value in list(meta.get("candidateWinConditionCounts") or [])],
            "candidateSynergyClusterCounts": [int(value) for value in list(meta.get("candidateSynergyClusterCounts") or [])],
            "winConditionSelectionMetrics": dict(meta.get("winConditionSelectionMetrics") or {}),
            "synergySelectionMetrics": dict(meta.get("synergySelectionMetrics") or {}),
            "resolutionSelectionMode": str(meta.get("resolutionSelectionMode") or ""),
            "resolutionReferenceArtifact": str(meta.get("resolutionReferenceArtifact") or ""),
            "generatorWinVectorSize": int(meta.get("generatorWinVectorSize") or generator_state.get("winVectorSize") or 0),
            "generatorClusterVectorSize": int(meta.get("generatorClusterVectorSize") or generator_state.get("clusterVectorSize") or 0),
            "embeddingNeighborCount": int(meta.get("embeddingNeighborCount") or 0),
            "strictBuildableRecommendationHitRate": float(meta.get("strictBuildableRecommendationHitRate") or 0.0),
            "strictBuildableEmptyResultRate": float(meta.get("strictBuildableEmptyResultRate") or 0.0),
            "sourceHealth": dict(meta.get("sourceHealth") or {}),
            "lastLoadedAt": self._last_loaded_at,
            "runtimeWarnings": list(self._runtime_warnings),
            "lastError": self._last_error,
        }

    def win_conditions(self) -> list[dict[str, Any]]:
        if self._loaded is None:
            return []
        shell_coverage = {int(key): int(value) for key, value in dict(self._loaded.bundle.get("shellCoverageByWinCondition") or {}).items()}
        archetype_count = {int(key): int(value) for key, value in dict(self._loaded.bundle.get("archetypeCountByWinCondition") or {}).items()}
        rows = []
        for row in self._loaded.bundle.get("winConditions") or []:
            wc_id = int(row.get("component_id", row.get("componentId", 0)))
            rows.append({
                "id": wc_id,
                "label": str(row.get("label") or ""),
                "topCards": list(row.get("top_cards") or row.get("topCards") or []),
                "topEffectTokens": list(row.get("top_effect_tokens") or row.get("topEffectTokens") or []),
                "sampleDeckCount": int(row.get("sample_deck_count", row.get("sampleDeckCount", 0)) or 0),
                "avgCompetitiveScore": float(row.get("avg_competitive_score", row.get("avgCompetitiveScore", 0.0)) or 0.0),
                "shellCoverageCount": int(row.get("shell_coverage_count", row.get("shellCoverageCount", shell_coverage.get(wc_id, 0))) or 0),
                "archetypeCount": int(row.get("archetype_count", row.get("archetypeCount", archetype_count.get(wc_id, 0))) or 0),
            })
        return rows

    def observation_snapshot(self, *, shell_limit: int = 24, archetype_limit: int = 48, synergy_limit: int = 72) -> dict[str, Any]:
        if self._loaded is None:
            return {
                "summary": {},
                "sources": {},
                "winConditions": [],
                "synergyClusters": [],
                "shells": [],
                "archetypes": [],
            }
        bundle = self._loaded.bundle
        metadata = self._loaded.metadata
        raw_shell_profiles = bundle.get("shellProfiles") or {}
        if isinstance(raw_shell_profiles, dict):
            shell_values = list(raw_shell_profiles.values())
        else:
            shell_values = list(raw_shell_profiles)
        shells = sorted(
            (
                {
                    "shellId": str(row.get("shellId", row.get("shell_id", "")) or ""),
                    "shellLabel": str(row.get("shellLabel", row.get("shell_label", "")) or ""),
                    "legendTitle": str(row.get("legendTitle", row.get("legend_title", "")) or ""),
                    "chosenChampionTitle": str(row.get("chosenChampionTitle", row.get("chosen_champion_title", "")) or ""),
                    "legendDomains": list(row.get("legendDomains", row.get("legend_domains", [])) or []),
                    "trainingDeckCount": int(row.get("trainingDeckCount", row.get("training_deck_count", 0)) or 0),
                    "archetypeCount": int(row.get("archetypeCount", row.get("archetype_count", 0)) or 0),
                    "competitivePrior": float(row.get("competitivePrior", row.get("competitive_prior", 0.0)) or 0.0),
                    "buildabilityPrior": float(row.get("buildabilityPrior", row.get("buildability_prior", 0.0)) or 0.0),
                    "buildableConversion": float(row.get("buildableConversion", row.get("buildable_conversion", 0.0)) or 0.0),
                    "sourceBreakdown": dict(row.get("sourceBreakdown", row.get("source_breakdown", {})) or {}),
                }
                for row in shell_values
            ),
            key=lambda row: (-float(row["competitivePrior"]), -float(row["buildabilityPrior"]), row["shellLabel"].lower()),
        )[: max(1, int(shell_limit))]
        archetypes = sorted(
            (
                {
                    "archetypeId": str(row.get("archetypeId", row.get("archetype_id", "")) or ""),
                    "shellId": str(row.get("shellId", row.get("shell_id", "")) or ""),
                    "archetypeName": str(row.get("archetypeName", row.get("archetype_name", "")) or ""),
                    "legendTitle": str(row.get("legendTitle", row.get("legend_title", "")) or ""),
                    "chosenChampionTitle": str(row.get("chosenChampionTitle", row.get("chosen_champion_title", "")) or ""),
                    "prototypeMain": dict(row.get("prototypeMain", row.get("prototype_main", {})) or {}),
                    "topCoreCards": list(row.get("topCoreCards", row.get("top_core_cards", [])) or []),
                    "topFlexCards": list(row.get("topFlexCards", row.get("top_flex_cards", [])) or []),
                    "competitivePrior": float(row.get("competitivePrior", row.get("competitive_prior", 0.0)) or 0.0),
                    "buildabilityPrior": float(row.get("buildabilityPrior", row.get("buildability_prior", 0.0)) or 0.0),
                    "buildableConversion": float(row.get("buildableConversion", row.get("buildable_conversion", 0.0)) or 0.0),
                    "confidence": float(row.get("confidence", 0.0) or 0.0),
                    "winConditionId": int(row.get("winConditionId", row.get("win_condition_id", 0)) or 0),
                    "synergyClusterIds": list(row.get("synergyClusterIds", row.get("synergy_cluster_ids", [])) or []),
                    "synergyClusterLabels": list(row.get("synergyClusterLabels", row.get("synergy_cluster_labels", [])) or []),
                    "sourceBreakdown": dict(row.get("sourceBreakdown", row.get("source_breakdown", {})) or {}),
                }
                for row in list(bundle.get("archetypes") or [])
            ),
            key=lambda row: (-float(row["competitivePrior"]), -float(row["buildabilityPrior"]), -float(row["confidence"]), row["archetypeName"].lower()),
        )[: max(1, int(archetype_limit))]
        synergy_clusters = []
        for row in list(bundle.get("synergyClusters") or [])[: max(1, int(synergy_limit))]:
            synergy_clusters.append(
                {
                    "id": int(row.get("cluster_id", row.get("id", row.get("clusterId", 0))) or 0),
                    "label": str(row.get("label") or ""),
                    "topCards": list(row.get("top_cards", row.get("topCards", [])) or []),
                    "avgCompetitiveScore": float(row.get("avg_competitive_score", row.get("avgCompetitiveScore", 0.0)) or 0.0),
                }
            )
        return {
            "summary": {
                "generatedAt": metadata.get("generatedAt"),
                "trainingDeckCount": int(metadata.get("trainingDeckCount") or 0),
                "validationDeckCount": int(metadata.get("validationDeckCount") or 0),
                "cardCount": int(metadata.get("cardCount") or 0),
                "selectedWinConditionCount": int(metadata.get("selectedWinConditionCount") or metadata.get("winConditionCount") or 0),
                "selectedSynergyClusterCount": int(metadata.get("selectedSynergyClusterCount") or metadata.get("synergyClusterCount") or 0),
                "uniqueShellCount": int(metadata.get("uniqueShellCount") or 0),
                "archetypeCount": int(metadata.get("archetypeCount") or 0),
            },
            "sources": dict(metadata.get("sourceCounts") or {}),
            "winConditions": self.win_conditions(),
            "synergyClusters": synergy_clusters,
            "shells": shells,
            "archetypes": archetypes,
        }

    def _match_profile(self, *, deck: DeckPayload, source: str = "", deck_id: str = "") -> dict[str, Any] | None:
        if self._loaded is None:
            return None
        ref_key = (str(source or "").lower(), str(deck_id or "").lower())
        if ref_key in self._profiles_by_ref:
            return self._profiles_by_ref[ref_key]
        main_by_key = deck_main_from_payload(deck, cards=self._cards)
        signature = deck_signature_from_main(main_by_key, leader_title=deck.legend_title, champion_title=deck.chosen_champion_title)
        if signature in self._profiles_by_signature:
            return self._profiles_by_signature[signature]
        profiles = list(self._loaded.bundle.get("deckProfiles") or [])
        if not profiles:
            return None
        target = set(main_by_key.keys())
        scored = []
        for row in profiles:
            other = set(dict(row.get("mainByKey") or {}).keys())
            denom = len(target | other)
            score = 0.0 if denom <= 0 else float(len(target & other)) / float(denom)
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], str(item[1].get("deckName") or "").lower()))
        result = scored[0][1] if scored and scored[0][0] > 0 else None
        # Cache result under both ref_key and signature so repeat lookups skip this O(N) scan.
        if ref_key[0] or ref_key[1]:
            self._profiles_by_ref[ref_key] = result
        self._profiles_by_signature[signature] = result
        return result

    def annotation_for_entry(self, entry: MetaDeckIndexEntry) -> dict[str, Any]:
        profile = self._match_profile(deck=entry.deck, source=entry.source, deck_id=entry.deck_id)
        if profile is None:
            return {}
        return {
            "competitiveScore": float(profile.get("competitiveScore") or 0.0),
            "winConditionId": int(profile.get("winConditionId") or 0),
            "winConditionLabel": str(profile.get("winConditionLabel") or ""),
        }

    def suggest_replacements(self, *, deck: DeckPayload, collection: dict[str, int]) -> tuple[list[CardReplacementSuggestion], str | None]:
        if self._loaded is None:
            return [], None
        profile = self._match_profile(deck=deck)
        dominant = int(profile.get("winConditionId") or 0) if profile is not None else 0
        label = str(profile.get("winConditionLabel") or "") if profile is not None else None
        analysis = analyze_collection_completion(deck, collection=collection, cards=self._cards, unit_price_for_title=self._prices.cheapest_price_for_title, buy_url_for_title=self._prices.tcgplayer_search_url)
        suggestions: list[CardReplacementSuggestion] = []
        for row in analysis.missing_cards:
            key = normalize_card_key(row.card)
            if not key or row.card not in deck.main:
                continue
            ranked = rank_replacements_for_missing_card(missing_key=key, deck=deck, bundle=self._loaded.bundle, cards=self._cards, collection_by_key={normalize_card_key(title): int(qty) for title, qty in collection.items()}, dominant_win_condition=dominant, top_k=6)
            if not ranked:
                continue
            suggestions.append(CardReplacementSuggestion(card=row.card, missing=row.missing, options=[ReplacementOption(card=item["card"], owned=item["owned"], available=item["available"], score=item["score"], source=item.get("source", "hybrid"), reason=item.get("reason", ""), winConditionMatch=float(item.get("winConditionMatch", 0.0) or 0.0), synergyMatch=float(item.get("synergyMatch", 0.0) or 0.0)) for item in ranked]))
        return suggestions, label

    def _candidate_signature(self, candidate) -> str:
        return deck_signature_from_main(
            deck_main_from_payload(candidate.deck, cards=self._cards),
            leader_title=candidate.deck.legend_title,
            champion_title=candidate.deck.chosen_champion_title,
        )

    def _candidate_priority(self, candidate, *, ranking_mode: str) -> tuple[float, float, float]:
        mode = resolved_ranking_mode(ranking_mode)
        competitive = float(getattr(candidate, "competitive_score", 0.0) or 0.0)
        ranking = float(getattr(candidate, "ranking_score", 0.0) or 0.0)
        candidate_score = float(getattr(candidate, "candidate_score", 0.0) or 0.0)
        if mode == "competitive":
            return (competitive, candidate_score, ranking)
        return (ranking, competitive, candidate_score)

    def _ordered_candidates(self, candidates: list[Any], *, ranking_mode: str, only_buildable: bool, top: int, diversity_mode: str) -> list[Any]:
        deduped: dict[str, Any] = {}
        for candidate in candidates:
            signature = self._candidate_signature(candidate)
            existing = deduped.get(signature)
            if existing is None or self._candidate_priority(candidate, ranking_mode=ranking_mode) > self._candidate_priority(existing, ranking_mode=ranking_mode):
                deduped[signature] = candidate
        ordered = sorted(
            deduped.values(),
            key=lambda row: (
                -self._candidate_priority(row, ranking_mode=ranking_mode)[0],
                -self._candidate_priority(row, ranking_mode=ranking_mode)[1],
                -self._candidate_priority(row, ranking_mode=ranking_mode)[2],
                row.deck.name.lower(),
            ),
        )
        if only_buildable:
            ordered = [row for row in ordered if row.is_buildable]
        if str(diversity_mode or "").strip().lower() != "shells":
            return ordered[: max(1, int(top))]
        shell_counts: dict[str, int] = {}
        primary: list[Any] = []
        overflow: list[Any] = []
        max_variants = int(self._loaded.metadata.get("maxVariantsPerShell") or generation_defaults()["maxVariantsPerShell"]) if self._loaded is not None else generation_defaults()["maxVariantsPerShell"]
        for candidate in ordered:
            shell_id = str(getattr(candidate, "shell_id", "") or "")
            if shell_counts.get(shell_id, 0) < max_variants:
                primary.append(candidate)
                shell_counts[shell_id] = shell_counts.get(shell_id, 0) + 1
            else:
                overflow.append(candidate)
        if len(primary) < max(1, int(top)):
            primary.extend(overflow[: max(0, int(top) - len(primary))])
        return primary[: max(1, int(top))]

    def _plan_is_collection_available(self, plan, collection_by_key: dict[str, int]) -> bool:
        legend_key = normalize_card_key(plan.legend_title)
        champion_key = normalize_card_key(plan.chosen_champion_title)
        if legend_key and int(collection_by_key.get(legend_key, 0)) <= 0:
            return False
        if champion_key and int(collection_by_key.get(champion_key, 0)) <= 0:
            return False
        return True

    def _plans_for_backfill(self, plans: list[Any], *, strict_buildable: bool) -> list[Any]:
        return sorted(
            plans,
            key=lambda plan: (
                -float(getattr(plan, "archetype_buildable_conversion", 0.0) if strict_buildable else getattr(plan, "prior_score", 0.0)),
                -float(getattr(plan, "shell_buildable_conversion", 0.0) if strict_buildable else getattr(plan, "archetype_buildability_prior", 0.0)),
                -float(getattr(plan, "archetype_buildability_prior", 0.0)),
                -float(getattr(plan, "shell_buildability_prior", 0.0)),
                -float(getattr(plan, "prior_score", 0.0)),
                str(getattr(plan, "shell_label", "")).lower(),
                str(getattr(plan, "archetype_name", "")).lower(),
            ),
        )

    def recommend(self, *, collection: dict[str, int], top: int = 24, ranking_mode: str = "collection", strategy_mode: str = "hybrid", legend_title: str = "", chosen_champion_title: str = "", only_buildable: bool = False, min_results: int = 12, diversity_mode: str = "shells") -> dict[str, Any]:
        effective_ranking_mode = resolved_ranking_mode(ranking_mode, only_buildable=bool(only_buildable))
        if self._loaded is None:
            return {"generatedAt": datetime.now(timezone.utc).isoformat(), "rankingMode": effective_ranking_mode, "requestedRankingMode": ranking_mode, "strategyMode": strategy_mode, "requestedTop": int(top), "targetResults": int(min_results), "returnedResults": 0, "uniqueShellCount": 0, "fallbackUsed": False, "buildableMode": "strict" if only_buildable else "mixed", "strictBuildableResultCount": 0, "strictBuildableExhausted": bool(only_buildable), "recommendations": []}
        collection_by_key = {normalize_card_key(title): int(qty) for title, qty in collection.items() if normalize_card_key(title)}
        plans = build_generation_plans(
            bundle=self._loaded.bundle,
            collection_by_key=collection_by_key,
            ranking_mode=effective_ranking_mode,
            legend_title=legend_title,
            chosen_champion_title=chosen_champion_title,
            strict_buildable=bool(only_buildable),
        )
        strict_buildable = bool(only_buildable)
        if strict_buildable:
            plans = [plan for plan in plans if self._plan_is_collection_available(plan, collection_by_key)]
        candidates = []
        fallback_used = False
        defaults = generation_defaults()
        generation_target = max(int(min_results), int(top))
        if strict_buildable:
            for plan_idx, plan in enumerate(plans):
                if strategy_mode in {"hybrid", "seed_adapt", "seed-adapt"} and plan_idx < defaults["seedAdaptLimit"]:
                    seed, fallback = adapt_seed_candidate(
                        plan=plan,
                        bundle=self._loaded.bundle,
                        cards=self._cards,
                        rules=self._rules,
                        collection_by_key=collection_by_key,
                        generator_state=self._loaded.generator_state,
                        strict_buildable=True,
                    )
                    if seed is not None:
                        candidates.append(build_candidate_payload(deck=seed, plan=plan, build_mode="seed-adapt", bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, prices=self._prices, collection=collection, ranking_mode=effective_ranking_mode, validation_fallback=fallback))
                        fallback_used = fallback_used or bool(fallback)
                if strategy_mode in {"hybrid", "pure_generate", "pure-generate"} and plan_idx < defaults["pureGenerateLimit"]:
                    pure, fallback = generate_pure_candidate(
                        plan=plan,
                        bundle=self._loaded.bundle,
                        cards=self._cards,
                        rules=self._rules,
                        generator_state=self._loaded.generator_state,
                        collection_by_key=collection_by_key,
                        strict_buildable=True,
                    )
                    if pure is not None:
                        candidates.append(build_candidate_payload(deck=pure, plan=plan, build_mode="pure-generate", bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, prices=self._prices, collection=collection, ranking_mode=effective_ranking_mode, validation_fallback=fallback))
                        fallback_used = fallback_used or bool(fallback)
            if len(candidates) < generation_target:
                for plan in self._plans_for_backfill(plans, strict_buildable=True):
                    prototype, fallback = prototype_candidate(
                        plan=plan,
                        bundle=self._loaded.bundle,
                        cards=self._cards,
                        rules=self._rules,
                        collection_by_key=collection_by_key,
                        strict_buildable=True,
                    )
                    if prototype is None:
                        continue
                    candidates.append(build_candidate_payload(deck=prototype, plan=plan, build_mode="prototype", bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, prices=self._prices, collection=collection, ranking_mode=effective_ranking_mode, validation_fallback=fallback))
                    fallback_used = True
                    if len(candidates) >= generation_target:
                        break
        else:
            for plan_idx, plan in enumerate(plans):
                if strategy_mode in {"hybrid", "pure_generate", "pure-generate"} and plan_idx < defaults["pureGenerateLimit"]:
                    pure, fallback = generate_pure_candidate(plan=plan, bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, generator_state=self._loaded.generator_state, collection_by_key=collection_by_key)
                    if pure is not None:
                        candidates.append(build_candidate_payload(deck=pure, plan=plan, build_mode="pure-generate", bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, prices=self._prices, collection=collection, ranking_mode=effective_ranking_mode, validation_fallback=fallback))
                        fallback_used = fallback_used or bool(fallback)
                if strategy_mode in {"hybrid", "seed_adapt", "seed-adapt"} and plan_idx < defaults["seedAdaptLimit"]:
                    seed, fallback = adapt_seed_candidate(plan=plan, bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, collection_by_key=collection_by_key, generator_state=self._loaded.generator_state)
                    if seed is not None:
                        candidates.append(build_candidate_payload(deck=seed, plan=plan, build_mode="seed-adapt", bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, prices=self._prices, collection=collection, ranking_mode=effective_ranking_mode, validation_fallback=fallback))
                        fallback_used = fallback_used or bool(fallback)
            if len(candidates) < generation_target:
                for plan in self._plans_for_backfill(plans, strict_buildable=False):
                    prototype, fallback = prototype_candidate(plan=plan, bundle=self._loaded.bundle, cards=self._cards, rules=self._rules)
                    if prototype is None:
                        continue
                    candidates.append(build_candidate_payload(deck=prototype, plan=plan, build_mode="prototype", bundle=self._loaded.bundle, cards=self._cards, rules=self._rules, prices=self._prices, collection=collection, ranking_mode=effective_ranking_mode, validation_fallback=fallback))
                    fallback_used = True
                    if len(candidates) >= generation_target:
                        break
        ordered = self._ordered_candidates(candidates, ranking_mode=effective_ranking_mode, only_buildable=only_buildable, top=top, diversity_mode=diversity_mode)
        recommendations = []
        for idx, item in enumerate(ordered, start=1):
            recommendations.append({
                "rank": idx,
                "buildMode": item.build_mode,
                "shellId": item.shell_id,
                "shellLabel": item.shell_label,
                "archetypeId": item.archetype_id,
                "archetypeName": item.archetype_name,
                "archetypeConfidence": item.archetype_confidence,
                "winConditionId": item.win_condition_id,
                "winConditionLabel": item.win_condition_label,
                "winConditionConfidence": item.win_condition_confidence,
                "synergyClusterIds": item.synergy_cluster_ids,
                "synergyClusterLabels": item.synergy_cluster_labels,
                "competitiveScore": item.competitive_score,
                "rankingScore": item.ranking_score,
                "sourceBreakdown": item.source_breakdown,
                "validationFallback": item.validation_fallback,
                "isBuildable": item.is_buildable,
                "completionPct": item.completion_pct,
                "estimatedCompletionCost": item.estimated_completion_cost,
                "missingCopies": item.missing_copies,
                "missingUniqueCards": item.missing_unique_cards,
                "missingCards": item.missing_cards,
                "replacementSuggestions": item.replacement_suggestions,
                "seedDecks": item.seed_decks,
                "explanations": item.explanations,
                "deck": item.deck.model_dump(by_alias=True),
            })
        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "rankingMode": effective_ranking_mode,
            "requestedRankingMode": ranking_mode,
            "strategyMode": strategy_mode,
            "requestedTop": int(top),
            "targetResults": int(generation_target),
            "returnedResults": len(recommendations),
            "uniqueShellCount": len({str(item.get("shellId") or "") for item in recommendations if str(item.get("shellId") or "")}),
            "fallbackUsed": bool(fallback_used),
            "buildableMode": "strict" if strict_buildable else "mixed",
            "strictBuildableResultCount": len(recommendations) if strict_buildable else len([item for item in recommendations if bool(item.get("isBuildable"))]),
            "strictBuildableExhausted": bool(strict_buildable and len(recommendations) < generation_target),
            "recommendations": recommendations,
        }

    def complete(self, *, deck: DeckPayload, collection: dict[str, int], ranking_mode: str = "collection", strategy_mode: str = "hybrid") -> dict[str, Any]:
        if self._loaded is None:
            return {"completedCandidates": [], "bestCandidate": None, "replacementPlan": [], "winConditionLabel": "", "synergyClusters": [], "explanations": []}
        legend_title = deck.legend_title
        champion_title = deck.chosen_champion_title
        response = self.recommend(collection=collection, top=6, ranking_mode=ranking_mode, strategy_mode=strategy_mode, legend_title=legend_title, chosen_champion_title=champion_title, only_buildable=False)
        replacement_plan, label = self.suggest_replacements(deck=deck, collection=collection)
        best = response["recommendations"][0] if response.get("recommendations") else None
        synergy_labels = list(best.get("synergyClusterLabels") or []) if best else []
        return {"completedCandidates": response.get("recommendations") or [], "bestCandidate": best, "replacementPlan": [row.model_dump() for row in replacement_plan], "winConditionLabel": label or (best.get("winConditionLabel") if best else ""), "synergyClusters": synergy_labels, "explanations": best.get("explanations") if best else []}
