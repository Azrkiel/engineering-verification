"""Design conditions (pressure equipment) and load cases (airframe structure)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from everify.models.base import EverifyModel
from everify.units import LengthQ, PressureQ, StressQ, TemperatureQ, ureg


class DesignConditions(EverifyModel):
    design_pressure: PressureQ = Field(description="Internal design gage pressure")
    design_temperature: TemperatureQ
    corrosion_allowance: LengthQ = Field(default_factory=lambda: ureg.Quantity("0 inch"))
    mechanical_allowance: LengthQ = Field(
        default_factory=lambda: ureg.Quantity("0 inch"),
        description="Thread/groove depth and similar mechanical allowances (B31.3 304.1.1 'c' includes these)",
    )
    joint_efficiency: float = Field(
        default=1.0, gt=0, le=1.0, description="ASME VIII-1 weld joint efficiency E per UW-12"
    )
    quality_factor: float = Field(
        default=1.0, gt=0, le=1.0, description="ASME B31.3 quality factor E per Tables A-1A/A-1B"
    )
    weld_strength_reduction: float = Field(
        default=1.0, gt=0, le=1.0, description="ASME B31.3 weld joint strength reduction factor W per 302.3.5(e)"
    )
    mill_tolerance: float = Field(
        default=0.125,
        ge=0,
        lt=1,
        description="Fractional wall under-tolerance for pipe (0.125 = 12.5% for seamless per ASTM)",
    )
    y_coefficient: float | None = Field(
        default=None,
        description="ASME B31.3 Y coefficient override; defaults to 0.4 (Table 304.1.1, ductile metals below creep range)",
    )

    @model_validator(mode="after")
    def _nonnegative(self) -> "DesignConditions":
        if self.design_pressure.magnitude < 0:
            raise ValueError("design_pressure must be non-negative (gage)")
        for name in ("corrosion_allowance", "mechanical_allowance"):
            if getattr(self, name).magnitude < 0:
                raise ValueError(f"{name} must be non-negative")
        return self


class LoadCase(EverifyModel):
    """A structural load case with the peak limit stress from the user's analysis.

    everify verifies factor application and margins per 14 CFR; it does not
    perform the stress analysis itself — the limit stress comes from your
    FEA or hand analysis and its pedigree is your responsibility.
    """

    name: str
    limit_stress: StressQ = Field(
        description="Maximum tensile stress at limit load from the governing analysis"
    )
    load_path: Literal["single", "redundant"] = Field(
        default="redundant",
        description="Single load path structures require A-basis (or S-basis) design values per 25.613(b)",
    )
    is_fitting: bool = Field(
        default=False, description="Apply the 25.625 fitting factor to this case"
    )
    fitting_factor: float = Field(default=1.15, ge=1.0)
    factor_of_safety: float = Field(
        default=1.5, ge=1.0, description="Ultimate factor of safety per 14 CFR 25.303"
    )

    @model_validator(mode="after")
    def _positive_stress(self) -> "LoadCase":
        if self.limit_stress.magnitude <= 0:
            raise ValueError("limit_stress must be positive (tension); compression checks are out of scope in v1")
        return self
