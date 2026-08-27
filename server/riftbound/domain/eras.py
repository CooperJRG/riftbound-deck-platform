"""Format eras: the windows in which the banned list did not change.

The archive spans a banning. 1,113 of the 4,218 published lists in it — 26.4% — are
illegal today, and the damage is not confined to legality: the builder filters banned
cards out of its *pool*, but the *signal* it fills from is computed over every deck ever
recorded. Twelve of forty-nine legends carry a banned card inside their all-time top-25
play rates, and 85 of 1,040 archetype clusters have one in the core that defines them.
A win rate averaged across the same boundary describes a format nobody is playing.

So an era is a first-class thing, declared in the format profile beside the ban list it
belongs to, and every meta statistic says which one it describes.

**It is a constant, not an inference.** Across the whole archive the last deck playing
any currently-banned card is dated 2026-03-28 and the first list without one is dated
2026-03-29, with no exceptions on either side. That is a step function; detecting it
needs a date, not a model.

**On citations.** The format profile is the project's best idea precisely because every
constraint points at the rulebook section behind it. The era boundary cannot honestly do
that yet — it was derived from the corpus, not read off an announcement — so each period
carries an ``evidence`` string saying exactly how the date was established and an empty
``source`` waiting for the real one. :attr:`Era.is_cited` reports which it is, so the
distinction stays visible rather than being quietly forgotten.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

#: Era id used when a date falls outside every declared period, or when a profile
#: declares none at all. Never silently folded into a real era.
UNKNOWN_ERA = "unknown"


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Era:
    """One window of stable rules.

    ``from_date`` and ``to_date`` are both inclusive, and either may be empty: an empty
    start means "since the beginning of the archive" and an empty end means "still
    current". Open-ended on purpose — an era that has not finished must not need editing
    the day after it starts.
    """
    era_id: str
    name: str
    from_date: str = ""
    to_date: str = ""
    #: Cards this era added to the banned list, as authored names.
    bans_introduced: tuple[str, ...] = ()
    #: How the boundary was established. Always populated; see the module docstring.
    evidence: str = ""
    #: The official announcement, when one is to hand. Empty means the date is derived.
    source: str = ""

    @property
    def is_open(self) -> bool:
        """True when this era has no declared end, i.e. it is the current format."""
        return not self.to_date

    @property
    def is_cited(self) -> bool:
        """True when the boundary points at a published announcement rather than at us."""
        return bool(self.source)

    def contains(self, when: str | date | None) -> bool:
        value = when if isinstance(when, date) else parse_date(when or "")
        if value is None:
            return False
        start = parse_date(self.from_date)
        end = parse_date(self.to_date)
        if start is not None and value < start:
            return False
        return end is None or value <= end

    def describe(self) -> str:
        """One line a reader can judge the window by."""
        if not self.from_date and not self.to_date:
            return f"{self.name} — the whole archive"
        if self.is_open:
            return f"{self.name} — since {self.from_date}"
        if not self.from_date:
            return f"{self.name} — up to {self.to_date}"
        return f"{self.name} — {self.from_date} to {self.to_date}"


#: Returned when a profile declares no eras at all, so callers never handle ``None``.
#: Its single period spans everything, which is the honest reading of "nobody has told
#: us the rules ever changed".
def _unknown_era() -> Era:
    return Era(
        era_id=UNKNOWN_ERA,
        name="All time",
        evidence="This format profile declares no eras, so every date is treated alike.",
    )


@dataclass(frozen=True)
class Eras:
    """Every declared era for one format, oldest first."""
    periods: tuple[Era, ...]

    def __iter__(self):
        return iter(self.periods)

    def __len__(self) -> int:
        return len(self.periods)

    @property
    def current(self) -> Era:
        """The era in force now: the open-ended one, else the latest, else unknown."""
        if not self.periods:
            return _unknown_era()
        for era in reversed(self.periods):
            if era.is_open:
                return era
        return self.periods[-1]

    def get(self, era_id: str) -> Era | None:
        wanted = str(era_id or "").strip()
        return next((e for e in self.periods if e.era_id == wanted), None)

    def for_date(self, when: str | date | None) -> Era:
        """Which era a date belongs to. Never guesses: unknown stays unknown."""
        for era in self.periods:
            if era.contains(when):
                return era
        return _unknown_era()

    def resolve(self, era_id: str) -> Era:
        """An era by id, defaulting to the current one.

        ``"all"`` is accepted and returns a single window spanning everything, so a
        caller can offer "current format" and "all time" without special-casing either.
        """
        wanted = str(era_id or "").strip().casefold()
        if wanted in {"all", "all-time", "alltime"}:
            return Era(
                era_id="all",
                name="All time",
                evidence="Every era in the archive, including formats no longer played.",
            )
        return self.get(era_id) or self.current

    def bounds(self, era: Era) -> tuple[date | None, date | None]:
        return parse_date(era.from_date), parse_date(era.to_date)

    def filter_dates(self, rows: Iterable[tuple[str, Any]], era: Era) -> list[Any]:
        """Keep the rows whose date falls inside an era. ``rows`` is ``(date, value)``."""
        if era.era_id == "all":
            return [value for _when, value in rows]
        return [value for when, value in rows if era.contains(when)]


def eras_from(raw: Mapping[str, Any] | None) -> Eras:
    """Read the ``eras`` block of a format profile.

    Tolerant by design: a profile that declares no eras, or declares them badly, yields
    an empty set rather than failing to load a format. Legality must not depend on this
    file being right — an era only decides which decks a *statistic* is computed over.
    """
    block = raw if isinstance(raw, Mapping) else {}
    rows = block.get("periods")
    if not isinstance(rows, (list, tuple)):
        return Eras(periods=())

    out: list[Era] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        era_id = str(row.get("id") or "").strip()
        if not era_id:
            continue
        bans = row.get("bans_introduced")
        out.append(
            Era(
                era_id=era_id,
                name=str(row.get("name") or era_id).strip(),
                from_date=str(row.get("from") or "").strip(),
                to_date=str(row.get("to") or "").strip(),
                bans_introduced=tuple(
                    str(b).strip()
                    for b in (bans if isinstance(bans, (list, tuple)) else ())
                    if str(b).strip()
                ),
                evidence=str(row.get("evidence") or "").strip(),
                source=str(row.get("source") or "").strip(),
            )
        )
    # Oldest first, open-ended last. An era with no start sorts before everything.
    out.sort(key=lambda e: (e.from_date or "", e.to_date or "9999-12-31"))
    return Eras(periods=tuple(out))


def eras_for_format(rules: Any) -> Eras:
    """Pull the era list off a :class:`FormatRules` or :class:`BoundRules`.

    Takes the object rather than the path so a caller that already has the bound rules
    — which every meta route does — needs no second load.
    """
    block = getattr(rules, "eras", None)
    if block is None:
        profile = getattr(rules, "rules", None)
        block = getattr(profile, "eras", None)
    return eras_from(block)


def split_by_era(
    rows: Sequence[tuple[str, Any]], eras: Eras
) -> dict[str, list[Any]]:
    """Group ``(date, value)`` rows by the era they fall in.

    Useful for reporting how much evidence each era actually holds, which is the number
    that decides whether an era-scoped statistic can be shown at all.
    """
    out: dict[str, list[Any]] = {}
    for when, value in rows:
        out.setdefault(eras.for_date(when).era_id, []).append(value)
    return out
