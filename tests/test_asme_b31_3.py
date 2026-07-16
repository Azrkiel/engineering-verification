"""Golden tests for the B31.3 straight-pipe module.

SA-106-B example allowable stress: S = 17.1 ksi through 500 °F.
"""

import pytest

from conftest import by_id
from everify.engine import Disposition, verify_part
from everify.models import Part


def pipe_part(**overrides) -> Part:
    doc = {
        "id": "P-1",
        "name": "test pipe",
        "material": "SA-106-B",
        "geometry": {
            "type": "straight_pipe",
            "outside_diameter": "6.625 inch",
            "nominal_wall": "0.280 inch",
        },
        "design_conditions": {
            "design_pressure": "300 psi",
            "design_temperature": "400 degF",
            "corrosion_allowance": "0.0625 inch",
        },
        "standards": ["asme-b31-3"],
    }
    doc.update(overrides)
    return Part.model_validate(doc)


def test_golden_wall_thickness(library):
    run = verify_part(pipe_part(), library)
    r = by_id(run)["b313.304_1_2"]
    # t = P·D/(2(SEW + PY)) = 300×6.625 / (2×(17100 + 300×0.4)) = 1987.5/34440 = 0.0577091 in
    # t_m = t + c = 0.0577091 + 0.0625 = 0.1202091 in
    # t_nom_required = t_m/(1 − 0.125) = 0.1202091/0.875 = 0.1373818 in;  0.280 ≥ 0.1373818 → PASS
    assert r.disposition is Disposition.PASS
    assert r.margin == pytest.approx(0.280 / 0.13738178 - 1, rel=1e-5)


def test_rating_info(library):
    run = verify_part(pipe_part(), library)
    r = by_id(run)["b313.rating"]
    # t_eff = 0.280×0.875 − 0.0625 = 0.1825 in
    # P_max = 2×0.1825×17100/(6.625 − 0.8×0.1825) = 6241.5/6.479 = 963.34 psi
    assert r.disposition is Disposition.INFO
    assert "963.3" in r.substitution


def test_undersized_wall_fails(library):
    part = pipe_part(geometry={
        "type": "straight_pipe",
        "outside_diameter": "6.625 inch",
        "nominal_wall": "0.109 inch",
    })
    run = verify_part(part, library)
    assert by_id(run)["b313.304_1_2"].disposition is Disposition.FAIL
    assert run.overall_disposition is Disposition.FAIL


def test_creep_range_requires_explicit_y(library):
    part = pipe_part(design_conditions={
        "design_pressure": "300 psi", "design_temperature": "950 degF",
    })
    run = verify_part(part, library)
    # 950 °F: Y must be supplied — and the example S table also ends at 500 °F.
    assert run.overall_disposition is Disposition.ERROR


def test_mill_tolerance_default(library):
    # Zero mill tolerance lowers the required nominal wall: margin must improve.
    base = by_id(verify_part(pipe_part(), library))["b313.304_1_2"].margin
    part = pipe_part(design_conditions={
        "design_pressure": "300 psi", "design_temperature": "400 degF",
        "corrosion_allowance": "0.0625 inch", "mill_tolerance": 0.0,
    })
    loose = by_id(verify_part(part, library))["b313.304_1_2"].margin
    assert loose > base
