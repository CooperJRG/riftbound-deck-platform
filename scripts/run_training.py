#!/usr/bin/env python3
"""One-shot training runner — uses all available data, upgraded architecture."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.domain.auto_builder_training import train_auto_builder_artifacts

CARDS_PATH        = ROOT / "data" / "riftbound-cards.json"
META_INDEX_PATH   = ROOT / "artifacts" / "meta-deck-index.json"
RULES_PATH        = ROOT / "rules_profiles" / "constructed.json"
OUT_DIR           = ROOT / "artifacts" / "auto_builder"

def _progress(p: dict) -> None:
    pct  = f"{p.get('progressPct', 0):.0f}%"
    step = f"{p.get('step',0)}/{p.get('totalSteps',0)}"
    msg  = p.get('message', '')
    print(f"  [{pct} | {step}] {msg}", flush=True)

if __name__ == "__main__":
    print("=== Riftbound Auto-Builder Training ===")
    print(f"Cards:      {CARDS_PATH}")
    print(f"Meta index: {META_INDEX_PATH}")
    print(f"Output:     {OUT_DIR}")
    print()

    t0 = time.time()
    result = train_auto_builder_artifacts(
        cards_path=CARDS_PATH,
        meta_index_path=META_INDEX_PATH,
        rules_profile_path=RULES_PATH,
        out_dir=OUT_DIR,
        epochs=20,
        torch_device="auto",
        resolution_mode="search",
        progress_callback=_progress,
    )

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f} min.")
    print(f"  Training decks:   {result.get('trainingDeckCount')}")
    print(f"  Card vocab:       {result.get('cardCount')}")
    print(f"  Win conditions:   {result.get('selectedWinConditionCount')}")
    print(f"  Synergy clusters: {result.get('selectedSynergyClusterCount')}")
    metrics = result.get('trainingMetrics', {})
    print(f"  nextCardTop10Recall:           {metrics.get('nextCardTop10Recall')}")
    print(f"  collectionFirstRecommHitRate:  {metrics.get('collectionFirstRecommendationHitRate')}")
    print(f"  competitiveScoreSpearman:      {metrics.get('competitiveScoreSpearman')}")
