"""Typed verification results: every check carries its clause citation and math."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, computed_field

from everify.models.base import EverifyModel
from everify.models.part import Part


class Disposition(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    INFO = "INFO"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


_SEVERITY = {
    Disposition.ERROR: 5,
    Disposition.FAIL: 4,
    Disposition.WARN: 3,
    Disposition.PASS: 2,
    Disposition.INFO: 1,
    Disposition.NOT_APPLICABLE: 0,
}


class ClauseRef(EverifyModel):
    standard: str = Field(description="Full standard title")
    edition: str = Field(description="Edition/revision the module was authored against")
    clause: str = Field(description="Clause / section / paragraph identifier")
    title: str
    quote: str | None = Field(
        default=None,
        description="Verbatim text where reproducible (14 CFR is public domain); omitted for copyrighted standards",
    )
    note: str | None = None

    def cite(self) -> str:
        return f"{self.standard} ({self.edition}), {self.clause}"


class ComputedValue(EverifyModel):
    symbol: str
    description: str
    value: str = Field(description="Unit-tagged value, full precision, e.g. '0.3578343... in'")


class CheckResult(EverifyModel):
    check_id: str
    title: str
    clause: ClauseRef
    disposition: Disposition
    formula: str | None = Field(default=None, description="Symbolic form, e.g. 't = P·R / (S·E − 0.6·P)'")
    substitution: str | None = Field(default=None, description="Formula with numbers substituted")
    computed: list[ComputedValue] = Field(default_factory=list)
    criterion: str | None = Field(default=None, description="Acceptance criterion, e.g. 't_available ≥ t_required'")
    margin: float | None = Field(
        default=None, description="Capacity/demand − 1 (≥ 0 acceptable); for 14 CFR checks this is the margin of safety"
    )
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    message: str | None = None


class StandardInfo(EverifyModel):
    id: str
    title: str
    edition: str
    note: str | None = None


def overall_disposition(results: list[CheckResult]) -> Disposition:
    if not results:
        return Disposition.ERROR
    worst = max((r.disposition for r in results), key=lambda d: _SEVERITY[d])
    if worst in (Disposition.ERROR, Disposition.FAIL, Disposition.WARN):
        return worst
    if any(r.disposition is Disposition.PASS for r in results):
        return Disposition.PASS
    # Only INFO / NOT_APPLICABLE results: nothing was actually verified.
    return Disposition.WARN


class VerificationRun(EverifyModel):
    part: Part
    standards: list[StandardInfo]
    results: list[CheckResult]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_disposition(self) -> Disposition:
        return overall_disposition(self.results)
