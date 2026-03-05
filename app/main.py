from __future__ import annotations

import anyio
from contextlib import asynccontextmanager
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

try:
    from sentry_sdk import init as sentry_init
except ModuleNotFoundError:  # pragma: no cover - local/dev fallback
    sentry_init = None

try:
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi import _rate_limit_exceeded_handler
except ModuleNotFoundError:  # pragma: no cover - local/dev fallback
    RateLimitExceeded = None
    SlowAPIMiddleware = None
    _rate_limit_exceeded_handler = None

from app.api.routers import auto_builder, cards, collection, decks, health, me, meta, model_observation
from app.core.meta_auto_refresh import MetaAutoRefreshScheduler
from app.core.rate_limits import limiter
from app.core.services import get_services

logger = logging.getLogger("riftbound.api")


def _inject_bootstrap(html: str, *, config_payload: dict[str, object], boot_workspace: str = "") -> str:
    config_script = (
        "<script>\n"
        f"window.__RIFTBOUND_CONFIG__ = {json.dumps(config_payload)};\n"
        f"window.__RIFTBOUND_BOOT_WORKSPACE = {json.dumps(boot_workspace)};\n"
        "</script>"
    )
    if '<script src="vendor/supabase-auth.js"></script>' in html:
        return html.replace('<script src="vendor/supabase-auth.js"></script>', config_script + "\n  <script src=\"vendor/supabase-auth.js\"></script>")
    return html.replace("</body>", config_script + "\n</body>") if "</body>" in html else html + config_script


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = get_services()
    scheduler: MetaAutoRefreshScheduler | None = None
    if services.config.sentry_dsn and sentry_init is not None:
        sentry_init(dsn=services.config.sentry_dsn, traces_sample_rate=0.0)
    if services.config.meta_auto_refresh_enabled:
        scheduler = MetaAutoRefreshScheduler(services)
        await scheduler.start()
    try:
        yield
    finally:
        if scheduler is not None:
            await scheduler.stop()


app = FastAPI(
    title="Riftbound Deck Platform v2",
    version="0.2.0",
    description="Closed beta deck builder and analysis platform.",
    lifespan=lifespan,
)
app.state.limiter = limiter
if RateLimitExceeded is not None and _rate_limit_exceeded_handler is not None:
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
if SlowAPIMiddleware is not None:
    app.add_middleware(SlowAPIMiddleware)

services = get_services()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(services.config.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(cards.router)
app.include_router(collection.router)
app.include_router(decks.router)
app.include_router(meta.router)
app.include_router(auto_builder.router)
app.include_router(model_observation.router)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = str(uuid4())
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except anyio.EndOfStream:
        # Client disconnected (e.g. navigated away); do not log as error.
        raise
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        auth = getattr(request.state, "auth", None)
        token_claims = getattr(request.state, "token_claims", None)
        user_id = getattr(auth, "user_id", "") or getattr(token_claims, "user_id", "")
        logger.exception(
            json.dumps(
                {
                    "event": "http_request",
                    "requestId": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "userId": user_id,
                    "status": 500,
                    "durationMs": elapsed_ms,
                }
            )
        )
        raise

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
    auth = getattr(request.state, "auth", None)
    token_claims = getattr(request.state, "token_claims", None)
    user_id = getattr(auth, "user_id", "") or getattr(token_claims, "user_id", "")
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "requestId": request_id,
                "method": request.method,
                "path": request.url.path,
                "userId": user_id,
                "status": response.status_code,
                "durationMs": elapsed_ms,
            }
        )
    )
    response.headers["X-Request-Id"] = request_id
    return response


def _index_html(*, boot_workspace: str = "") -> HTMLResponse:
    raw = (services.config.web_root / "index.html").read_text(encoding="utf-8")
    html = _inject_bootstrap(
        raw,
        config_payload={
            "supabaseUrl": services.config.supabase_url,
            "supabaseAnonKey": services.config.supabase_anon_key,
            "apiBase": "",
        },
        boot_workspace=boot_workspace,
    )
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def index_app() -> HTMLResponse:
    return _index_html()


@app.get("/model-observation", include_in_schema=False)
async def model_observation_app() -> HTMLResponse:
    # The SPA shell stays public; admin-only access is enforced by the observation APIs.
    return _index_html(boot_workspace="model-observation")


if services.config.web_root.is_dir():
    app.mount("/", StaticFiles(directory=str(services.config.web_root), html=True), name="web")
