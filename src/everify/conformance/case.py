"""Conformance case schema.

A conformance case is a portable, implementation-independent statement of what
a correct implementation of a standard's rules must produce. Each case carries
the *provenance of its expected value* — the hand calculation or independent
formulation that justifies it — so the suite is reviewable by an engineer who
has never seen everify's source.

Categories:

``golden``       an independently hand-computed expected value
``identity``     two algebraically equivalent formulations must agree (e.g. the
                 ID-form of UG-27 versus the OD-form of Appendix 1-1)
``invariance``   a transformation that must not change the answer (unit system,
                 geometric scaling, co-scaling of pressure and allowable stress)
``domain-guard`` inputs outside an equation's validity domain must be refused,
                 not silently computed
``degenerate``   edge inputs (zero pressure, nothing left after corrosion) must
                 be handled without crashing or producing nonsense
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from everify.models.base import EverifyModel


class Category(str, Enum):
    GOLDEN = "golden"
    IDENTITY = "identity"
    INVARIANCE = "invariance"
    DOMAIN_GUARD = "domain-guard"
    DEGENERATE = "degenerate"


class ExpectedCheck(EverifyModel):
    """What a given check must produce."""

    check_id: str
    disposition: str | None = Field(
        default=None, description="Required disposition, e.g. PASS / FAIL / NOT_APPLICABLE"
    )
    margin: float | None = Field(default=None, description="Required margin value")
    margin_tolerance: float = Field(
        default=1e-6, description="Relative tolerance on the margin comparison"
    )
    margin_is_none: bool = Field(
        default=False, description="Require the margin to be absent (trivially satisfied)"
    )
    message_contains: str | None = None

    @model_validator(mode="after")
    def _something_asserted(self) -> "ExpectedCheck":
        if (self.disposition is None and self.margin is None
                and not self.margin_is_none and self.message_contains is None):
            raise ValueError(f"expected check {self.check_id!r} asserts nothing")
        return self


class TransformExpectation(EverifyModel):
    """A second part that must agree with the primary part.

    Used by identity and invariance cases: the transformed part is verified
    independently and its results must match the primary part's, check for
    check, within tolerance.
    """

    description: str
    part: dict[str, Any]
    margin_tolerance: float = 1e-9
    only_checks: list[str] = Field(
        default_factory=list, description="Limit comparison to these check ids (default: all)"
    )


class ConformanceCase(EverifyModel):
    id: str
    title: str
    standard: str = Field(description="Standard module id the case exercises")
    category: Category
    rationale: str = Field(
        description="Why this case is correct: hand calculation, independent formulation, "
                    "or the physical principle being asserted"
    )
    part: dict[str, Any] = Field(description="Part definition, inline material or library id")
    materials: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Case-local material records by id, so cases do not depend on the "
                    "bundled library and stay portable across implementations",
    )
    expect: list[ExpectedCheck] = Field(default_factory=list)
    expect_overall: str | None = None
    agrees_with: list[TransformExpectation] = Field(default_factory=list)
    reference: str | None = Field(
        default=None, description="Clause or publication the case is drawn from"
    )

    @model_validator(mode="after")
    def _asserts_something(self) -> "ConformanceCase":
        if not self.expect and not self.agrees_with and self.expect_overall is None:
            raise ValueError(f"case {self.id!r} asserts nothing")
        return self
