"""Run the app: ``python -m riftbound``.

The entire start-up story. No build step is required to serve the API; when
``web/dist`` exists it is served from the same origin.
"""

from __future__ import annotations

import sys

from .config import ConfigError, load_config


def main() -> int:
    try:
        config = load_config()
        config.require_files()
    except ConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    import uvicorn

    print(f"Riftbound running at http://{config.host}:{config.port}  (mode={config.mode})")
    uvicorn.run("riftbound.main:app", host=config.host, port=config.port, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
