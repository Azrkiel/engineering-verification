"""Cross-validation properties of the standards modules.

These tests verify the implementation against *independent* formulations and
exact mathematical identities rather than single hand-picked numbers:

1. ID-form vs OD-form identity — ASME Mandatory Appendix 1-1 publishes the
   shell equations in outside-radius form; they are algebraically identical to
   the UG-27 inside-radius forms, so both must agree to float precision.
2. Forward/inverse closure — solving for required thickness at pressure P and
   then computing MAWP at exactly that thickness must return exactly P.
3. Physical invariances — margins are invariant under unit-system choice,
   geometric scaling (dimensionless margins), and co-scaling of P and S.
4. Degenerate inputs — zero design pressure must not crash (margin is None).
"""

import math
import random
from typing import ClassVar

import pytest
from conftest import by_id

from everify.engine import Disposition, verify_part
from everify.models import Part
from everify.units import Quantity, parse_quantity, ureg


def computed(result, symbol):
    for c in result.computed:
        if c.symbol == symbol:
            return parse_quantity(c.value)
    raise KeyError(f"{symbol} not in {[c.symbol for c in result.computed]}")


def make_part(geometry, conditions, standards=("asme-viii-div1",), material="SA-516-70"):
    return Part.model_validate({
        "id": "PROP", "name": "property test", "material": material,
        "geometry": geometry, "design_conditions": conditions,
        "standards": list(standards),
    })


class TestOdFormIdentities:
    """UG-27 ID-form vs Mandatory Appendix 1-1 OD-form, swept over a grid."""

    GRID: ClassVar[list[tuple[float, float, float, float]]] = [
        (P, R, S, E)
        for P in (15.0, 150.0, 600.0)      # psi
        for R in (6.0, 24.0, 120.0)        # inch
        for S in (15000.0, 20000.0)        # psi
        for E in (0.7, 0.85, 1.0)
    ]

    def test_cylinder_circumferential(self, library):
        for P, R, S_val, E in self.GRID:
            if S_val != 20000.0:
                continue  # library material fixes S; R and E still sweep
            part = make_part(
                {"type": "cylindrical_shell", "inside_diameter": f"{2 * R} inch",
                 "nominal_thickness": "2 inch"},
                {"design_pressure": f"{P} psi", "design_temperature": "100 degF",
                 "joint_efficiency": E},
            )
            r = by_id(verify_part(part, library))["viii1.ug27c1"]
            t = computed(r, "t_required").to("inch").magnitude
            # Appendix 1-1 OD form: t = P·Ro/(S·E + 0.4·P) with Ro = R + t
            ro = R + t
            t_od = P * ro / (S_val * E + 0.4 * P)
            assert t_od == pytest.approx(t, rel=1e-9), (P, R, E)

    def test_sphere(self, library):
        for P, R, S_val, E in self.GRID:
            if S_val != 20000.0:
                continue
            part = make_part(
                {"type": "spherical_shell", "inside_diameter": f"{2 * R} inch",
                 "nominal_thickness": "2 inch"},
                {"design_pressure": f"{P} psi", "design_temperature": "100 degF",
                 "joint_efficiency": E},
            )
            r = by_id(verify_part(part, library))["viii1.ug27d"]
            t = computed(r, "t_required").to("inch").magnitude
            # Appendix 1-1 OD form: t = P·Ro/(2·S·E + 0.8·P) with Ro = R + t
            ro = R + t
            t_od = P * ro / (2 * S_val * E + 0.8 * P)
            assert t_od == pytest.approx(t, rel=1e-9), (P, R, E)


class TestForwardInverseClosure:
    """nominal = t_required(P) + CA  ⇒  MAWP margin must be exactly zero."""

    S, E, P = 20000.0, 0.85, 250.0  # psi, -, psi

    def _mawp_margin(self, library, geometry, conditions):
        part = make_part(geometry, conditions)
        return by_id(verify_part(part, library))["viii1.mawp"].margin

    def test_cylinder_with_corrosion(self, library):
        D, CA = 48.0, 0.125
        R = D / 2 + CA
        t = self.P * R / (self.S * self.E - 0.6 * self.P)
        m = self._mawp_margin(
            library,
            {"type": "cylindrical_shell", "inside_diameter": f"{D} inch",
             "nominal_thickness": Quantity(t + CA, "inch")},
            {"design_pressure": f"{self.P} psi", "design_temperature": "100 degF",
             "corrosion_allowance": f"{CA} inch", "joint_efficiency": self.E},
        )
        assert m == pytest.approx(0.0, abs=1e-9)

    def test_sphere(self, library):
        R = 30.0
        t = self.P * R / (2 * self.S * self.E - 0.2 * self.P)
        m = self._mawp_margin(
            library,
            {"type": "spherical_shell", "inside_diameter": f"{2 * R} inch",
             "nominal_thickness": Quantity(t, "inch")},
            {"design_pressure": f"{self.P} psi", "design_temperature": "100 degF",
             "joint_efficiency": self.E},
        )
        assert m == pytest.approx(0.0, abs=1e-9)

    def test_ellipsoidal_head(self, library):
        D = 48.0  # 2:1 head, K = 1
        t = self.P * D / (2 * self.S * self.E - 0.2 * self.P)
        m = self._mawp_margin(
            library,
            {"type": "ellipsoidal_head", "inside_diameter": f"{D} inch",
             "nominal_thickness": Quantity(t, "inch")},
            {"design_pressure": f"{self.P} psi", "design_temperature": "100 degF",
             "joint_efficiency": self.E},
        )
        assert m == pytest.approx(0.0, abs=1e-9)

    def test_torispherical_head(self, library):
        D = 48.0
        L, r = D, 0.06 * D  # module defaults
        M = (3 + math.sqrt(L / r)) / 4
        t = self.P * L * M / (2 * self.S * self.E - 0.2 * self.P)
        m = self._mawp_margin(
            library,
            {"type": "torispherical_head", "inside_diameter": f"{D} inch",
             "nominal_thickness": Quantity(t, "inch")},
            {"design_pressure": f"{self.P} psi", "design_temperature": "100 degF",
             "joint_efficiency": self.E},
        )
        assert m == pytest.approx(0.0, abs=1e-9)

    def test_hemispherical_head(self, library):
        D = 60.0
        L = D / 2
        t = self.P * L / (2 * self.S * self.E - 0.2 * self.P)
        m = self._mawp_margin(
            library,
            {"type": "hemispherical_head", "inside_diameter": f"{D} inch",
             "nominal_thickness": Quantity(t, "inch")},
            {"design_pressure": f"{self.P} psi", "design_temperature": "100 degF",
             "joint_efficiency": self.E},
        )
        assert m == pytest.approx(0.0, abs=1e-9)

    def test_b313_exact_wall_zero_margin_and_pmax_closure(self, library):
        P, D, S, c, mill = 300.0, 6.625, 17100.0, 0.0625, 0.125
        t = P * D / (2 * (S + P * 0.4))
        t_nom = (t + c) / (1 - mill)
        part = make_part(
            {"type": "straight_pipe", "outside_diameter": f"{D} inch",
             "nominal_wall": Quantity(t_nom, "inch")},
            {"design_pressure": f"{P} psi", "design_temperature": "400 degF",
             "corrosion_allowance": f"{c} inch"},
            standards=("asme-b31-3",), material="SA-106-B",
        )
        results = by_id(verify_part(part, library))
        assert results["b313.304_1_2"].margin == pytest.approx(0.0, abs=1e-9)
        p_max = computed(results["b313.rating"], "P_max").to("psi").magnitude
        assert p_max == pytest.approx(P, rel=1e-9)


class TestInvariances:
    BASE_GEOM: ClassVar[dict[str, str]] = {
        "type": "cylindrical_shell", "inside_diameter": "48 inch",
        "nominal_thickness": "0.5 inch",
    }
    BASE_COND: ClassVar[dict[str, object]] = {
        "design_pressure": "250 psi", "design_temperature": "100 degF",
        "corrosion_allowance": "0.125 inch", "joint_efficiency": 0.85,
    }
    SCALE_FREE = ("viii1.ug27c1", "viii1.ug27c2", "viii1.mawp")

    def _margins(self, library, geom, cond, keys):
        results = by_id(verify_part(make_part(geom, cond), library))
        return {k: results[k].margin for k in keys}

    def test_geometric_scaling_leaves_margins_unchanged(self, library):
        base = self._margins(library, self.BASE_GEOM, self.BASE_COND, self.SCALE_FREE)
        k = 3.7
        scaled_geom = {"type": "cylindrical_shell",
                       "inside_diameter": f"{48 * k} inch",
                       "nominal_thickness": f"{0.5 * k} inch"}
        scaled_cond = dict(self.BASE_COND, corrosion_allowance=f"{0.125 * k} inch")
        scaled = self._margins(library, scaled_geom, scaled_cond, self.SCALE_FREE)
        for key in self.SCALE_FREE:
            assert scaled[key] == pytest.approx(base[key], rel=1e-9), key

    def test_random_unit_systems_agree(self, library):
        all_keys = (*self.SCALE_FREE, "viii1.ug16b")
        base = self._margins(library, self.BASE_GEOM, self.BASE_COND, all_keys)
        rng = random.Random(20260717)
        p_units = ["psi", "kPa", "MPa", "bar"]
        l_units = ["inch", "mm", "cm", "m"]
        t_units = ["degF", "degC", "kelvin"]
        for _ in range(12):
            pu, lu, tu = rng.choice(p_units), rng.choice(l_units), rng.choice(t_units)
            geom = {
                "type": "cylindrical_shell",
                "inside_diameter": f"{ureg.Quantity(48, 'inch').to(lu):~}",
                "nominal_thickness": f"{ureg.Quantity(0.5, 'inch').to(lu):~}",
            }
            cond = {
                "design_pressure": f"{ureg.Quantity(250, 'psi').to(pu):~}",
                "design_temperature": f"{ureg.Quantity(100, 'degF').to(tu):~}",
                "corrosion_allowance": f"{ureg.Quantity(0.125, 'inch').to(lu):~}",
                "joint_efficiency": 0.85,
            }
            other = self._margins(library, geom, cond, all_keys)
            for key in all_keys:
                assert other[key] == pytest.approx(base[key], rel=1e-9), (key, pu, lu, tu)

    def test_costress_scaling_p_and_s_together(self, library):
        # Doubling both P and S (inline material) leaves every margin unchanged.
        def margins(scale):
            material = {
                "id": "M", "name": "inline", "category": "pressure",
                "allowable_stress": {
                    "basis": "test",
                    "points": [{"temperature": "200 degF", "value": f"{20000 * scale} psi"}],
                },
                "provenance": {"source": "test", "requires_verification": False},
            }
            part = Part.model_validate({
                "id": "PROP", "name": "co-scale", "material": material,
                "geometry": self.BASE_GEOM,
                "design_conditions": dict(self.BASE_COND,
                                          design_pressure=f"{250 * scale} psi"),
                "standards": ["asme-viii-div1"],
            })
            results = by_id(verify_part(part, library))
            return {k: results[k].margin for k in (*self.SCALE_FREE, "viii1.ug16b")}

        one, two = margins(1.0), margins(2.5)
        for key, value in one.items():
            assert two[key] == pytest.approx(value, rel=1e-9), key


class TestDegenerateInputs:
    def test_zero_pressure_does_not_crash(self, library):
        part = make_part({"type": "cylindrical_shell",
                          "inside_diameter": "48 inch",
                          "nominal_thickness": "0.5 inch"},
                         {"design_pressure": "0 psi", "design_temperature": "100 degF"})
        run = verify_part(part, library)
        results = by_id(run)
        assert results["viii1.ug27c1"].disposition is Disposition.PASS
        assert results["viii1.ug27c1"].margin is None
        assert results["viii1.mawp"].margin is None
        assert run.overall_disposition is Disposition.PASS

    def test_zero_pressure_pipe_without_allowances(self, library):
        part = make_part(
            {"type": "straight_pipe", "outside_diameter": "6.625 inch",
             "nominal_wall": "0.280 inch"},
            {"design_pressure": "0 psi", "design_temperature": "100 degF"},
            standards=("asme-b31-3",), material="SA-106-B",
        )
        run = verify_part(part, library)
        assert by_id(run)["b313.304_1_2"].margin is None
        assert run.overall_disposition is Disposition.PASS

    def test_quantity_serialization_round_trips_exactly(self):
        rng = random.Random(42)
        for _ in range(200):
            x = rng.uniform(-12, 8)
            value = 10 ** x * rng.choice([1, -1])
            q = Quantity(value, "inch")
            back = parse_quantity(f"{q:~}")
            assert back.magnitude == value
            assert back.units == q.units
