"""Bundle and source health: which card data this server is serving."""

from __future__ import annotations

from .base import ApiModel

# -- data ---------------------------------------------------------------------


class SourceHealthView(ApiModel):
    name: str
    ok: bool
    fetched: int
    accepted: int
    error: str


class BundleView(ApiModel):
    bundle_id: str
    created_at: str
    card_count: int
    printing_count: int
    set_codes: list[str]
    sources: list[SourceHealthView]
    warnings: list[str]
