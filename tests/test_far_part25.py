"""Golden tests for the 14 CFR Part 25 margin module.

7075-T6 example design values: Ftu = 78 ksi, Fty = 69 ksi (B-basis).
"""

import pytest

from conftest import by_id
from everify.engine import Disposition, verify_part
from everify.models import Part


def fitting_part(**overrides) -> Part:
    doc = {
        "id": "F-1",
        "name": "test fitting",
        "material": "7075-T6-sheet",
        "load_cases": [
            {
                "name": "2.5g pull-up",
                "limit_stress": "32 ksi",
                "load_path": "redundant",
                "is_fitting": True,
            }
        ],
        "standards": ["far-25"],
    }
    doc.update(overrides)
    return Part.model_validate(doc)


def test_ultimate_margin_with_fitting_factor(library):
    run = verify_part(fitting_part(), library)
    r = by_id(run)["far25.ultimate.2-5g-pull-up"]
    # MS_ult = Ftu/(FF·FS·f) − 1 = 78/(1.15×1.5×32) − 1 = 78/55.2 − 1 = +0.4130
    assert r.disposition is Disposition.PASS
    assert r.margin == pytest.approx(78 / 55.2 - 1, rel=1e-9)
    assert "25.303" in r.clause.clause
    assert "factor of safety of 1.5" in r.clause.quote


def test_limit_margin_with_fitting_factor(library):
    run = verify_part(fitting_part(), library)
    r = by_id(run)["far25.limit.2-5g-pull-up"]
    # MS_limit = Fty/(FF·f) − 1 = 69/(1.15×32) − 1 = 69/36.8 − 1 = +0.8750
    assert r.disposition is Disposition.PASS
    assert r.margin == pytest.approx(0.875, rel=1e-9)


def test_margins_without_fitting_factor(library):
    part = fitting_part(
        material="2024-T3-sheet",
        load_cases=[{"name": "case", "limit_stress": "30 ksi", "load_path": "redundant"}],
    )
    run = verify_part(part, library)
    # MS_ult = 64/(1.5×30) − 1 = +0.42222;  MS_limit = 47/30 − 1 = +0.56667
    assert by_id(run)["far25.ultimate.case"].margin == pytest.approx(64 / 45 - 1, rel=1e-9)
    assert by_id(run)["far25.limit.case"].margin == pytest.approx(47 / 30 - 1, rel=1e-9)


def test_negative_margin_fails(library):
    part = fitting_part(
        load_cases=[{"name": "hot", "limit_stress": "60 ksi", "is_fitting": True}],
    )
    run = verify_part(part, library)
    r = by_id(run)["far25.ultimate.hot"]
    # MS_ult = 78/(1.15×1.5×60) − 1 = 78/103.5 − 1 = −0.2464 → FAIL
    assert r.disposition is Disposition.FAIL
    assert r.margin == pytest.approx(78 / 103.5 - 1, rel=1e-9)
    assert run.overall_disposition is Disposition.FAIL


def test_single_load_path_rejects_b_basis(library):
    part = fitting_part(
        load_cases=[{"name": "lug", "limit_stress": "20 ksi", "load_path": "single"}],
    )
    run = verify_part(part, library)
    r = by_id(run)["far25.basis.lug"]
    assert r.disposition is Disposition.FAIL
    assert "A-basis" in r.message


def test_undeclared_basis_warns(library):
    part = fitting_part(material={
        "id": "unobtainium",
        "name": "inline material without basis",
        "category": "aerospace",
        "design_values": {"Ftu": "80 ksi", "Fty": "70 ksi"},
        "provenance": {"source": "test", "requires_verification": False},
    })
    run = verify_part(part, library)
    assert by_id(run)["far25.basis.2-5g-pull-up"].disposition is Disposition.WARN


def test_material_without_design_values_is_error(library):
    part = fitting_part(material="SA-516-70")
    run = verify_part(part, library)
    assert run.overall_disposition is Disposition.ERROR


def test_duplicate_case_names_rejected():
    with pytest.raises(Exception, match="unique"):
        fitting_part(load_cases=[
            {"name": "gust", "limit_stress": "30 ksi"},
            {"name": "gust", "limit_stress": "50 ksi"},
        ])


def test_distinct_names_with_same_slug_get_unique_check_ids(library):
    part = fitting_part(load_cases=[
        {"name": "Case A", "limit_stress": "20 ksi"},
        {"name": "case a", "limit_stress": "25 ksi"},
    ])
    run = verify_part(part, library)
    ids = [r.check_id for r in run.results]
    assert len(ids) == len(set(ids))
    assert "far25.ultimate.case-a" in ids
    assert "far25.ultimate.case-a-2" in ids
