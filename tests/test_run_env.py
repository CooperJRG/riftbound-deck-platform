from __future__ import annotations

from pathlib import Path

from run import load_dotenv_defaults


def test_load_dotenv_defaults_reads_basic_values(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "FOO=bar",
                "QUOTED='hello world'",
                "COMMENTED=value # trailing comment",
                "SPACED = spaced-value",
            ]
        ),
        encoding="utf-8",
    )
    for key in ("FOO", "QUOTED", "COMMENTED", "SPACED"):
        monkeypatch.delenv(key, raising=False)

    loaded = load_dotenv_defaults(env_path)

    assert loaded["FOO"] == "bar"
    assert loaded["QUOTED"] == "hello world"
    assert loaded["COMMENTED"] == "value"
    assert loaded["SPACED"] == "spaced-value"


def test_load_dotenv_defaults_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=from-file\nBAR=from-file\n", encoding="utf-8")
    monkeypatch.setenv("FOO", "from-env")
    monkeypatch.delenv("BAR", raising=False)

    loaded = load_dotenv_defaults(env_path)

    assert loaded == {"BAR": "from-file"}
