"""The two shapes every API model is built on.

Responses are camelCase on the wire and snake_case in Python; requests reject unknown
fields rather than ignoring them, so a client typo is an error and not a silent no-op.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    """Response base: snake_case in Python, camelCase on the wire."""
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True)


class StrictRequest(BaseModel):
    """Request base: unknown fields are an error, not silently ignored."""
    model_config = ConfigDict(alias_generator=_camel, populate_by_name=True, extra="forbid")
