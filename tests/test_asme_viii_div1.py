"""Golden tests for the Section VIII Division 1 module.

Every expected value below is an independent hand calculation written out in
the comments, so a reviewer can re-derive each number with a pocket
calculator. SA-516-70 example allowable stress: S = 20.0 ksi through 500 °F.
"""

import pytest

from conftest import by_id
from everify.engine import Disposition, verify_part
from everify.models import Part


def shell_part(**overrides) -> Part:
    doc = {
        "id": "T-1",
        "name": "test shell",
        "material": "SA-516-70",
        "geometry": {
            "type": "cylindrical_shell",
            "inside_diameter": "48 inch",
            "nominal_thickness": "0.500 inch",
        },
        "design_conditions": {
            "design_pressure": "250 psi",
            "design_temperature": "500 degF",
            "corrosion_allowance": "0.125 inch",
            "joint_efficiency": 0.85,
        },
        "standards": ["asme-viii-div1"],
    }
    doc.update(overrides)
    return Part.model_validate(doc)


class TestCylindricalShell:
    """R = 24 + 0.125 = 24.125 in;  t_avail = 0.500 − 0.125 = 0.375 in;
    S·E = 20000 × 0.85 = 17000 psi."""

    def test_ug27c1_required_thickness(self, library):
        run = verify_part(shell_part(), library)
        r = by_id(run)["viii1.ug27c1"]
        # t = P·R/(S·E − 0.6P) = 250×24.125 / (17000 − 150) = 6031.25/16850 = 0.3579377 in
        assert r.disposition is Disposition.PASS
        assert r.margin == pytest.approx(0.375 / 0.35793769 - 1, rel=1e-5)
        assert r.clause.clause == "UG-27(c)(1)"

    def test_ug27c2_required_thickness(self, library):
        run = verify_part(shell_part(), library)
        r = by_id(run)["viii1.ug27c2"]
        # t = P·R/(2·S·E + 0.4P) = 6031.25 / (34000 + 100) = 6031.25/34100 = 0.1768695 in
        assert r.disposition is Disposition.PASS
        assert r.margin == pytest.approx(0.375 / 0.17686950 - 1, rel=1e-5)

    def test_mawp(self, library):
        run = verify_part(shell_part(), library)
        r = by_id(run)["viii1.mawp"]
        # circ:  P = S·E·t/(R + 0.6t) = 17000×0.375/24.35   = 261.8069 psi  (governs)
        # long:  P = 2·S·E·t/(R − 0.4t) = 34000×0.375/23.975 = 531.8040 psi
        assert r.disposition is Disposition.PASS
        assert r.margin == pytest.approx(261.80698 / 250 - 1, rel=1e-5)

    def test_hydrotest_info(self, library):
        run = verify_part(shell_part(), library)
        r = by_id(run)["viii1.ug99b"]
        # P_test = 1.3 × MAWP = 1.3 × 261.8069 = 340.349 psi
        assert r.disposition is Disposition.INFO
        assert "340.349" in r.substitution

    def test_undersized_shell_fails_with_correct_margin(self, library):
        part = shell_part(
            geometry={
                "type": "cylindrical_shell",
                "inside_diameter": "60 inch",
                "nominal_thickness": "0.3125 inch",
            },
            design_conditions={
                "design_pressure": "250 psi",
                "design_temperature": "300 degF",
                "corrosion_allowance": "0.0625 inch",
                "joint_efficiency": 0.85,
            },
        )
        run = verify_part(part, library)
        r = by_id(run)["viii1.ug27c1"]
        # R = 30.0625; t_req = 250×30.0625/16850 = 0.4460312 in; t_avail = 0.25 in → FAIL
        assert r.disposition is Disposition.FAIL
        assert r.margin == pytest.approx(0.25 / 0.44603116 - 1, rel=1e-5)
        assert run.overall_disposition is Disposition.FAIL

    def test_thickness_increases_with_pressure(self, library):
        margins = []
        for p in ("100 psi", "200 psi", "300 psi", "380 psi"):
            part = shell_part(design_conditions={
                "design_pressure": p, "design_temperature": "500 degF",
                "corrosion_allowance": "0.125 inch", "joint_efficiency": 0.85,
            })
            margins.append(by_id(verify_part(part, library))["viii1.ug27c1"].margin)
        assert margins == sorted(margins, reverse=True)  # margin falls as pressure rises

    def test_high_pressure_outside_domain_is_flagged(self, library):
        # P > 0.385·S·E = 6545 psi → thin-shell equation not applicable
        part = shell_part(design_conditions={
            "design_pressure": "7000 psi", "design_temperature": "500 degF",
            "joint_efficiency": 0.85,
        })
        r = by_id(verify_part(part, library))["viii1.ug27c1"]
        assert r.disposition is Disposition.NOT_APPLICABLE
        assert "Appendix 1-2" in r.message

    def test_temperature_above_table_is_error(self, library):
        part = shell_part(design_conditions={
            "design_pressure": "250 psi", "design_temperature": "800 degF",
        })
        run = verify_part(part, library)
        assert run.overall_disposition is Disposition.ERROR


class TestHeadsAndSpheres:
    def test_ellipsoidal_head(self, library):
        part = shell_part(
            geometry={
                "type": "ellipsoidal_head",
                "inside_diameter": "48 inch",
                "nominal_thickness": "0.500 inch",
            },
            design_conditions={
                "design_pressure": "250 psi", "design_temperature": "500 degF",
                "corrosion_allowance": "0.125 inch", "joint_efficiency": 1.0,
            },
        )
        r = by_id(verify_part(part, library))["viii1.app14c"]
        # K = 1 for 2:1;  D_c = 48.25;  t = 250×48.25/(40000 − 50) = 12062.5/39950 = 0.3019399 in
        assert r.disposition is Disposition.PASS
        assert r.margin == pytest.approx(0.375 / 0.30193993 - 1, rel=1e-5)

    def test_torispherical_head(self, library):
        part = shell_part(
            geometry={
                "type": "torispherical_head",
                "inside_diameter": "48 inch",
                "nominal_thickness": "0.625 inch",
            },
            design_conditions={
                "design_pressure": "250 psi", "design_temperature": "500 degF",
                "joint_efficiency": 1.0,
            },
        )
        r = by_id(verify_part(part, library))["viii1.app14d"]
        # L = D = 48; r = 0.06·48 = 2.88; L/r = 16.667; M = ¼(3 + √16.667) = 1.7706207
        # t = 250×48×1.7706207/39950 = 21247.449/39950 = 0.5318510 in
        assert r.disposition is Disposition.PASS
        assert r.margin == pytest.approx(0.625 / 0.53185104 - 1, rel=1e-5)

    def test_spherical_shell(self, library):
        part = shell_part(
            geometry={
                "type": "spherical_shell",
                "inside_diameter": "60 inch",
                "nominal_thickness": "0.250 inch",
            },
            design_conditions={
                "design_pressure": "250 psi", "design_temperature": "500 degF",
                "joint_efficiency": 1.0,
            },
        )
        r = by_id(verify_part(part, library))["viii1.ug27d"]
        # R = 30;  t = P·R/(2SE − 0.2P) = 7500/39950 = 0.1877347 in
        assert r.disposition is Disposition.PASS
        assert r.margin == pytest.approx(0.25 / 0.18773467 - 1, rel=1e-5)

    def test_hemispherical_head_matches_spherical_formula(self, library):
        part = shell_part(
            geometry={
                "type": "hemispherical_head",
                "inside_diameter": "60 inch",
                "nominal_thickness": "0.250 inch",
            },
            design_conditions={
                "design_pressure": "250 psi", "design_temperature": "500 degF",
                "joint_efficiency": 1.0,
            },
        )
        r = by_id(verify_part(part, library))["viii1.ug32.hemi"]
        assert r.margin == pytest.approx(0.25 / 0.18773467 - 1, rel=1e-5)


class TestGeneralRules:
    def test_ug16b_minimum_thickness(self, library):
        part = shell_part(
            geometry={
                "type": "cylindrical_shell",
                "inside_diameter": "12 inch",
                "nominal_thickness": "0.125 inch",
            },
            design_conditions={
                "design_pressure": "50 psi", "design_temperature": "100 degF",
                "corrosion_allowance": "0.09 inch",
            },
        )
        r = by_id(verify_part(part, library))["viii1.ug16b"]
        # t_avail = 0.035 in < 1/16 in → FAIL
        assert r.disposition is Disposition.FAIL

    def test_material_warning_attached_until_verified(self, library):
        run = verify_part(shell_part(), library)
        assert all("unverified example data" in " ".join(r.warnings) for r in run.results)

    def test_nothing_left_after_corrosion_is_error(self, library):
        part = shell_part(design_conditions={
            "design_pressure": "250 psi", "design_temperature": "500 degF",
            "corrosion_allowance": "0.5 inch",
        })
        run = verify_part(part, library)
        assert run.overall_disposition is Disposition.ERROR
