"""Filling a cold database from the snapshot committed at ``data/meta-seed``.

A fresh deploy or a fresh clone has never harvested anything, and a full Riftools
harvest is one request per decklist -- roughly 14,700 of them. Rather than leave Explore
empty until that finishes, one real snapshot is committed to the repo and promoted at
start-up. These tests are about the one property that matters most: it never overwrites
a snapshot that got there some other way.
"""

from __future__ import annotations

from riftbound.data.meta_normalize import normalize_meta_decks
from riftbound.data.meta_snapshot import (
    load_current_meta,
    resolve_current,
    seed_meta_if_missing,
    write_snapshot,
)


def deck_payload(catalog, slug="a-deck", **overrides):
    from tests.test_meta import deck_payload as _deck_payload

    return _deck_payload(catalog, slug=slug, **overrides)


def a_seed_snapshot(tmp_path, catalog, n=5, name="seed-source"):
    """A real, valid snapshot directory -- exactly what `data/meta-seed` holds."""
    decks = normalize_meta_decks(
        [deck_payload(catalog, slug=f"{name}-{i}") for i in range(n)], catalog=catalog
    )
    return write_snapshot(tmp_path / name, decks, [], [])


def test_a_cold_meta_dir_is_seeded(tmp_path, catalog):
    seed = a_seed_snapshot(tmp_path, catalog)
    meta_dir = tmp_path / "meta"

    promoted = seed_meta_if_missing(meta_dir, seed.path)

    assert promoted is not None
    current = load_current_meta(meta_dir)
    assert current is not None
    assert current.manifest.snapshot_id == seed.manifest.snapshot_id
    assert current.manifest.deck_count == 5


def test_it_never_overwrites_a_real_snapshot(tmp_path, catalog):
    """The one property that matters: a live harvest's result is never clobbered."""
    real = a_seed_snapshot(tmp_path, catalog, n=40, name="live-harvest")
    meta_dir = tmp_path / "meta"
    written = write_snapshot(meta_dir, real.decks, [], [])
    from riftbound.data.meta_snapshot import promote_meta

    promote_meta(meta_dir, written.manifest.snapshot_id)

    seed = a_seed_snapshot(tmp_path, catalog, n=5, name="seed-source")
    promoted = seed_meta_if_missing(meta_dir, seed.path)

    assert promoted is None
    assert load_current_meta(meta_dir).manifest.deck_count == 40


def test_a_missing_seed_directory_is_not_an_error(tmp_path):
    meta_dir = tmp_path / "meta"
    assert seed_meta_if_missing(meta_dir, tmp_path / "nowhere") is None
    assert resolve_current(meta_dir) is None


def test_an_empty_seed_directory_is_not_an_error(tmp_path):
    meta_dir = tmp_path / "meta"
    empty_seed = tmp_path / "empty-seed"
    empty_seed.mkdir()
    assert seed_meta_if_missing(meta_dir, empty_seed) is None
    assert resolve_current(meta_dir) is None


def test_a_tampered_seed_is_refused_not_promoted(tmp_path, catalog):
    """Same integrity check any snapshot gets. A corrupt commit must not boot silently
    wrong -- it should leave meta absent, a state the rest of the app already handles."""
    seed = a_seed_snapshot(tmp_path, catalog)
    (seed.path / "meta.json").write_text('{"decks": [], "tournaments": [], "standings": []}')

    meta_dir = tmp_path / "meta"
    promoted = seed_meta_if_missing(meta_dir, seed.path)

    assert promoted is None
    assert resolve_current(meta_dir) is None


def test_seeding_twice_is_a_harmless_no_op(tmp_path, catalog):
    seed = a_seed_snapshot(tmp_path, catalog)
    meta_dir = tmp_path / "meta"

    first = seed_meta_if_missing(meta_dir, seed.path)
    second = seed_meta_if_missing(meta_dir, seed.path)

    assert first is not None
    assert second is None
    assert load_current_meta(meta_dir).manifest.snapshot_id == seed.manifest.snapshot_id


def test_the_meta_dir_need_not_exist_yet(tmp_path, catalog):
    """A brand-new volume: no data/meta directory at all, not even an empty one."""
    seed = a_seed_snapshot(tmp_path, catalog)
    meta_dir = tmp_path / "meta"
    assert not meta_dir.exists()

    seed_meta_if_missing(meta_dir, seed.path)

    assert load_current_meta(meta_dir) is not None


def test_the_committed_seed_itself_is_a_valid_snapshot():
    """The file this session actually generated for data/meta-seed/, read the way
    `Services.warm()` reads it. If this fails, the committed content is broken."""
    from pathlib import Path

    from riftbound.config import ROOT
    from riftbound.data.meta_snapshot import read_snapshot

    seed_dir = Path(ROOT) / "data" / "meta-seed"
    if not (seed_dir / "manifest.json").is_file():
        import pytest

        pytest.skip("no data/meta-seed committed in this checkout")

    snapshot = read_snapshot(seed_dir)
    assert snapshot.manifest.deck_count > 0
    assert len(snapshot.decks) == snapshot.manifest.deck_count
