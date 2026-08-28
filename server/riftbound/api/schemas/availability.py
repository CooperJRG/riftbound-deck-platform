"""The availability profile: the lens the builder sees the card pool through."""

from __future__ import annotations

from pydantic import Field

from ...domain.availability import DEFAULT_PENALTY, MODES, RULE_KINDS
from .base import ApiModel, StrictRequest

# -- availability -------------------------------------------------------------


class ExclusionRuleView(ApiModel):
    kind: str
    value: str
    description: str


class ExcludedCardView(ApiModel):
    """An excluded card with its name resolved.

    The server owns the catalogue, so it names these rather than leaving the client to
    display a bare id for any card it has not happened to load.
    """
    card_id: str
    name: str


class AvailabilityView(ApiModel):
    mode: str
    strict: bool
    penalty: float
    description: str
    excluded_cards: list[ExcludedCardView]
    rules: list[ExclusionRuleView]
    owned_card_count: int


class ExclusionRuleInput(StrictRequest):
    kind: str
    value: str = ""


class AvailabilityUpdate(StrictRequest):
    mode: str = Field(default="open")
    strict: bool = False
    penalty: float = DEFAULT_PENALTY
    excluded_card_ids: list[str] = Field(default_factory=list)
    rules: list[ExclusionRuleInput] = Field(default_factory=list)

    def validated_mode(self) -> str:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        return self.mode

    def validated_rules(self) -> list[ExclusionRuleInput]:
        for rule in self.rules:
            if rule.kind not in RULE_KINDS:
                raise ValueError(f"rule kind must be one of {RULE_KINDS}, got {rule.kind!r}")
        return self.rules


class ForgetResult(ApiModel):
    """What erasing actually removed. Counted rather than assumed.

    A privacy control that says "done" without saying what it did asks to be trusted at
    exactly the moment it should be showing its working.
    """
    collection_rows: int
    sessions: int
    #: The profile after the erase, so a client never renders a collection it no longer
    #: has -- collection mode is switched to open when it is left standing on nothing.
    availability: AvailabilityView
