from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

repo = Path(__file__).resolve().parents[1]
workspace = repo.parent
src_prod = repo / "artifacts" / "auto_builder"
dst_prod = workspace / "artifacts" / "auto_builder"
src_version = repo / "artifacts" / "auto_builder_models" / "versions" / "20260523T022939Z-model-v4-unleashed"
dst_versions = workspace / "artifacts" / "auto_builder_models" / "versions"
manifest_path = workspace / "artifacts" / "auto_builder_models" / "manifest.json"
model_id = "20260523T022939Z-model-v4-unleashed"

if dst_prod.exists():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = workspace / "artifacts" / f"auto_builder.backup-{stamp}"
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(dst_prod, backup)
    shutil.rmtree(dst_prod)
shutil.copytree(src_prod, dst_prod)
print(f"Promoted v4 to {dst_prod}")

if src_version.exists():
    dst_version = dst_versions / model_id
    if dst_version.exists():
        shutil.rmtree(dst_version)
    shutil.copytree(src_version, dst_version)
    print(f"Copied version dir to {dst_version}")

manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"productionModelId": "", "models": []}
repo_manifest = json.loads((repo / "artifacts" / "auto_builder_models" / "manifest.json").read_text(encoding="utf-8"))
v4_entry = next(row for row in repo_manifest["models"] if row["id"] == model_id)
models = [row for row in manifest.get("models", []) if row.get("id") != model_id]
models.insert(0, v4_entry)
manifest["models"] = models
manifest["productionModelId"] = model_id
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"Updated manifest productionModelId -> {model_id}")

sys.path.insert(0, str(repo))
from app.domain.auto_builder_generation import prewarm_auto_builder_runtime

raw = torch.load(dst_prod / "generator_moe.pt", map_location="cpu", weights_only=False)
prewarm_auto_builder_runtime(bundle={"cardEmbeddings": {}}, generator_state=raw, cards=object())
print(f"Runtime prewarm OK, candidateDim={raw.get('candidateDim')}")
