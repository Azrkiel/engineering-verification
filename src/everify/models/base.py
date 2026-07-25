"""Shared pydantic base model configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class EverifyModel(BaseModel):
    """Base for all everify schemas.

    - arbitrary_types_allowed: pint Quantity fields
    - extra="forbid": typos in engineering input files must fail loudly,
      never be silently ignored
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
