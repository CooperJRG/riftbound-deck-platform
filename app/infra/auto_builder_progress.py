from __future__ import annotations

import sys
import time
from typing import Any, TextIO


def _format_elapsed(elapsed_sec: float) -> str:
    total_seconds = max(0, int(round(float(elapsed_sec))))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _progress_bar(progress_pct: float, *, width: int = 18) -> str:
    bounded = max(0.0, min(100.0, float(progress_pct)))
    filled = int(round((bounded / 100.0) * float(max(1, width))))
    filled = min(max(0, filled), max(1, width))
    return "#" * filled + "." * (max(1, width) - filled)


def format_auto_builder_progress(payload: dict[str, Any], *, elapsed_sec: float | None = None) -> str:
    progress_pct = float(payload.get("progressPct") or 0.0)
    stage = str(payload.get("stage") or "train").strip().replace("-", " ")
    message = str(payload.get("message") or "").strip()
    parts = [f"[{_progress_bar(progress_pct)}] {progress_pct:5.1f}% {stage}"]
    stage_current = payload.get("stageCurrent")
    stage_total = payload.get("stageTotal")
    if stage_current is not None and stage_total is not None:
        parts.append(f"[{int(stage_current)}/{max(1, int(stage_total))}]")
    if message:
        parts.append(message)
    details: list[str] = []
    current_candidate = payload.get("currentCandidate")
    if current_candidate is not None:
        details.append(f"value={int(current_candidate)}")
    loss = payload.get("loss")
    if loss is not None:
        details.append(f"loss={float(loss):.4f}")
    selected_win = payload.get("selectedWinConditionCount")
    if selected_win is not None:
        details.append(f"win={int(selected_win)}")
    selected_synergy = payload.get("selectedSynergyClusterCount")
    if selected_synergy is not None:
        details.append(f"clusters={int(selected_synergy)}")
    torch_device = str(payload.get("torchDevice") or "").strip()
    if torch_device:
        details.append(f"device={torch_device}")
    if elapsed_sec is not None:
        details.append(f"elapsed={_format_elapsed(elapsed_sec)}")
    if details:
        parts.append("| " + ", ".join(details))
    return " ".join(parts)


class AutoBuilderProgressPrinter:
    def __init__(self, *, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stderr
        self._started = time.perf_counter()
        self._last_signature: tuple[Any, ...] | None = None

    def emit(self, payload: dict[str, Any]) -> None:
        signature = (
            payload.get("stage"),
            payload.get("step"),
            payload.get("stageCurrent"),
            payload.get("stageTotal"),
            payload.get("message"),
            payload.get("currentCandidate"),
            payload.get("loss"),
            payload.get("selectedWinConditionCount"),
            payload.get("selectedSynergyClusterCount"),
            payload.get("torchDevice"),
        )
        if signature == self._last_signature:
            return
        print(
            format_auto_builder_progress(payload, elapsed_sec=time.perf_counter() - self._started),
            file=self._stream,
            flush=True,
        )
        self._last_signature = signature

    def __call__(self, payload: dict[str, Any]) -> None:
        self.emit(payload)

    def note(self, *, stage: str, progress_pct: float, message: str, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "stage": str(stage or "").strip() or "benchmark",
            "step": 0,
            "totalSteps": 1,
            "progressPct": max(0.0, min(100.0, float(progress_pct))),
            "message": str(message or "").strip(),
        }
        if extra:
            payload.update(dict(extra))
        self.emit(payload)
