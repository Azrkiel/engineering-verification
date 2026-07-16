"""Material models: allowable-stress tables (ASME-style) and aerospace design values.

Copyright note: ASME Section II-D allowable-stress tables are copyrighted and
are NOT reproduced here. The bundled library ships EXAMPLE values compiled from
public references, every one flagged `requires_verification: true`. The
verification engine attaches a warning to every result computed from material
data the user has not explicitly marked as verified against the governing code
edition (set `provenance.verified_by_user: true` once you have done so).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from everify.models.base import EverifyModel
from everify.units import Quantity, StressQ, TemperatureQ, kelvin


class AllowableStressRangeError(ValueError):
    """Design temperature falls outside the material's allowable-stress table."""


class AllowableStressPoint(EverifyModel):
    temperature: TemperatureQ
    value: StressQ


class AllowableStress(EverifyModel):
    basis: str = Field(
        description="What these values represent and where they came from, "
        "e.g. 'Maximum allowable stress S in the style of ASME BPVC Section II-D (example values)'"
    )
    points: list[AllowableStressPoint] = Field(min_length=1)

    @model_validator(mode="after")
    def _sorted_unique(self) -> "AllowableStress":
        temps = [kelvin(p.temperature) for p in self.points]
        if sorted(temps) != temps:
            self.points = sorted(self.points, key=lambda p: kelvin(p.temperature))
            temps = sorted(temps)
        for a, b in zip(temps, temps[1:]):
            if abs(a - b) < 1e-9:
                raise ValueError("allowable_stress.points contains duplicate temperatures")
        return self

    def at(self, temperature: Quantity) -> Quantity:
        """Linear interpolation in temperature.

        Below the first tabulated point the first value is returned (allowable
        stress tables are flat at low temperature; impact-test/MDMT rules are
        out of scope and must be addressed separately). Above the last point
        we refuse to extrapolate.
        """
        tk = kelvin(temperature)
        pts = self.points
        unit = pts[0].value.units
        if tk <= kelvin(pts[0].temperature) + 1e-9:
            return pts[0].value
        for a, b in zip(pts, pts[1:]):
            ta, tb = kelvin(a.temperature), kelvin(b.temperature)
            if tk <= tb + 1e-9:
                f = (tk - ta) / (tb - ta)
                va = a.value.to(unit).magnitude
                vb = b.value.to(unit).magnitude
                return Quantity(va + f * (vb - va), unit)
        raise AllowableStressRangeError(
            f"design temperature {temperature:~} is above the last tabulated point "
            f"({pts[-1].temperature:~}); refusing to extrapolate allowable stress"
        )


class DesignValues(EverifyModel):
    """Aerospace material design values (14 CFR 25.613 style)."""

    Ftu: StressQ | None = Field(default=None, description="Design ultimate tensile strength")
    Fty: StressQ | None = Field(default=None, description="Design tensile yield strength")
    basis: Literal["A", "B", "S"] | None = Field(
        default=None,
        description="Statistical basis: A (99%/95%), B (90%/95%), S (specification minimum)",
    )
    source: str | None = None


class Provenance(EverifyModel):
    source: str
    requires_verification: bool = True
    verified_by_user: bool = False
    verification_note: str | None = Field(
        default=None,
        description="Who verified these values, against which code edition / data source, and when",
    )


class Material(EverifyModel):
    id: str
    name: str
    category: Literal["pressure", "aerospace", "general"] = "general"
    description: str | None = None
    yield_strength: StressQ | None = None
    ultimate_strength: StressQ | None = None
    allowable_stress: AllowableStress | None = None
    design_values: DesignValues | None = None
    provenance: Provenance
