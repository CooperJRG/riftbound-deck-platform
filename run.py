from __future__ import annotations

import os
from pathlib import Path
import shlex

import uvicorn

from app.core.config import load_config


def _parse_env_value(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        lexer = shlex.shlex(text, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        parts = list(lexer)
    except ValueError:
        return text
    if not parts:
        return ""
    return " ".join(parts)


def load_dotenv_defaults(env_path: str | Path | None = None) -> dict[str, str]:
    path = Path(env_path) if env_path is not None else Path(__file__).resolve().with_name(".env")
    if not path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        clean_key = str(key or "").strip()
        if not clean_key or clean_key in os.environ:
            continue
        parsed_value = _parse_env_value(value)
        os.environ[clean_key] = parsed_value
        loaded[clean_key] = parsed_value
    return loaded


def main() -> None:
    load_dotenv_defaults()
    cfg = load_config()
    uvicorn.run("app.main:app", host=cfg.host, port=cfg.port, reload=False)


if __name__ == "__main__":
    main()
