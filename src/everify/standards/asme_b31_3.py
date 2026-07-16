"""ASME B31.3 Process Piping — pressure design of straight pipe (304.1).

Implements equation (3a) of para. 304.1.2 for straight pipe under internal
pressure, the t_m = t + c allowance stack of para. 304.1.1, and the nominal
wall selection including fractional mill under-tolerance. Formulas are
reproduced throughout the open literature; clause citations locate each rule.

NOT evaluated: sustained/occasional/displacement stresses (302.3.5, 319),
flexibility analysis, branch reinforcement (304.3), bends/miters (304.2),
flanges, supports, and all fabrication/examination requirements.
"""

from __future__ import annotations

from dataclasses import dataclass

from everify.engine.results import CheckResult, ComputedValue, Disposition
from everify.models.geometry import StraightPipe
from everify.models.material import AllowableStressRangeError, Material
from everify.models.part import Part
from everify.standards.base import StandardModule, register
from everify.units import Quantity, fmt, ureg

Y_CREEP_LIMIT = ureg.Quantity(900, "degF")  # Table 304.1.1: Y = 0.4 for ductile metals below the creep regime


@dataclass
class _Ctx:
    P: Quantity
    S: Quantity
    E: float
    W: float
    Y: float
    c: Quantity
    mill: float
    p_units: str
    l_units: str


class AsmeB313(StandardModule):
    id = "asme-b31-3"
    aliases = ("b31.3", "asme-b31.3", "b31-3")
    title = "ASME B31.3 Process Piping"
    edition = "2022"
    note = (
        "Straight-pipe internal pressure design (304.1) only. Flexibility, sustained and "
        "occasional stresses, branch connections, bends, and fabrication/examination "
        "requirements are not evaluated."
    )

    def applicable(self, part: Part) -> bool:
        return isinstance(part.geometry, StraightPipe)

    def run(self, part: Part) -> list[CheckResult]:
        geom = part.geometry
        dc = part.design_conditions
        if dc is None:
            return [self._error("design_conditions (pressure, temperature) are required for B31.3 checks")]
        mat = part.material
        if not isinstance(mat, Material):
            return [self._error("material reference was not resolved to a material record")]
        if mat.allowable_stress is None:
            return [self._error(
                f"material {mat.id!r} has no allowable-stress table; B31.3 design requires "
                "allowable stress S per Table A-1"
            )]
        try:
            S = mat.allowable_stress.at(dc.design_temperature)
        except AllowableStressRangeError as exc:
            return [self._error(str(exc))]

        if dc.y_coefficient is not None:
            Y = dc.y_coefficient
            y_note = f"Y = {Y:g} supplied by user"
        elif dc.design_temperature.to("kelvin") <= Y_CREEP_LIMIT.to("kelvin"):
            Y = 0.4
            y_note = "Y = 0.4 per Table 304.1.1 (ductile metals, T ≤ 482 °C / 900 °F)"
        else:
            return [self._error(
                "design temperature exceeds 900 °F: the Y coefficient of Table 304.1.1 varies in "
                "the creep regime; supply design_conditions.y_coefficient explicitly"
            )]

        ctx = _Ctx(
            P=dc.design_pressure, S=S, E=dc.quality_factor, W=dc.weld_strength_reduction,
            Y=Y, c=dc.corrosion_allowance + dc.mechanical_allowance, mill=dc.mill_tolerance,
            p_units=f"{dc.design_pressure.units:~}", l_units=f"{geom.nominal_wall.units:~}",
        )
        return self._straight_pipe(ctx, geom, y_note)

    def _error(self, message: str) -> CheckResult:
        return CheckResult(
            check_id="b313.setup",
            title="B31.3 input validation",
            clause=self.clause("300(c)", "General statements: designer responsibilities"),
            disposition=Disposition.ERROR,
            message=message,
        )

    def _straight_pipe(self, ctx: _Ctx, geom: StraightPipe, y_note: str) -> list[CheckResult]:
        D = geom.outside_diameter
        t_nom = geom.nominal_wall

        t = (ctx.P * D / (2 * (ctx.S * ctx.E * ctx.W + ctx.P * ctx.Y))).to(ctx.l_units)
        t_m = t + ctx.c
        t_nom_req = t_m / (1 - ctx.mill)

        thin_wall = t < (D / 6)
        ratio_ok = (ctx.P / (ctx.S * ctx.E)).to("dimensionless").magnitude <= 0.385

        assumptions = [
            y_note,
            f"c = corrosion + mechanical allowances = {fmt(ctx.c, ctx.l_units)} (304.1.1)",
            f"Mill under-tolerance {ctx.mill * 100:g}% applied to select nominal wall "
            "(12.5% is the ASTM seamless default).",
        ]

        computed = [
            ComputedValue(symbol="t", description="pressure design thickness, eq. (3a)", value=f"{t:~}"),
            ComputedValue(symbol="t_m", description="minimum required thickness incl. allowances", value=f"{t_m:~}"),
            ComputedValue(symbol="t_nom_required", description="required nominal wall incl. mill tolerance", value=f"{t_nom_req:~}"),
            ComputedValue(symbol="S", description="allowable stress at design temperature", value=f"{ctx.S:~}"),
            ComputedValue(symbol="E", description="quality factor (Tables A-1A/A-1B)", value=f"{ctx.E:g}"),
            ComputedValue(symbol="W", description="weld joint strength reduction factor (302.3.5(e))", value=f"{ctx.W:g}"),
            ComputedValue(symbol="Y", description="coefficient (Table 304.1.1)", value=f"{ctx.Y:g}"),
        ]

        if not (thin_wall and ratio_ok):
            return [CheckResult(
                check_id="b313.304_1_2",
                title="Straight pipe — pressure design wall thickness",
                clause=self.clause("304.1.2", "Straight pipe under internal pressure, eq. (3a)"),
                disposition=Disposition.NOT_APPLICABLE,
                formula="t = P·D / [2·(S·E·W + P·Y)]",
                computed=computed,
                criterion="applies for t < D/6 and P/(S·E) ≤ 0.385",
                assumptions=assumptions,
                message="Outside the validity domain of eq. (3a) (t ≥ D/6 or P/(S·E) > 0.385): "
                        "thick-wall design per 304.1.2(b) / K-2 required.",
            )]

        margin = float((t_nom / t_nom_req).to("dimensionless").magnitude) - 1.0
        substitution = (
            f"t = ({fmt(ctx.P, ctx.p_units)} × {fmt(D, ctx.l_units)}) / "
            f"(2 × ({fmt(ctx.S, ctx.p_units)} × {ctx.E:g} × {ctx.W:g} + "
            f"{fmt(ctx.P, ctx.p_units)} × {ctx.Y:g})) = {fmt(t, ctx.l_units)};  "
            f"t_m = t + c = {fmt(t_m, ctx.l_units)};  "
            f"t_nom_required = t_m / (1 − {ctx.mill:g}) = {fmt(t_nom_req, ctx.l_units)}"
        )
        check = CheckResult(
            check_id="b313.304_1_2",
            title=f"Straight pipe — pressure design wall thickness{f' ({geom.designation})' if geom.designation else ''}",
            clause=self.clause("304.1.2", "Straight pipe under internal pressure, eq. (3a)"),
            disposition=Disposition.PASS if margin >= 0 else Disposition.FAIL,
            formula="t = P·D / [2·(S·E·W + P·Y)];  t_m = t + c;  t_nom ≥ t_m / (1 − mill_tol)",
            substitution=substitution,
            computed=computed,
            criterion="selected nominal wall ≥ required nominal wall",
            margin=margin,
            assumptions=assumptions,
            message=None if margin >= 0 else (
                f"Selected nominal wall {fmt(t_nom, ctx.l_units)} is below the required "
                f"{fmt(t_nom_req, ctx.l_units)}."
            ),
        )

        t_eff = t_nom * (1 - ctx.mill) - ctx.c
        rating: CheckResult
        if t_eff <= 0 * t_eff:
            rating = CheckResult(
                check_id="b313.rating",
                title="Pressure capacity of selected wall (informational)",
                clause=self.clause("304.1.2", "Straight pipe under internal pressure — rearranged for P"),
                disposition=Disposition.INFO,
                message="No wall remains after allowances and mill tolerance; capacity is zero.",
            )
        else:
            p_max = (2 * t_eff * ctx.S * ctx.E * ctx.W / (D - 2 * ctx.Y * t_eff)).to(ctx.p_units)
            rating = CheckResult(
                check_id="b313.rating",
                title="Pressure capacity of selected wall (informational)",
                clause=self.clause("304.1.2", "Straight pipe under internal pressure — rearranged for P"),
                disposition=Disposition.INFO,
                formula="P_max = 2·t_eff·S·E·W / (D − 2·Y·t_eff),  t_eff = t_nom·(1 − mill_tol) − c",
                substitution=f"t_eff = {fmt(t_eff, ctx.l_units)};  P_max = {fmt(p_max, ctx.p_units)}",
                computed=[ComputedValue(symbol="P_max", description="internal pressure capacity of the selected wall", value=f"{p_max:~}")],
                assumptions=assumptions,
            )
        return [check, rating]


register(AsmeB313())
