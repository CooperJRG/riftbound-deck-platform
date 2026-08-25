"""Source adapters.

Card and deck data comes from third-party community sites that change their markup
without warning. v2 treated ingestion as one monolithic script, so any upstream change
broke *everything* and did so silently.

Here each source is a small adapter behind one interface. The pipeline runs them
independently and records per-source health in the bundle manifest, so a site that
changes its layout shows up as **that source failing** while the others keep working.
Adding a source is adding a file; it never touches the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class RawCard:
    """One printing as reported by a source, before normalisation.

    Deliberately permissive: every field is optional and untyped-ish, because the
    whole point is that upstream data is messy. Cleaning happens in ``normalize``,
    where the rules are visible and testable, not scattered through adapters.
    """
    source: str
    slug: str = ""
    title: str = ""
    set_name: str = ""
    card_number: str = ""
    rarity: str = ""
    promo: bool = False
    image_url: str = ""
    card_type: str = ""
    super_type: str = ""
    # A list of domain names from modern sources; older exports pack it as "FuryChaos".
    color: str | Sequence[str] = ""
    cost: Any = None
    might: Any = None
    tags: Sequence[str] = field(default_factory=tuple)
    effect: str = ""
    flavor: str = ""
    #: Whether the source marks this card banned. Advisory only -- the format's rules
    #: profile remains the authority on legality; this drives drift detection.
    banned: bool = False


@dataclass
class FetchResult:
    """What one adapter produced in one run."""
    name: str
    cards: list[RawCard] = field(default_factory=list)
    fetched: int = 0
    ok: bool = True
    error: str = ""
    duration_ms: int = 0


class CardSource(Protocol):
    """A source of card printings.

    Implementations must not raise: a failing source returns ``FetchResult(ok=False,
    error=...)`` so one broken site cannot abort an ingest that other sources would
    have satisfied.
    """

    name: str

    def fetch(self) -> FetchResult:
        ...
