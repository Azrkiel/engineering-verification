"""The same physical part expressed in SI and US customary units must produce
identical dispositions and margins."""

import pytest

from conftest import by_id
from everify.engine import verify_part
from everify.models import Part
from everify.units import ureg


def _part(D, t, ca, p, temp) -> Part:
    return Part.model_validate({
        "id": "U-1",
        "name": "unit-system check",
        "material": "SA-516-70",
        "geometry": {"type": "cylindrical_shell", "inside_diameter": D, "nominal_thickness": t},
        "design_conditions": {
            "design_pressure": p, "design_temperature": temp,
            "corrosion_allowance": ca, "joint_efficiency": 0.85,
        },
        "standards": ["asme-viii-div1"],
    })


def test_si_and_usc_agree(library):
    usc = _part("48 inch", "0.500 inch", "0.125 inch", "250 psi", "500 degF")
    p_si = f"{ureg.Quantity('250 psi').to('MPa'):~}"
    si = _part("1219.2 mm", "12.7 mm", "3.175 mm", p_si, "260 degC")

    run_usc = by_id(verify_part(usc, library))
    run_si = by_id(verify_part(si, library))

    assert set(run_usc) == set(run_si)
    for cid, r_usc in run_usc.items():
        r_si = run_si[cid]
        assert r_si.disposition == r_usc.disposition, cid
        if r_usc.margin is not None:
            assert r_si.margin == pytest.approx(r_usc.margin, rel=1e-9), cid
