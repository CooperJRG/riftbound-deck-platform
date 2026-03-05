#!/usr/bin/env python3
from __future__ import annotations

import os
import runpy
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
TARGET = WORKSPACE_ROOT / "scripts" / "benchmark_auto_builder.py"


def main() -> int:
    if not TARGET.is_file():
        raise SystemExit(f"Missing auto-builder benchmark script: {TARGET}")
    os.chdir(WORKSPACE_ROOT)
    runpy.run_path(str(TARGET), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
