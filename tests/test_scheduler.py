"""The meta refresh scheduler.

The harvest itself is the pipeline's business and is tested there. What is tested here
is the scheduling, because that is where this feature can hurt: a background loop that
takes the app down, hammers somebody else's API, or runs twice at once is worse than no
scheduler at all.

The refresh callable is injected, so none of this touches a network.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC

import pytest

from riftbound.config import load_config
from riftbound.data.scheduler import (
    HISTORY_LIMIT,
    MIN_INTERVAL_HOURS,
    STATUS_OFF,
    MetaScheduler,
    RunRecord,
    snapshot_age_hours,
)


@pytest.fixture()
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("RB_MODE", "local")
    monkeypatch.setenv("RB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RB_DB_PATH", str(tmp_path / "data" / "t.db"))
    monkeypatch.setattr("riftbound.config.ROOT", tmp_path)
    return load_config()


def a_record(ok=True, **kw) -> RunRecord:
    base = dict(
        started_at="2026-08-26T00:00:00+00:00", finished_at="2026-08-26T00:01:00+00:00",
        ok=ok, promoted=ok, snapshot_id="snap-1", deck_count=3000,
        duration_ms=60_000, message="",
    )
    base.update(kw)
    return RunRecord(**base)


# -- configuration ------------------------------------------------------------


def test_it_is_on_by_default_on_a_local_machine(config):
    """The failure this exists to prevent is data quietly going stale."""
    assert config.meta_refresh is True
    assert MetaScheduler(config).state.enabled


def test_hosted_mode_leaves_the_harvest_to_whatever_deploys_it(tmp_path, monkeypatch):
    monkeypatch.setenv("RB_MODE", "hosted")
    monkeypatch.setenv("RB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("riftbound.config.ROOT", tmp_path)
    scheduler = MetaScheduler(load_config())
    assert not scheduler.state.enabled
    assert scheduler.state.status == STATUS_OFF


def test_an_over_eager_interval_is_clamped(config):
    """We are a guest on somebody else's API and should behave like one."""
    scheduler = MetaScheduler(replace(config, meta_refresh_hours=0.01))
    assert scheduler.state.interval_hours == MIN_INTERVAL_HOURS


# -- running ------------------------------------------------------------------


def test_a_successful_run_is_recorded(config):
    scheduler = MetaScheduler(config, refresh=lambda budget: a_record())
    record = asyncio.run(scheduler.run_once())
    assert record is not None and record.ok
    assert scheduler.state.runs == 1
    assert scheduler.state.failures == 0
    assert scheduler.state.last_run is record


def test_a_harvest_that_raises_does_not_escape(config):
    """A refresh must never take the app down. Meta is optional data by design."""
    def explode(budget):
        raise RuntimeError("upstream on fire")

    scheduler = MetaScheduler(config, refresh=explode)
    record = asyncio.run(scheduler.run_once())
    assert record is not None
    assert not record.ok
    assert "upstream on fire" in record.message
    assert scheduler.state.failures == 1


def test_the_budget_is_passed_to_the_harvest(config):
    seen: list[float] = []

    def refresh(budget):
        seen.append(budget)
        return a_record()

    asyncio.run(MetaScheduler(replace(config, meta_refresh_budget=12.5), refresh=refresh).run_once())
    assert seen == [12.5]


def test_two_runs_do_not_overlap(config):
    """One harvest at a time, whatever asks for it.

    A timer tick landing on top of a manual refresh must not start a second harvest
    writing the same snapshot directory.
    """
    started = asyncio.Event()
    release = asyncio.Event()

    def slow(budget):
        started.set()
        # Block the worker thread until the test lets it go.
        asyncio.run(asyncio.sleep(0))
        while not release.is_set():
            pass
        return a_record()

    async def scenario():
        scheduler = MetaScheduler(config, refresh=slow)
        first = asyncio.create_task(scheduler.run_once())
        await asyncio.wait_for(started.wait(), timeout=5)
        second = await scheduler.run_once()   # while the first is still in flight
        release.set()
        return second, await first

    second, first = asyncio.run(scenario())
    assert second is None, "the second caller must be turned away, not queued"
    assert first is not None and first.ok


# -- backoff ------------------------------------------------------------------


def test_repeated_failure_backs_off(config):
    """An upstream that is down stays down; hammering it helps nobody."""
    scheduler = MetaScheduler(config, refresh=lambda b: a_record(ok=False))
    base = scheduler._interval_seconds()

    asyncio.run(scheduler.run_once())
    assert scheduler._interval_seconds() == base * 2
    asyncio.run(scheduler.run_once())
    assert scheduler._interval_seconds() == base * 4


def test_backoff_is_capped(config):
    scheduler = MetaScheduler(config, refresh=lambda b: a_record(ok=False))
    base = scheduler._interval_seconds()
    for _ in range(10):
        asyncio.run(scheduler.run_once())
    assert scheduler._interval_seconds() == base * 8


def test_one_success_clears_the_backoff(config):
    outcomes = [False, False, True]
    scheduler = MetaScheduler(config, refresh=lambda b: a_record(ok=outcomes.pop(0)))
    base = scheduler._interval_seconds()
    for _ in range(3):
        asyncio.run(scheduler.run_once())
    assert scheduler.state.consecutive_failures == 0
    assert scheduler._interval_seconds() == base


# -- history ------------------------------------------------------------------


def test_history_is_bounded(config):
    """Enough to see a pattern, not enough to be a leak."""
    scheduler = MetaScheduler(config, refresh=lambda b: a_record())
    for _ in range(HISTORY_LIMIT + 5):
        asyncio.run(scheduler.run_once())
    assert len(scheduler.state.history) == HISTORY_LIMIT
    assert scheduler.state.runs == HISTORY_LIMIT + 5


def test_newest_run_is_first(config):
    ids = iter(["a", "b", "c"])
    scheduler = MetaScheduler(config, refresh=lambda b: a_record(snapshot_id=next(ids)))
    for _ in range(3):
        asyncio.run(scheduler.run_once())
    assert [r.snapshot_id for r in scheduler.state.history] == ["c", "b", "a"]


# -- age ----------------------------------------------------------------------


def test_snapshot_age_handles_a_missing_or_broken_timestamp():
    """Never throw over a date. An unreadable stamp is an unknown age, not a crash."""
    assert snapshot_age_hours("") is None
    assert snapshot_age_hours("not a date") is None


def test_snapshot_age_is_measured_in_hours():
    from datetime import datetime, timedelta

    stamp = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    age = snapshot_age_hours(stamp)
    assert age is not None and 4.9 < age < 5.1


def test_a_naive_timestamp_is_read_as_utc():
    """Snapshots are written in UTC; a stamp without a zone is not a reason to guess."""
    from datetime import datetime, timedelta

    naive = (datetime.now(UTC) - timedelta(hours=2)).replace(tzinfo=None)
    age = snapshot_age_hours(naive.isoformat())
    assert age is not None and 1.9 < age < 2.1


# -- lifecycle ----------------------------------------------------------------


def test_a_disabled_scheduler_starts_nothing(config):
    scheduler = MetaScheduler(replace(config, meta_refresh=False))

    async def scenario():
        scheduler.start()
        assert scheduler._task is None
        await scheduler.stop()

    asyncio.run(scenario())


def test_stopping_cancels_the_loop(config):
    """A refresh must not outlive the process it belongs to."""
    async def scenario():
        scheduler = MetaScheduler(
            replace(config, meta_refresh_delay=0.01), refresh=lambda b: a_record()
        )
        scheduler.start()
        assert scheduler._task is not None
        await scheduler.stop()
        assert scheduler._task is None

    asyncio.run(scenario())
