from __future__ import annotations

import uvicorn

from app.core.config import load_config


def main() -> None:
    cfg = load_config()
    uvicorn.run("app.main:app", host=cfg.host, port=cfg.port, reload=False)


if __name__ == "__main__":
    main()

