"""Finding things in Riftools' ``release-v3`` store.

Riftools replaced ``/public-snapshots`` with a content-addressed release store, and
retired the old path with a hard **410 Gone** rather than a redirect. Everything that
read the old manifest stopped working at once: the decklist harvest and the matchup
table both. The meta refresh had been failing on every attempt for three weeks before
anyone looked, because a failed harvest is refused by the gate and the gate's whole job
is to leave the previous snapshot in place.

The new layout is three hops, and the indirection is the point -- objects are named by
their own hash, so a release that changes one deck reuses every other object untouched:

    /release-v3/current.json
        -> client_manifests["<set>__<family>"].path     (a manifest of artifacts)
        -> artifacts["<key>"].object_path                (the payload itself)

This module owns those three hops and nothing else. Both Riftools sources use it, so
the next time the store moves there is one place to change rather than two.

**Sets are discovered, never listed.** ``current.json`` names every set it publishes and
which is the default, so a set 5 release is picked up by the same code that found set 4 --
the discipline ``normalize.set_code_for`` follows for card sets and the old source
followed for its ``winrates-setN`` families.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .http import HttpClient, HttpError

DEFAULT_BASE_URL = "https://www.riftools.app"

#: The pointer every release is found through.
CURRENT_PATH = "/release-v3/current.json"

#: Object and manifest paths in ``current.json`` are relative to this, not to the host.
RELEASE_ROOT = "/release-v3"

#: Pull a comparable number out of "set4" so "newest" has a meaning. A set whose name
#: carries no number sorts last rather than being dropped -- it is still a real set.
_SET_NUMBER = re.compile(r"(\d+)")


@dataclass
class Release:
    """One published release, and the manifests hanging off it."""

    release_id: str = ""
    generated_at: str = ""
    schema_version: str = ""
    default_set: str = ""
    sets: tuple[str, ...] = ()
    #: ``"<set>__<family>" -> relative object path``
    client_manifests: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def manifest_path(self, set_name: str, family: str) -> str:
        return self.client_manifests.get(f"{set_name}__{family}", "")

    def ordered_sets(self) -> tuple[str, ...]:
        """Every set, newest first.

        Newest first because a caller that wants one table wants the current one, and a
        caller that wants the whole archive does not care about the order.
        """
        def rank(name: str) -> int:
            found = _SET_NUMBER.search(name)
            return int(found.group(1)) if found else -1

        return tuple(sorted(self.sets, key=rank, reverse=True))


class ReleaseReader:
    """Reads the release pointer, its manifests and their objects."""

    def __init__(self, *, base_url: str = DEFAULT_BASE_URL, client: HttpClient):
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._http = client
        self._manifests: dict[str, dict[str, Any]] = {}

    # -- the three hops --------------------------------------------------------

    def current(self) -> Release:
        payload = self._http.get_json(f"{self._base}{CURRENT_PATH}")
        if not isinstance(payload, dict):
            raise HttpError("release pointer is not an object")
        manifests = {
            str(key): str((entry or {}).get("path") or "")
            for key, entry in (payload.get("client_manifests") or {}).items()
            if isinstance(entry, dict) and entry.get("path")
        }
        if not manifests:
            raise HttpError("release pointer carries no client manifests")
        return Release(
            release_id=str(payload.get("release_id") or ""),
            generated_at=str(payload.get("generated_at") or ""),
            schema_version=str(payload.get("schema_version") or ""),
            default_set=str(payload.get("default_set") or ""),
            sets=tuple(str(s) for s in (payload.get("sets") or []) if str(s).strip()),
            client_manifests=manifests,
            summary=dict(payload.get("summary") or {}),
        )

    def manifest(self, path: str) -> dict[str, Any]:
        """One client manifest: ``artifact key -> {object_path, ...}``.

        Cached per reader. A release has a handful of manifests and several of them are
        read more than once -- the details manifest holds both the deck objects and the
        per-event chunks -- and re-fetching a 2.5 MB index for the second reader of it
        is a pointless download.
        """
        if not path:
            raise HttpError("no manifest path")
        if path in self._manifests:
            return self._manifests[path]
        payload = self._http.get_json(f"{self._base}{RELEASE_ROOT}/{path.lstrip('/')}")
        if not isinstance(payload, dict):
            raise HttpError(f"manifest {path} is not an object")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, dict):
            raise HttpError(f"manifest {path} carries no artifacts")
        self._manifests[path] = artifacts
        return artifacts

    def object_path(self, artifacts: dict[str, Any], key: str) -> str:
        entry = artifacts.get(key)
        if not isinstance(entry, dict):
            return ""
        return str(entry.get("object_path") or "")

    def object(self, object_path: str) -> Any:
        if not object_path:
            raise HttpError("no object path")
        return self._http.get_json(
            f"{self._base}{RELEASE_ROOT}/{object_path.lstrip('/')}"
        )

    def artifact(self, artifacts: dict[str, Any], key: str) -> Any:
        """The payload behind one artifact key, in one call."""
        return self.object(self.object_path(artifacts, key))
