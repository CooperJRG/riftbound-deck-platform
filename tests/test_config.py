"""Configuration guards.

These encode two rules that v2 broke, so they must not silently regress:

* every data path stays under the project root (v2 resolved its data directory to the
  repository's *parent*, so the model in git was not the model that ran);
* local mode has no authentication and therefore cannot listen off-machine (v2 inferred
  offline mode from missing env vars, skipped token checks entirely in that mode, and
  bound 0.0.0.0 whenever PORT was set).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from riftbound.api.identity import HostedIdentityProvider, LocalIdentityProvider, build_identity_provider
from riftbound.config import Config, ConfigError, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("RB_MODE", "RB_HOST", "RB_PORT", "RB_DATA_DIR", "RB_DB_PATH", "PORT"):
        monkeypatch.delenv(name, raising=False)


# -- paths --------------------------------------------------------------------


def test_data_dir_above_the_root_is_rejected(monkeypatch):
    monkeypatch.setenv("RB_DATA_DIR", "..")
    with pytest.raises(ConfigError, match="outside the project root"):
        load_config()


def test_absolute_path_outside_the_root_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("RB_DATA_DIR", str(tmp_path))
    with pytest.raises(ConfigError, match="outside the project root"):
        load_config()


def test_db_path_outside_the_root_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("RB_DB_PATH", str(tmp_path / "elsewhere.db"))
    with pytest.raises(ConfigError, match="outside the project root"):
        load_config()


def test_default_paths_are_under_the_root():
    config = load_config()
    assert config.data_dir.is_relative_to(config.root)
    assert config.bundles_dir.is_relative_to(config.root)
    assert config.db_path.is_relative_to(config.root)


# -- mode ---------------------------------------------------------------------


def test_mode_defaults_to_local():
    assert load_config().mode == "local"


def test_unknown_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("RB_MODE", "offline")
    with pytest.raises(ConfigError, match="must be 'local' or 'hosted'"):
        load_config()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::"])
def test_local_mode_refuses_to_bind_off_machine(monkeypatch, host):
    monkeypatch.setenv("RB_MODE", "local")
    monkeypatch.setenv("RB_HOST", host)
    with pytest.raises(ConfigError, match="refuses to bind"):
        load_config()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_local_mode_allows_loopback(monkeypatch, host):
    monkeypatch.setenv("RB_MODE", "local")
    monkeypatch.setenv("RB_HOST", host)
    assert load_config().host == host


def test_hosted_mode_may_bind_publicly(monkeypatch):
    monkeypatch.setenv("RB_MODE", "hosted")
    monkeypatch.setenv("RB_HOST", "0.0.0.0")
    assert load_config().host == "0.0.0.0"


def test_mode_is_never_inferred_from_missing_configuration(monkeypatch):
    """v2 silently switched to a no-auth mode when Supabase env vars were absent."""
    monkeypatch.setenv("RB_MODE", "hosted")
    assert load_config().mode == "hosted", "an unconfigured hosted app stays hosted"


# -- identity -----------------------------------------------------------------


def _config(mode: str) -> Config:
    base = load_config()
    return Config(**{**base.__dict__, "mode": mode})


def test_local_mode_uses_the_local_identity_provider():
    assert isinstance(build_identity_provider(_config("local")), LocalIdentityProvider)


def test_hosted_mode_uses_the_hosted_provider():
    assert isinstance(build_identity_provider(_config("hosted")), HostedIdentityProvider)


def test_hosted_provider_fails_closed():
    """Not permissive-by-default: an unconfigured hosted app rejects everyone."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        HostedIdentityProvider().identify(None)  # type: ignore[arg-type]
    assert excinfo.value.status_code == 501


# -- required data ------------------------------------------------------------


def test_missing_bundle_names_the_command_that_builds_one(monkeypatch, tmp_path):
    monkeypatch.setattr("riftbound.config.ROOT", tmp_path)
    (tmp_path / "data" / "rules").mkdir(parents=True)
    (tmp_path / "data" / "rules" / "constructed.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("RB_DATA_DIR", str(tmp_path / "data"))
    config = load_config()
    with pytest.raises(ConfigError, match="pipeline build --promote"):
        config.require_files()


def test_missing_rules_are_named(monkeypatch, tmp_path):
    monkeypatch.setattr("riftbound.config.ROOT", tmp_path)
    (tmp_path / "data" / "bundles" / "current").mkdir(parents=True)
    monkeypatch.setenv("RB_DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(ConfigError, match="format rule profiles"):
        load_config().require_files()


def test_windows_pointer_file_counts_as_a_promoted_bundle(monkeypatch, tmp_path):
    """Stock Windows needs elevation for symlinks, so promotion writes current.txt."""
    monkeypatch.setattr("riftbound.config.ROOT", tmp_path)
    rules = tmp_path / "data" / "rules"
    rules.mkdir(parents=True)
    (rules / "constructed.json").write_text("{}", encoding="utf-8")
    bundles = tmp_path / "data" / "bundles"
    bundles.mkdir(parents=True)
    (bundles / "current.txt").write_text("2026-01-01T0000Z-abc123", encoding="utf-8")
    monkeypatch.setenv("RB_DATA_DIR", str(tmp_path / "data"))
    load_config().require_files()  # must not raise
