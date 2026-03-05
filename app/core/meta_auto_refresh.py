from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import sys
import time

from app.core.services import AppServices

logger = logging.getLogger("riftbound.meta-refresh")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_stream(data: bytes, *, max_chars: int = 4000) -> str:
    text = data.decode("utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


class MetaAutoRefreshScheduler:
    def __init__(self, services: AppServices):
        self._services = services
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._run_lock = asyncio.Lock()
        self._last_run_started_at: str | None = None
        self._last_run_finished_at: str | None = None
        self._last_run_error: str | None = None

    async def start(self) -> None:
        cfg = self._services.config
        if not cfg.meta_auto_refresh_enabled:
            return
        if not cfg.meta_refresh_script_path.is_file():
            logger.error(
                json.dumps(
                    {
                        "event": "meta_auto_refresh_unavailable",
                        "reason": "refresh_script_missing",
                        "scriptPath": str(cfg.meta_refresh_script_path),
                    }
                )
            )
            return
        if self._task is not None and not self._task.done():
            return

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="meta-auto-refresh")
        logger.info(
            json.dumps(
                {
                    "event": "meta_auto_refresh_started",
                    "intervalSec": cfg.meta_auto_refresh_interval_sec,
                    "timeoutSec": cfg.meta_auto_refresh_timeout_sec,
                    "runOnStartup": cfg.meta_auto_refresh_run_on_startup,
                    "scriptPath": str(cfg.meta_refresh_script_path),
                }
            )
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    def status(self) -> dict[str, object]:
        cfg = self._services.config
        running = bool(self._task is not None and not self._task.done())
        return {
            "enabled": bool(cfg.meta_auto_refresh_enabled),
            "running": running,
            "intervalSec": cfg.meta_auto_refresh_interval_sec,
            "timeoutSec": cfg.meta_auto_refresh_timeout_sec,
            "lastRunStartedAt": self._last_run_started_at,
            "lastRunFinishedAt": self._last_run_finished_at,
            "lastRunError": self._last_run_error,
        }

    async def _run_loop(self) -> None:
        cfg = self._services.config
        if cfg.meta_auto_refresh_run_on_startup:
            await self._run_once()

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=float(cfg.meta_auto_refresh_interval_sec),
                )
                break
            except asyncio.TimeoutError:
                await self._run_once()

    async def _run_once(self) -> None:
        if self._run_lock.locked():
            logger.warning(json.dumps({"event": "meta_auto_refresh_skipped", "reason": "previous_run_active"}))
            return
        async with self._run_lock:
            await self._run_once_locked()

    async def _run_once_locked(self) -> None:
        cfg = self._services.config
        command = self._build_command()
        started = _utc_now_iso()
        self._last_run_started_at = started
        started_perf = time.perf_counter()
        logger.info(
            json.dumps(
                {
                    "event": "meta_auto_refresh_run_started",
                    "startedAt": started,
                    "command": command,
                }
            )
        )

        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cfg.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(cfg.meta_auto_refresh_timeout_sec),
            )
            stdout = _decode_stream(stdout_bytes or b"")
            stderr = _decode_stream(stderr_bytes or b"")
            return_code = int(proc.returncode or 0)
            if return_code != 0:
                raise RuntimeError(
                    f"refresh script exited with code {return_code}; stderr={stderr or '<empty>'}"
                )

            self._services.prices.refresh(force=True)
            status = self._services.meta.refresh()
            self._services.auto_builder.refresh(force=True)
            self._last_run_finished_at = _utc_now_iso()
            self._last_run_error = None
            logger.info(
                json.dumps(
                    {
                        "event": "meta_auto_refresh_run_completed",
                        "finishedAt": self._last_run_finished_at,
                        "durationSec": round(time.perf_counter() - started_perf, 3),
                        "indexedDecks": status.get("indexedDecks"),
                        "rawRows": status.get("rawRows"),
                    }
                )
            )
            if stderr:
                logger.warning(
                    json.dumps(
                        {
                            "event": "meta_auto_refresh_stderr",
                            "stderrTail": stderr,
                        }
                    )
                )
            if stdout:
                logger.info(
                    json.dumps(
                        {
                            "event": "meta_auto_refresh_stdout",
                            "stdoutTail": stdout,
                        }
                    )
                )
        except asyncio.TimeoutError:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.communicate()
            self._last_run_finished_at = _utc_now_iso()
            self._last_run_error = (
                f"refresh script timed out after {cfg.meta_auto_refresh_timeout_sec} seconds"
            )
            logger.error(
                json.dumps(
                    {
                        "event": "meta_auto_refresh_timeout",
                        "finishedAt": self._last_run_finished_at,
                        "timeoutSec": cfg.meta_auto_refresh_timeout_sec,
                    }
                )
            )
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.communicate()
            raise
        except Exception as exc:
            self._last_run_finished_at = _utc_now_iso()
            self._last_run_error = str(exc)
            logger.exception(
                json.dumps(
                    {
                        "event": "meta_auto_refresh_failed",
                        "finishedAt": self._last_run_finished_at,
                        "error": str(exc),
                    }
                )
            )

    def _build_command(self) -> list[str]:
        cfg = self._services.config
        command = [
            sys.executable,
            str(cfg.meta_refresh_script_path),
            "--cards",
            str(cfg.cards_path),
            "--cache-dir",
            str(cfg.deck_sources_cache_dir),
            "--out-json",
            str(cfg.meta_index_path),
            "--out-csv",
            str(cfg.meta_index_csv_path),
            "--out-prices-json",
            str(cfg.base_card_prices_json_path),
            "--out-prices-csv",
            str(cfg.base_card_prices_csv_path),
            "--rules-profile",
            str(cfg.rules_profile_path),
            "--auto-builder-dir",
            str(cfg.auto_builder_dir),
            "--auto-builder-epochs",
            str(cfg.auto_builder_epochs),
        ]
        if not cfg.auto_builder_enabled:
            command.append("--skip-auto-builder")
        command.extend(cfg.meta_refresh_extra_args)
        return command
