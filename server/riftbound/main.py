"""FastAPI application.

Startup calls ``services.warm()``, so a missing bundle or an unreadable rules profile
fails immediately with a message naming the file -- rather than v2's behaviour of
booting happily and rendering empty screens.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import ConfigError
from .api.identity import build_identity_provider
from .api.routes import availability, cards, decks, meta, smart_decks, system
from .services import get_services

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s  %(message)s"
)
logger = logging.getLogger("riftbound.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = get_services()
    services.warm()
    app.state.identity_provider = build_identity_provider(services.config)
    logger.info(
        "riftbound ready — mode=%s bundle=%s cards=%d",
        services.config.mode,
        services.bundle.manifest.bundle_id,
        services.bundle.manifest.card_count,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Riftbound Deck Builder",
        version="0.1.0",
        description="Deck building with collection-aware and exclusion-aware card availability.",
        lifespan=lifespan,
    )
    config = get_services().config

    # Only the Vite dev server needs CORS; in production the API and the built UI
    # are the same origin.
    if config.dev_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.dev_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        started = time.perf_counter()
        request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                json.dumps({
                    "event": "http_request", "requestId": request_id,
                    "method": request.method, "path": request.url.path, "status": 500,
                    "durationMs": round((time.perf_counter() - started) * 1000, 2),
                })
            )
            raise
        logger.info(
            json.dumps({
                "event": "http_request", "requestId": request_id,
                "method": request.method, "path": request.url.path,
                "status": response.status_code,
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
            })
        )
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(ConfigError)
    async def config_error_handler(request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    app.include_router(system.router)
    app.include_router(cards.router)
    app.include_router(decks.router)
    app.include_router(availability.router)
    app.include_router(meta.router)
    app.include_router(smart_decks.router)

    # The built UI, when it exists. Missing dist is normal during development,
    # where Vite serves the frontend and proxies /api here.
    dist = config.web_dist
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            # An unknown /api path is a bug, not a page. Serving the app shell here
            # hands the caller HTML where it asked for JSON, and the failure surfaces
            # as `Unexpected token '<', "<!doctype "... is not valid JSON` -- which
            # says nothing about the actual problem (usually a stale server that does
            # not have the route yet). Fail as JSON, in the shape every other error
            # in this API uses.
            if full_path == "api" or full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={
                        "detail": (
                            f"No API route for /{full_path}. If the UI is newer than "
                            "the running server, restart the server."
                        )
                    },
                )
            return FileResponse(dist / "index.html")

    return app


app = create_app()
