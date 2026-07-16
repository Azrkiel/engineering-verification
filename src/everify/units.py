"""Shared unit registry and pydantic-compatible quantity types.

Every physical input carries explicit units (e.g. "250 psi", "6.625 inch");
bare numbers are rejected so that unit mistakes cannot silently corrupt
results. Quantities serialize to plain strings ("0.375 in") which parse back
to identical values, keeping certificates round-trippable.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

import pint
from pydantic import BeforeValidator, PlainSerializer

ureg = pint.UnitRegistry()
Quantity = ureg.Quantity

# "<number> <unit>" — parsed as (magnitude, unit) rather than a pint expression,
# so offset units like degF work and "500degF * 2" style expressions are rejected.
_NUM_UNIT = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(\S.*?)\s*$")


class QuantityParseError(ValueError):
    """Raised when a value cannot be interpreted as a unit-tagged quantity."""


def parse_quantity(value: Any) -> Quantity:
    if isinstance(value, Quantity):
        return value
    if isinstance(value, str):
        m = _NUM_UNIT.match(value)
        if m is None:
            raise QuantityParseError(
                f"could not parse quantity {value!r}: expected '<number> <unit>', e.g. '250 psi'"
            )
        magnitude, unit = m.groups()
        try:
            return ureg.Quantity(float(magnitude), unit)
        except Exception as exc:  # pint raises several exception types
            raise QuantityParseError(f"could not parse quantity {value!r}: {exc}") from exc
    if isinstance(value, dict) and "magnitude" in value and "units" in value:
        return ureg.Quantity(value["magnitude"], value["units"])
    if isinstance(value, (int, float)):
        raise QuantityParseError(
            f"bare number {value!r} is not allowed: quantities must carry units, e.g. '250 psi'"
        )
    raise QuantityParseError(f"unsupported quantity value: {value!r}")


def _serialize(q: Quantity) -> str:
    return f"{q:~}"


def _checked(dimensionality: str):
    def validate(value: Any) -> Quantity:
        q = parse_quantity(value)
        if not q.check(dimensionality):
            raise QuantityParseError(
                f"expected a quantity with dimensionality {dimensionality}, "
                f"got {value!r} with dimensionality {q.dimensionality}"
            )
        return q

    return validate


def qty_type(dimensionality: str):
    return Annotated[
        Quantity,
        BeforeValidator(_checked(dimensionality)),
        PlainSerializer(_serialize, return_type=str, when_used="always"),
    ]


PressureQ = qty_type("[pressure]")
StressQ = qty_type("[pressure]")
LengthQ = qty_type("[length]")
TemperatureQ = qty_type("[temperature]")


def kelvin(t: Quantity) -> float:
    return t.to("kelvin").magnitude


def fmt(q: Quantity, units: str | None = None, sig: int = 6) -> str:
    """Human-readable rounded rendering, e.g. fmt(q, 'in') -> '0.357935 in'."""
    if units is not None:
        q = q.to(units)
    return f"{q.magnitude:.{sig}g} {q.units:~}"
