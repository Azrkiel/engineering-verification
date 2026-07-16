"""Geometry definitions for verifiable components.

Dimensions are as-new (uncorroded) unless stated otherwise; standards modules
apply corrosion allowance per the governing code (e.g. ASME VIII-1 UG-25:
inside dimensions grow, thickness shrinks in the corroded condition).
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from everify.models.base import EverifyModel
from everify.units import LengthQ


class CylindricalShell(EverifyModel):
    type: Literal["cylindrical_shell"] = "cylindrical_shell"
    inside_diameter: LengthQ
    nominal_thickness: LengthQ


class SphericalShell(EverifyModel):
    type: Literal["spherical_shell"] = "spherical_shell"
    inside_diameter: LengthQ
    nominal_thickness: LengthQ


class EllipsoidalHead(EverifyModel):
    type: Literal["ellipsoidal_head"] = "ellipsoidal_head"
    inside_diameter: LengthQ
    nominal_thickness: LengthQ
    aspect_ratio: float = Field(
        default=2.0,
        gt=0,
        description="D/2h — ratio of inside diameter to twice the inside head depth (2.0 = standard 2:1 head)",
    )


class TorisphericalHead(EverifyModel):
    type: Literal["torispherical_head"] = "torispherical_head"
    inside_diameter: LengthQ
    nominal_thickness: LengthQ
    crown_radius: LengthQ | None = Field(
        default=None, description="Inside crown (spherical) radius L; defaults to the inside diameter"
    )
    knuckle_radius: LengthQ | None = Field(
        default=None, description="Inside knuckle radius r; defaults to 6% of the crown radius"
    )


class HemisphericalHead(EverifyModel):
    type: Literal["hemispherical_head"] = "hemispherical_head"
    inside_diameter: LengthQ
    nominal_thickness: LengthQ


class StraightPipe(EverifyModel):
    type: Literal["straight_pipe"] = "straight_pipe"
    outside_diameter: LengthQ
    nominal_wall: LengthQ
    designation: str | None = Field(
        default=None, description='Optional label, e.g. "NPS 6 Sch 40"'
    )

    @model_validator(mode="after")
    def _wall_fits(self) -> "StraightPipe":
        if self.nominal_wall * 2 >= self.outside_diameter:
            raise ValueError("nominal_wall must be less than half the outside diameter")
        return self


Geometry = Annotated[
    Union[
        CylindricalShell,
        SphericalShell,
        EllipsoidalHead,
        TorisphericalHead,
        HemisphericalHead,
        StraightPipe,
    ],
    Field(discriminator="type"),
]

PRESSURE_VESSEL_TYPES = (
    CylindricalShell,
    SphericalShell,
    EllipsoidalHead,
    TorisphericalHead,
    HemisphericalHead,
)
