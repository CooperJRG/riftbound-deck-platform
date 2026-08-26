"""Application configuration.

Rule 1 of this rebuild: **nothing above the project root.** Every path is derived
from a single ``ROOT`` and every required file is checked at startup with an error
that names the missing file. v2 resolved its data paths to the *parent* of the
repository and reported a missing data file as an empty page; both are impossible
here by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

# server/riftbound/config.py -> server/riftbound -> server -> ROOT
ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised at startup when configuration or required data is unusable."""


def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    raw = _env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _under_root(path: Path, *, name: str) -> Path:
    """Reject any configured path that escapes the project root."""
    resolved = path.expanduser().resolve()
    # Resolve the root at call time: it is patchable in tests, and on Windows an
    # unresolved temp path does not compare equal to its resolved form.
    root = Path(ROOT).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ConfigError(
            f"{name} resolves to {resolved}, which is outside the project root {root}. "
            f"All data must live under the project root."
        ) from exc
    return resolved


@dataclass(frozen=True)
class Config:
    root: Path
    data_dir: Path
    bundles_dir: Path
    meta_dir: Path
    rules_dir: Path
    db_path: Path
    web_dist: Path
    mode: str            # "local" | "hosted" — declared, never inferred
    host: str
    port: int
    dev_origins: tuple[str, ...]

    @property
    def is_local(self) -> bool:
        return self.mode == "local"

    def require_files(self) -> None:
        """Fail loudly, naming what is missing and how to produce it."""
        missing: list[str] = []
        if not self.rules_dir.is_dir() or not any(self.rules_dir.glob("*.json")):
            missing.append(
                f"  {self.rules_dir}/*.json — format rule profiles (ship with the repo)"
            )
        # "current" is a symlink where the OS allows one, and a pointer file where it
        # does not — stock Windows needs elevation to create symlinks.
        has_bundle = (self.bundles_dir / "current").is_dir() or (
            self.bundles_dir / "current.txt"
        ).is_file()
        if not has_bundle:
            missing.append(
                f"  {self.bundles_dir}/current — card data bundle.\n"
                f"      Build one with:  python -m riftbound.data.pipeline build --promote"
            )
        if missing:
            raise ConfigError(
                "Riftbound cannot start — required data is missing:\n"
                + "\n".join(missing)
            )


def load_dotenv(path: Path | None = None) -> list[str]:
    """Load ``.env`` into the environment, without overriding what is already set.

    Kept deliberately small — the only secret this project has is an optional API key
    for tournament data. Real environment variables always win, so a CI or shell value
    is never shadowed by a stale file. Returns the names loaded, never the values.
    """
    target = path or (Path(ROOT) / ".env")
    if not target.is_file():
        return []
    loaded: list[str] = []
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, _, value = line.partition("=")
        name = name.strip()
        if not name or name in os.environ:
            continue
        os.environ[name] = value.strip().strip("'\"")
        loaded.append(name)
    return loaded


def load_config() -> Config:
    mode = _env_str("RB_MODE", "local").lower()
    if mode not in {"local", "hosted"}:
        raise ConfigError(f"RB_MODE must be 'local' or 'hosted', got {mode!r}")

    data_dir = _under_root(Path(_env_str("RB_DATA_DIR") or ROOT / "data"), name="RB_DATA_DIR")
    port = _env_int("RB_PORT", default=int(_env_str("PORT") or 8020))

    if mode == "local":
        # Local mode has no authentication. It must never listen off-machine.
        host = _env_str("RB_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ConfigError(
                f"RB_MODE=local refuses to bind {host!r}. Local mode has no authentication, "
                f"so it only listens on loopback. Set RB_MODE=hosted to serve other machines."
            )
    else:
        host = _env_str("RB_HOST", "0.0.0.0")

    return Config(
        root=ROOT,
        data_dir=data_dir,
        bundles_dir=data_dir / "bundles",
        # Meta snapshots are optional: the builder works with none promoted, so a
        # source outage degrades the meta view and nothing else.
        meta_dir=data_dir / "meta",
        rules_dir=data_dir / "rules",
        db_path=_under_root(Path(_env_str("RB_DB_PATH") or data_dir / "riftbound.db"), name="RB_DB_PATH"),
        web_dist=ROOT / "web" / "dist",
        mode=mode,
        host=host,
        port=port,
        dev_origins=tuple(
            o.strip() for o in _env_str("RB_DEV_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()
        ),
    )
