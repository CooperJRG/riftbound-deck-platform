from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routers import cards, collection, decks, health, meta
from app.core.services import get_services


app = FastAPI(
    title="Riftbound Deck Platform v2",
    version="0.1.0",
    description="Deck builder and analysis platform (no gameplay engine).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*", "http://127.0.0.1:*", "null"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(cards.router)
app.include_router(collection.router)
app.include_router(decks.router)
app.include_router(meta.router)


@app.on_event("startup")
def startup() -> None:
    get_services()


services = get_services()
if services.config.web_root.is_dir():
    app.mount("/", StaticFiles(directory=str(services.config.web_root), html=True), name="web")

