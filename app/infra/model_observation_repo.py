from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from app.core.config import AppConfig
from app.domain.auto_builder_training import train_auto_builder_artifacts
from app.infra.auto_builder_repo import AutoBuilderRepository


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    raw = raw.strip("-")
    return raw or "model"


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


class ModelObservationRepository:
    def __init__(self, *, registry_dir: Path, config: AppConfig, auto_builder: AutoBuilderRepository):
        self._registry_dir = Path(registry_dir)
        self._versions_dir = self._registry_dir / "versions"
        self._manifest_path = self._registry_dir / "manifest.json"
        self._config = config
        self._auto_builder = auto_builder
        self._lock = threading.Lock()
        self._training_thread: threading.Thread | None = None
        self._training_state: dict[str, Any] = self._empty_training_state()
        self._registry_dir.mkdir(parents=True, exist_ok=True)
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_manifest()

    def _empty_training_state(self) -> dict[str, Any]:
        return {
            "isRunning": False,
            "jobId": "",
            "label": "",
            "status": "idle",
            "startedAt": None,
            "updatedAt": None,
            "finishedAt": None,
            "stage": "",
            "step": 0,
            "totalSteps": 0,
            "progressPct": 0.0,
            "message": "",
            "error": "",
            "outputDir": "",
            "modelId": "",
            "params": {},
            "result": {},
            "events": [],
        }

    def _load_manifest(self) -> dict[str, Any]:
        if not self._manifest_path.is_file():
            return {"productionModelId": "", "models": []}
        try:
            payload = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {"productionModelId": "", "models": []}
        return {
            "productionModelId": str(payload.get("productionModelId") or ""),
            "models": list(payload.get("models") or []),
        }

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        self._manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _ensure_manifest(self) -> None:
        manifest = self._load_manifest()
        seen_ids = set()
        normalized = []
        for row in list(manifest.get("models") or []):
            model_id = str(row.get("id") or "").strip()
            dir_name = str(row.get("dirName") or model_id).strip()
            if not model_id or not dir_name or model_id in seen_ids:
                continue
            seen_ids.add(model_id)
            normalized.append(
                {
                    "id": model_id,
                    "label": str(row.get("label") or model_id),
                    "kind": str(row.get("kind") or "trained"),
                    "status": str(row.get("status") or "ready"),
                    "createdAt": row.get("createdAt") or _utc_now_iso(),
                    "promotedAt": row.get("promotedAt"),
                    "dirName": dir_name,
                }
            )
        manifest["models"] = normalized
        self._save_manifest(manifest)

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _manifest(self) -> dict[str, Any]:
        manifest = self._load_manifest()
        models = []
        for row in list(manifest.get("models") or []):
            version_dir = self._versions_dir / str(row.get("dirName") or "")
            if version_dir.is_dir():
                models.append(row)
        manifest["models"] = models
        return manifest

    def _version_dir(self, row: dict[str, Any]) -> Path:
        return self._versions_dir / str(row.get("dirName") or row.get("id") or "")

    def _upsert_manifest_entry(self, entry: dict[str, Any]) -> None:
        manifest = self._manifest()
        models = [row for row in manifest.get("models") or [] if str(row.get("id") or "") != str(entry.get("id") or "")]
        models.append(entry)
        models.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
        manifest["models"] = models
        self._save_manifest(manifest)

    def _defaults(self) -> dict[str, Any]:
        metadata = self._read_json(self._config.auto_builder_dir / "metadata.json")
        synthetic = dict(metadata.get("syntheticCollectionConfig") or {})
        selected_win = int(metadata.get("selectedWinConditionCount") or metadata.get("winConditionCount") or 0)
        selected_synergy = int(metadata.get("selectedSynergyClusterCount") or metadata.get("synergyClusterCount") or 0)
        return {
            "epochs": int(metadata.get("epochs") or self._config.auto_builder_epochs),
            "torchDevice": str(metadata.get("torchDevice") or "auto"),
            "minWinConditionCount": max(8, int(selected_win or metadata.get("minWinConditionCount") or 56)),
            "minSynergyClusterCount": max(16, int(selected_synergy or metadata.get("minSynergyClusterCount") or 112)),
            "syntheticCollection": {
                "packMin": int(synthetic.get("packMin") or 24),
                "packMax": int(synthetic.get("packMax") or 240),
                "scenarioCount": int(synthetic.get("scenarioCount") or 4),
                "runeUnlimited": bool(synthetic.get("runeUnlimited", True)),
            },
            "productionModelDir": str(self._config.auto_builder_dir),
            "registryDir": str(self._registry_dir),
        }

    def _summary_for_entry(self, row: dict[str, Any], *, production_model_id: str = "") -> dict[str, Any]:
        version_dir = self._version_dir(row)
        metadata = self._read_json(version_dir / "metadata.json")
        return {
            "id": str(row.get("id") or ""),
            "label": str(row.get("label") or row.get("id") or ""),
            "kind": str(row.get("kind") or "trained"),
            "status": str(row.get("status") or "ready"),
            "isProduction": str(row.get("id") or "") == str(production_model_id or ""),
            "createdAt": row.get("createdAt"),
            "promotedAt": row.get("promotedAt"),
            "modelDir": str(version_dir),
            "generatedAt": metadata.get("generatedAt"),
            "trainingDeckCount": int(metadata.get("trainingDeckCount") or 0),
            "winConditionCount": int(metadata.get("selectedWinConditionCount") or metadata.get("winConditionCount") or 0),
            "synergyClusterCount": int(metadata.get("selectedSynergyClusterCount") or metadata.get("synergyClusterCount") or 0),
            "epochs": int(metadata.get("epochs") or 0),
            "torchDevice": str(metadata.get("torchDevice") or ""),
            "sourceCounts": dict(metadata.get("sourceCounts") or {}),
            "trainingMetrics": dict(metadata.get("trainingMetrics") or {}),
        }

    def list_models(self) -> list[dict[str, Any]]:
        manifest = self._manifest()
        production_model_id = str(manifest.get("productionModelId") or "")
        rows = [self._summary_for_entry(row, production_model_id=production_model_id) for row in list(manifest.get("models") or [])]
        rows.sort(key=lambda row: str(row.get("createdAt") or ""), reverse=True)
        return rows

    def training_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._training_state)

    def overview(self) -> dict[str, Any]:
        return {
            "status": self._auto_builder.status(),
            "training": self.training_status(),
            "models": self.list_models(),
            "observation": self._auto_builder.observation_snapshot(),
            "defaults": self._defaults(),
        }

    def _set_training_state(self, **updates: Any) -> None:
        with self._lock:
            next_state = dict(self._training_state)
            should_record_event = False
            event_payload = {
                "timestamp": _utc_now_iso(),
                "status": str(updates.get("status", next_state.get("status", "")) or ""),
                "stage": str(updates.get("stage", next_state.get("stage", "")) or ""),
                "step": int(updates.get("step", next_state.get("step", 0)) or 0),
                "totalSteps": int(updates.get("totalSteps", next_state.get("totalSteps", 0)) or 0),
                "progressPct": float(updates.get("progressPct", next_state.get("progressPct", 0.0)) or 0.0),
                "message": str(updates.get("message", next_state.get("message", "")) or ""),
            }
            if event_payload["message"]:
                for key in ("status", "stage", "step", "totalSteps", "message"):
                    if updates.get(key) != next_state.get(key):
                        should_record_event = True
                        break
            next_state.update(updates)
            next_state["updatedAt"] = _utc_now_iso()
            if should_record_event:
                history = list(next_state.get("events") or [])
                history.append(event_payload)
                next_state["events"] = history[-24:]
            self._training_state = next_state

    def start_training(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._training_state.get("isRunning"):
                raise RuntimeError("A model training job is already running.")
        defaults = self._defaults()
        label = str(params.get("label") or "").strip()
        model_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_slugify(label or 'observation-model')}"
        output_dir = self._versions_dir / model_id
        request_params = {
            "label": label or f"Model {model_id}",
            "epochs": max(1, int(params.get("epochs") or defaults["epochs"])),
            "torchDevice": "auto",
            "minWinConditionCount": int(defaults["minWinConditionCount"]),
            "minSynergyClusterCount": int(defaults["minSynergyClusterCount"]),
            "syntheticCollection": dict(defaults["syntheticCollection"]),
        }
        source_health = dict(self._auto_builder.status().get("sourceHealth") or {})
        started_at = _utc_now_iso()
        self._set_training_state(
            isRunning=True,
            jobId=model_id,
            label=request_params["label"],
            status="running",
            startedAt=started_at,
            finishedAt=None,
            stage="queued",
            step=0,
            totalSteps=11,
            progressPct=1.0,
            message="Queued model training.",
            error="",
            outputDir=str(output_dir),
            modelId=model_id,
            params=request_params,
            result={},
            events=[],
        )

        def _progress(payload: dict[str, Any]) -> None:
            self._set_training_state(**payload, status="running")

        def _run() -> None:
            error = ""
            result: dict[str, Any] = {}
            try:
                result = train_auto_builder_artifacts(
                    cards_path=self._config.cards_path,
                    meta_index_path=self._config.meta_index_path,
                    rules_profile_path=self._config.rules_profile_path,
                    out_dir=output_dir,
                    epochs=int(request_params["epochs"]),
                    source_health=source_health,
                    torch_device=str(request_params["torchDevice"]),
                    min_win_condition_count=int(request_params["minWinConditionCount"]),
                    min_synergy_cluster_count=int(request_params["minSynergyClusterCount"]),
                    synthetic_collection_config=dict(request_params["syntheticCollection"]),
                    resolution_mode="auto",
                    resolution_reference_artifact_dir=self._config.auto_builder_dir,
                    progress_callback=_progress,
                )
                self._upsert_manifest_entry(
                    {
                        "id": model_id,
                        "label": request_params["label"],
                        "kind": "trained",
                        "status": "ready",
                        "createdAt": started_at,
                        "promotedAt": None,
                        "dirName": model_id,
                    }
                )
                self._set_training_state(
                    isRunning=False,
                    status="completed",
                    finishedAt=_utc_now_iso(),
                    progressPct=100.0,
                    step=max(int(self._training_state.get("step") or 0), int(self._training_state.get("totalSteps") or 0)),
                    message="Training completed.",
                    error="",
                    result=result,
                )
            except Exception as exc:
                error = str(exc)
                self._upsert_manifest_entry(
                    {
                        "id": model_id,
                        "label": request_params["label"],
                        "kind": "trained",
                        "status": "failed",
                        "createdAt": started_at,
                        "promotedAt": None,
                        "dirName": model_id,
                    }
                )
                self._set_training_state(
                    isRunning=False,
                    status="failed",
                    finishedAt=_utc_now_iso(),
                    error=error,
                    message=error or "Training failed.",
                    result=result,
                )
            finally:
                with self._lock:
                    self._training_thread = None

        thread = threading.Thread(target=_run, name=f"model-observation-train-{model_id}", daemon=True)
        with self._lock:
            self._training_thread = thread
        thread.start()
        return self.training_status()

    def snapshot_production(self, *, label: str = "") -> dict[str, Any]:
        metadata_path = self._config.auto_builder_dir / "metadata.json"
        if not metadata_path.is_file():
            raise RuntimeError("No production model is available to snapshot.")
        model_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_slugify(label or 'production-snapshot')}"
        target_dir = self._versions_dir / model_id
        _copy_tree(self._config.auto_builder_dir, target_dir)
        self._upsert_manifest_entry(
            {
                "id": model_id,
                "label": label or "Production Snapshot",
                "kind": "snapshot",
                "status": "ready",
                "createdAt": _utc_now_iso(),
                "promotedAt": None,
                "dirName": model_id,
            }
        )
        manifest = self._manifest()
        return self._summary_for_entry(
            next(row for row in manifest["models"] if str(row.get("id") or "") == model_id),
            production_model_id=str(manifest.get("productionModelId") or ""),
        )

    def promote_model(self, model_id: str) -> dict[str, Any]:
        target_id = str(model_id or "").strip()
        manifest = self._manifest()
        entry = next((row for row in manifest.get("models") or [] if str(row.get("id") or "") == target_id), None)
        if entry is None:
            raise RuntimeError("Model version not found.")
        src_dir = self._version_dir(entry)
        if not src_dir.is_dir():
            raise RuntimeError("Saved model directory is missing.")
        production_dir = self._config.auto_builder_dir
        parent_dir = production_dir.parent
        temp_dir = parent_dir / f"{production_dir.name}.incoming-{target_id}"
        backup_dir = parent_dir / f"{production_dir.name}.backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        _copy_tree(src_dir, temp_dir)
        previous_exists = production_dir.exists()
        try:
            if previous_exists:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                shutil.move(str(production_dir), str(backup_dir))
            shutil.move(str(temp_dir), str(production_dir))
            self._auto_builder.refresh(force=True)
            status = self._auto_builder.status()
            if status.get("lastError"):
                raise RuntimeError(str(status["lastError"]))
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            manifest["productionModelId"] = target_id
            for row in manifest.get("models") or []:
                if str(row.get("id") or "") == target_id:
                    row["promotedAt"] = _utc_now_iso()
            self._save_manifest(manifest)
        except Exception:
            if production_dir.exists():
                shutil.rmtree(production_dir)
            if backup_dir.exists():
                shutil.move(str(backup_dir), str(production_dir))
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            self._auto_builder.refresh(force=True)
            raise
        return self._summary_for_entry(entry, production_model_id=target_id)
