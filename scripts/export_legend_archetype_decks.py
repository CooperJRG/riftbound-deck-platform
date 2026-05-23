#!/usr/bin/env python3
"""Export one archetypical deck per legend using the trained auto-builder model."""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.core.config import load_config
from app.domain.auto_builder_generation import (
    _archetype_profiles,
    _build_deck_payload,
    _complete_main_greedily,
    _main_deck_target_size,
    _validate_completed_candidate,
    adapt_seed_candidate,
    build_generation_plans,
    generate_pure_candidate,
    prewarm_auto_builder_runtime,
    prototype_candidate,
)
from app.domain.auto_builder_types import GenerationPlan
from app.domain.eligibility import build_eligibility_snapshot
from app.domain.normalization import normalize_card_key
from app.domain.rules import load_format_rules
from app.domain.validator import validate_deck
from app.infra.cards_repo import load_card_catalog


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_bundle(model_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    bundle_path = model_dir / "sklearn_bundle.joblib"
    generator_path = model_dir / "generator_moe.pt"
    metadata_path = model_dir / "metadata.json"
    for path in (bundle_path, generator_path, metadata_path):
        if not path.is_file():
            raise FileNotFoundError(f"Missing auto-builder artifact: {path}")
    with bundle_path.open("rb") as fh:
        bundle = pickle.load(fh)
    generator_state = torch.load(generator_path, map_location="cpu", weights_only=False)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return bundle, generator_state, metadata


def _unlimited_collection(bundle: dict[str, Any], *, copies: int = 4) -> dict[str, int]:
    keys: set[str] = set()
    for key in list(bundle.get("indexToKey") or []):
        normalized = normalize_card_key(str(key))
        if normalized:
            keys.add(normalized)
    for key in dict(bundle.get("cardEmbeddings") or {}).keys():
        normalized = normalize_card_key(str(key))
        if normalized:
            keys.add(normalized)
    return {key: int(copies) for key in keys}


def _title_map(cards, main_by_key: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, qty in main_by_key.items():
        if int(qty) <= 0:
            continue
        title = cards.by_key[key].title if key in cards.by_key else str(key)
        out[title] = int(out.get(title, 0)) + int(qty)
    return dict(sorted(out.items(), key=lambda row: (-row[1], row[0].lower())))


def _best_shell_by_legend(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_profiles = dict(bundle.get("shellProfiles") or {})
    shells = list(raw_profiles.values()) if raw_profiles else []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in shells:
        if not isinstance(row, dict):
            continue
        legend = str(row.get("legendTitle") or row.get("legend_title") or "")
        if legend:
            grouped[legend].append(row)
    best: dict[str, dict[str, Any]] = {}
    for legend, rows in grouped.items():
        rows.sort(
            key=lambda row: (
                -float(row.get("competitivePrior") or row.get("competitive_prior") or 0.0),
                -int(row.get("trainingDeckCount") or row.get("training_deck_count") or 0),
                str(row.get("shellLabel") or row.get("shell_label") or "").lower(),
            )
        )
        best[legend] = rows[0]
    return best


def _archetype_fallback_deck(
    *,
    plan: GenerationPlan,
    bundle: dict[str, Any],
    cards,
    rules,
    generator_state: dict[str, Any],
    collection_by_key: dict[str, int],
) -> tuple[Any | None, str]:
    archetype = _archetype_profiles(bundle).get(plan.archetype_id, {})
    main_by_key = {str(key): int(qty) for key, qty in dict(archetype.get("prototypeMain") or {}).items() if int(qty) > 0}
    if not main_by_key:
        return None, "missing-prototype-main"

    target_main_size = _main_deck_target_size(rules)
    if sum(int(value) for value in main_by_key.values()) < target_main_size:
        completed = _complete_main_greedily(
            plan=plan,
            main_by_key=main_by_key,
            target_main_size=target_main_size,
            bundle=bundle,
            cards=cards,
            generator_state=generator_state,
            collection_by_key=collection_by_key,
            strict_buildable=False,
        )
        if completed is not None:
            main_by_key = completed

    validated, fallback = _validate_completed_candidate(
        plan=plan,
        main_by_key=main_by_key,
        bundle=bundle,
        cards=cards,
        rules=rules,
        collection_by_key=collection_by_key,
        strict_buildable=False,
    )
    if validated is not None:
        return validated, fallback or "archetype-prototype"

    snapshot = build_eligibility_snapshot(cards=cards, rules=rules, legend_title=plan.legend_title)
    runes = dict(snapshot.recommended_runes)
    battlefields = [card.title for card in snapshot.battlefields[: snapshot.battlefield_count]]
    return _build_deck_payload(
        plan=plan,
        main_by_key=main_by_key,
        cards=cards,
        runes=runes,
        battlefields=battlefields,
    ), "archetype-prototype-unvalidated"


def _generate_deck_for_plan(
    *,
    plan: GenerationPlan,
    bundle: dict[str, Any],
    cards,
    rules,
    generator_state: dict[str, Any],
    collection_by_key: dict[str, int],
) -> tuple[Any | None, str, str]:
    attempts: list[tuple[str, Any]] = [
        (
            "pure-generate",
            lambda: generate_pure_candidate(
                plan=plan,
                bundle=bundle,
                cards=cards,
                rules=rules,
                generator_state=generator_state,
                collection_by_key=collection_by_key,
                strict_buildable=False,
            ),
        ),
        (
            "seed-adapt",
            lambda: adapt_seed_candidate(
                plan=plan,
                bundle=bundle,
                cards=cards,
                rules=rules,
                collection_by_key=collection_by_key,
                generator_state=generator_state,
                strict_buildable=False,
            ),
        ),
        (
            "prototype",
            lambda: prototype_candidate(
                plan=plan,
                bundle=bundle,
                cards=cards,
                rules=rules,
                collection_by_key=collection_by_key,
                strict_buildable=False,
            ),
        ),
    ]
    last_fallback = ""
    for build_mode, runner in attempts:
        deck, fallback = runner()
        last_fallback = str(fallback or last_fallback)
        if deck is not None:
            return deck, build_mode, fallback
    deck, fallback = _archetype_fallback_deck(
        plan=plan,
        bundle=bundle,
        cards=cards,
        rules=rules,
        generator_state=generator_state,
        collection_by_key=collection_by_key,
    )
    if deck is not None:
        return deck, "archetype-prototype", fallback
    return None, "", last_fallback


def _deck_entry(*, plan: GenerationPlan, deck, build_mode: str, fallback: str, cards, rules) -> dict[str, Any]:
    validation = validate_deck(deck, rules=rules, cards=cards)
    return {
        "legendTitle": plan.legend_title,
        "chosenChampionTitle": plan.chosen_champion_title,
        "shellId": plan.shell_id,
        "shellLabel": plan.shell_label,
        "archetypeId": plan.archetype_id,
        "archetypeName": plan.archetype_name,
        "winConditionId": plan.win_condition_id,
        "winConditionLabel": plan.win_condition_label,
        "buildMode": build_mode,
        "validationFallback": fallback or "",
        "isValid": bool(validation.is_valid),
        "validationSummary": validation.summary,
        "validationIssues": [{"code": issue.code, "field": issue.field, "message": issue.message} for issue in validation.issues],
        "deck": {
            "name": deck.name,
            "main": _title_map(cards, deck.main),
            "runes": _title_map(cards, deck.runes),
            "battlefields": list(deck.battlefields or []),
            "sideboard": _title_map(cards, deck.sideboard),
        },
    }


def export_legend_archetype_decks(*, model_dir: Path, out_path: Path, copies: int = 4) -> dict[str, Any]:
    cfg = load_config()
    cards = load_card_catalog(cfg.cards_path)
    rules = load_format_rules(cfg.rules_profile_path)
    bundle, generator_state, metadata = _load_bundle(model_dir)
    prewarm_auto_builder_runtime(bundle=bundle, generator_state=generator_state, cards=cards)

    collection_by_key = _unlimited_collection(bundle, copies=copies)
    best_shells = _best_shell_by_legend(bundle)
    legends = sorted(best_shells.keys(), key=str.lower)

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for index, legend_title in enumerate(legends, start=1):
        shell = best_shells[legend_title]
        champion_title = str(shell.get("chosenChampionTitle") or shell.get("chosen_champion_title") or "")
        print(f"[{index}/{len(legends)}] {legend_title} / {champion_title}", flush=True)

        plans = build_generation_plans(
            bundle=bundle,
            collection_by_key=collection_by_key,
            ranking_mode="competitive",
            legend_title=legend_title,
            chosen_champion_title=champion_title,
            strict_buildable=False,
        )
        if not plans:
            skipped.append({"legendTitle": legend_title, "reason": "no-generation-plan"})
            continue

        plan = plans[0]
        deck, build_mode, fallback = _generate_deck_for_plan(
            plan=plan,
            bundle=bundle,
            cards=cards,
            rules=rules,
            generator_state=generator_state,
            collection_by_key=collection_by_key,
        )

        if deck is None:
            skipped.append({"legendTitle": legend_title, "reason": fallback or "generation-failed"})
            continue

        rows.append(_deck_entry(plan=plan, deck=deck, build_mode=build_mode, fallback=fallback, cards=cards, rules=rules))

    payload = {
        "generatedAt": _utc_now_iso(),
        "modelDir": str(model_dir),
        "modelGeneratedAt": metadata.get("generatedAt"),
        "trainingDeckCount": int(metadata.get("trainingDeckCount") or 0),
        "legendCount": len(rows),
        "requestedLegendCount": len(legends),
        "skippedCount": len(skipped),
        "legends": rows,
        "skipped": skipped,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="Auto-builder artifact directory (default: RB_AUTO_BUILDER_DIR / config auto_builder_dir)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=APP_ROOT / "artifacts" / "legend_archetype_decks.json",
        help="Output JSON path",
    )
    parser.add_argument("--copies", type=int, default=4, help="Collection copies per card for generation")
    args = parser.parse_args()

    cfg = load_config()
    model_dir = Path(args.model_dir or cfg.auto_builder_dir)
    payload = export_legend_archetype_decks(model_dir=model_dir, out_path=args.out, copies=max(1, int(args.copies)))
    print(f"Wrote {payload['legendCount']} legend decks to {args.out}")
    if payload["skippedCount"]:
        print(f"Skipped {payload['skippedCount']} legends (see skipped[] in output)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
