"""Keep the meta snapshot fresh without anybody remembering to.

The user's own diagnosis of what went wrong last time was blunt: *a big problem was
getting data, it needs to be fairly actively tracking the meta, keeping up with new card
releases, and new decks.* A pipeline that only runs when somebody types the command is a
pipeline that stops running, and an app serving a month-old meta looks exactly like one
serving a current meta -- which is the worse half of the problem.

Design constraints, each of them a way this could go wrong:

* **It must never take the app down.** The harvest runs in a worker thread, every
  failure is caught, and a failed run is logged and retried at the next tick. Meta is
  optional data by design; the deck builder works with none at all.
* **It must not promote rubbish.** Promotion goes through the existing gate, which
  rejects a snapshot that lost more than a couple of percent of its decks. An automatic
  refresh is exactly the situation the gate was written for: nobody is watching.
* **It must not stampede.** One run at a time, a delay before the first, and a
  deliberately long default interval. A restart loop must not become a request flood
  against somebody else's API.
* **It must be visible.** Every run records what happened, so "why is the meta old"
  has an answer in the UI rather than in a log file nobody opens.

Deliberately in-process rather than a cron entry or a Windows scheduled task: this is a
local-first app somebody starts by running it, and a scheduler that needs its own
install step is one more thing to get wrong on a machine that already works.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..config import Config

logger = logging.getLogger("riftbound.scheduler")

#: Refuse to run more often than this however the interval is configured. The upstreams
#: are somebody else's servers and we are a guest on them.
MIN_INTERVAL_HOURS = 0.5

#: How long a refresh may run before we stop waiting on it. Well above the harvest
#: budget, so this only fires if something is genuinely wedged.
HARD_TIMEOUT_SECONDS = 1800.0

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_OFF = "off"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RunRecord:
    """What one refresh did. Kept whether it worked or not."""
    started_at: str
    finished_at: str
    ok: bool
    promoted: bool
    snapshot_id: str
    deck_count: int
    duration_ms: int
    message: str


@dataclass
class SchedulerState:
    enabled: bool
    interval_hours: float
    status: str = STATUS_IDLE
    next_run_at: str = ""
    last_run: RunRecord | None = None
    runs: int = 0
    failures: int = 0
    #: Consecutive failures. Drives the backoff, and is the number worth alarming on --
    #: one failed harvest is an upstream having a bad minute, five is a broken app.
    consecutive_failures: int = 0
    history: list[RunRecord] = field(default_factory=list)


#: How many past runs to keep. Enough to see a pattern, small enough to hold in memory.
HISTORY_LIMIT = 20


class MetaScheduler:
    """Runs the meta harvest on a timer, in the background, safely.

    The refresh callable is injected rather than imported here so this stays testable
    without a network: the scheduling logic is the part with the interesting failure
    modes, and it should be provable on its own.
    """

    def __init__(
        self,
        config: Config,
        *,
        refresh: Callable[[float], RunRecord] | None = None,
        sleep: Callable[[float], asyncio.Future[None]] | None = None,
    ):
        self._config = config
        self._refresh = refresh or (lambda budget: run_refresh(config, budget))
        self._sleep = sleep or asyncio.sleep
        self._task: asyncio.Task[None] | None = None
        self._lock = threading.Lock()
        self.state = SchedulerState(
            enabled=config.meta_refresh,
            interval_hours=max(MIN_INTERVAL_HOURS, config.meta_refresh_hours),
            status=STATUS_IDLE if config.meta_refresh else STATUS_OFF,
        )

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        if not self.state.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="riftbound-meta-refresh")
        logger.info(
            "meta refresh scheduled every %.1fh, first check in %.0fs",
            self.state.interval_hours,
            self._config.meta_refresh_delay,
        )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        # Both, deliberately: CancelledError derives from BaseException, so catching
        # Exception alone would let the cancellation we just requested escape. Shutdown
        # is best effort -- nothing here is worth failing a process exit over.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # -- the loop -------------------------------------------------------------

    async def _loop(self) -> None:
        try:
            await self._sleep(self._config.meta_refresh_delay)
            while True:
                self._note_next_run(self._interval_seconds())
                await self.run_once()
                await self._sleep(self._interval_seconds())
        except asyncio.CancelledError:
            logger.info("meta refresh stopped")
            raise

    def _interval_seconds(self) -> float:
        """Interval, backed off after repeated failure.

        An upstream that is down stays down for a while, and hammering it neither helps
        us nor is a decent way to behave. Doubling per failure, capped at eight times
        the configured interval.
        """
        base = self.state.interval_hours * 3600.0
        factor = min(8, 2 ** self.state.consecutive_failures)
        return base * factor

    def _note_next_run(self, seconds: float) -> None:
        self.state.next_run_at = (_now() + timedelta(seconds=seconds)).isoformat()

    async def run_once(self) -> RunRecord | None:
        """One refresh. Returns None if another is already in flight.

        The harvest is blocking stdlib HTTP, so it goes to a worker thread; running it
        on the event loop would freeze every request for the length of a harvest.
        """
        if not self._lock.acquire(blocking=False):
            logger.info("meta refresh already running, skipping this tick")
            return None
        self.state.status = STATUS_RUNNING
        try:
            record = await asyncio.wait_for(
                asyncio.to_thread(self._refresh, self._config.meta_refresh_budget),
                timeout=HARD_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record = RunRecord(
                started_at=_now().isoformat(), finished_at=_now().isoformat(),
                ok=False, promoted=False, snapshot_id="", deck_count=0,
                duration_ms=0, message=f"{type(exc).__name__}: {exc}",
            )
            logger.warning("meta refresh failed: %s", exc)
        finally:
            self.state.status = STATUS_IDLE
            self._lock.release()

        self._record(record)
        return record

    def _record(self, record: RunRecord) -> None:
        self.state.last_run = record
        self.state.runs += 1
        if record.ok:
            self.state.consecutive_failures = 0
        else:
            self.state.failures += 1
            self.state.consecutive_failures += 1
        self.state.history.insert(0, record)
        del self.state.history[HISTORY_LIMIT:]
        if record.ok:
            logger.info(
                "meta refresh ok: %s (%d decks)%s",
                record.snapshot_id, record.deck_count,
                " promoted" if record.promoted else " not promoted",
            )


def run_refresh(config: Config, budget: float) -> RunRecord:
    """Harvest and promote, reusing the pipeline the command line runs.

    Calls the same code path as ``python -m riftbound.data.meta_pipeline build
    --promote`` on purpose. A scheduler with its own copy of the ingest logic is two
    pipelines that drift apart, and only one of them gets tested.
    """
    from .meta_pipeline import main as pipeline_main

    started = _now()
    clock = time.perf_counter()
    argv = ["build", "--promote", f"--budget={budget:g}"]

    code = pipeline_main(argv)
    duration_ms = int((time.perf_counter() - clock) * 1000)

    snapshot_id, deck_count, promoted = _describe_current(config)
    return RunRecord(
        started_at=started.isoformat(),
        finished_at=_now().isoformat(),
        ok=code == 0,
        promoted=promoted and code == 0,
        snapshot_id=snapshot_id,
        deck_count=deck_count,
        duration_ms=duration_ms,
        message="" if code == 0 else f"pipeline exited {code}",
    )


def _describe_current(config: Config) -> tuple[str, int, bool]:
    from .meta_snapshot import load_current_meta

    try:
        snapshot = load_current_meta(config.meta_dir)
    except (FileNotFoundError, ValueError):
        return ("", 0, False)
    if snapshot is None:
        return ("", 0, False)
    return (snapshot.manifest.snapshot_id, snapshot.manifest.deck_count, True)


def snapshot_age_hours(created_at: str) -> float | None:
    """How old a snapshot is, or None if the timestamp is unreadable."""
    if not created_at:
        return None
    try:
        stamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return max(0.0, (_now() - stamp).total_seconds() / 3600.0)
