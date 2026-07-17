"""ASME BPVC Section VIII, Division 1 — design-by-rule checks for internal pressure.

Implements the classic thin-wall design equations (UG-27 shells; UG-32 /
Mandatory Appendix 1-4 formed heads), MAWP back-calculation, the UG-16(b)
minimum thickness rule, and the UG-99(b) hydrostatic test pressure. The
equations themselves are not copyrightable and are reproduced throughout the
open engineering literature; clause citations identify where each rule lives
in the Code. Corroded-condition dimensions follow UG-25 practice: inside
dimensions grow by the corrosion allowance, available thickness shrinks by it.

NOT evaluated (non-exhaustive): external pressure (UG-28), nozzle
reinforcement (UG-37), MDMT / impact testing (UG-20(f), UCS-66), fatigue,
supports, attachments, fabrication and inspection requirements. A PASS here
is a necessary, never a sufficient, condition for Code compliance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from everify.engine.results import CheckResult, ComputedValue, Disposition, capacity_margin
from everify.models.geometry import (
    CylindricalShell,
    EllipsoidalHead,
    HemisphericalHead,
    SphericalShell,
    TorisphericalHead,
)
from everify.models.material import AllowableStressRangeError, Material
from everify.models.part import Part
from everify.standards.base import StandardModule, register
from everify.units import Quantity, fmt

MIN_THICKNESS = Quantity("0.0625 inch")  # UG-16(b): 1/16 in. exclusive of corrosion allowance
HYDRO_FACTOR = 1.3  # UG-99(b)

CORRODED_ASSUMPTION = (
    "Dimensions evaluated in the fully corroded condition (UG-25): inside dimensions "
    "increased by the corrosion allowance, available thickness reduced by it."
)
STATIC_HEAD_ASSUMPTION = (
    "Static liquid head is assumed negligible; P is taken as the pressure at the top of "
    "the vessel. Add static head where significant (UG-21)."
)


@dataclass
class _Ctx:
    P: Quantity  # internal design gage pressure
    S: Quantity  # maximum allowable stress at design temperature
    E: float  # joint efficiency (UW-12)
    CA: Quantity  # corrosion allowance
    material: Material
    p_units: str
    l_units: str
    assumptions: list[str]


class AsmeViiiDiv1(StandardModule):
    id = "asme-viii-div1"
    aliases = ("asme-viii-1", "asme-bpvc-viii-1", "viii-1")
    title = "ASME Boiler and Pressure Vessel Code, Section VIII, Division 1"
    edition = "2023"
    note = (
        "Internal-pressure design-by-rule checks only. External pressure (UG-28), nozzle "
        "reinforcement (UG-37), MDMT/impact (UCS-66), fatigue, and all other Code "
        "requirements are not evaluated."
    )

    SUPPORTED = (
        CylindricalShell,
        SphericalShell,
        EllipsoidalHead,
        TorisphericalHead,
        HemisphericalHead,
    )

    def applicable(self, part: Part) -> bool:
        return isinstance(part.geometry, self.SUPPORTED)

    def run(self, part: Part) -> list[CheckResult]:
        if not self.applicable(part):
            return [CheckResult(
                check_id=f"{self.id}.not_applicable",
                title=self.title,
                clause=self.clause("U-1", "Scope"),
                disposition=Disposition.NOT_APPLICABLE,
                message="Part geometry is not a pressure component covered by this module.",
            )]
        err = self._context_errors(part)
        if err:
            return err
        ctx = self._context(part)
        geom = part.geometry
        if isinstance(geom, CylindricalShell):
            return self._cylindrical(ctx, geom)
        if isinstance(geom, SphericalShell):
            return self._spherical(ctx, geom)
        if isinstance(geom, EllipsoidalHead):
            return self._ellipsoidal(ctx, geom)
        if isinstance(geom, TorisphericalHead):
            return self._torispherical(ctx, geom)
        if isinstance(geom, HemisphericalHead):
            return self._hemispherical(ctx, geom)
        return [self._error(f"unsupported geometry type {type(geom).__name__}")]

    # ------------------------------------------------------------------ setup

    def _context_errors(self, part: Part) -> list[CheckResult]:
        if part.design_conditions is None:
            return [self._error("design_conditions (pressure, temperature) are required for Section VIII checks")]
        mat = part.material
        if not isinstance(mat, Material):
            return [self._error("material reference was not resolved to a material record")]
        if mat.allowable_stress is None:
            return [self._error(
                f"material {mat.id!r} has no allowable-stress table; Section VIII design "
                "requires maximum allowable stress values (Section II-D)"
            )]
        try:
            mat.allowable_stress.at(part.design_conditions.design_temperature)
        except AllowableStressRangeError as exc:
            return [self._error(str(exc))]
        dc = part.design_conditions
        if part.geometry is not None and hasattr(part.geometry, "nominal_thickness"):
            if part.geometry.nominal_thickness - dc.corrosion_allowance <= 0 * dc.corrosion_allowance:
                return [self._error(
                    "no thickness remains after corrosion allowance; increase nominal thickness"
                )]
        return []

    def _context(self, part: Part) -> _Ctx:
        dc = part.design_conditions
        mat = part.material
        S = mat.allowable_stress.at(dc.design_temperature)
        assumptions = [CORRODED_ASSUMPTION, STATIC_HEAD_ASSUMPTION]
        if mat.allowable_stress.clamped_below(dc.design_temperature):
            first = mat.allowable_stress.points[0].temperature
            assumptions.append(
                f"Design temperature {dc.design_temperature:~} is below the first tabulated "
                f"allowable-stress point ({first:~}); S is taken at that first point. "
                "Low-temperature (MDMT/impact, UCS-66) requirements are NOT evaluated."
            )
        return _Ctx(
            P=dc.design_pressure,
            S=S,
            E=dc.joint_efficiency,
            CA=dc.corrosion_allowance,
            material=mat,
            p_units=f"{dc.design_pressure.units:~}",
            l_units=f"{part.geometry.nominal_thickness.units:~}",
            assumptions=assumptions,
        )

    def _error(self, message: str) -> CheckResult:
        return CheckResult(
            check_id="viii1.setup",
            title="Section VIII, Division 1 input validation",
            clause=self.clause("U-2", "General: user responsibilities and design inputs"),
            disposition=Disposition.ERROR,
            message=message,
        )

    # ------------------------------------------------------------- geometries

    def _cylindrical(self, ctx: _Ctx, geom: CylindricalShell) -> list[CheckResult]:
        R = geom.inside_diameter / 2 + ctx.CA
        t_avail = geom.nominal_thickness - ctx.CA
        results: list[CheckResult] = []

        # UG-27(c)(1) — circumferential stress (governs for E equal on both joints)
        circ_ok = ctx.P <= 0.385 * ctx.S * ctx.E
        t_circ = (ctx.P * R / (ctx.S * ctx.E - 0.6 * ctx.P)).to(ctx.l_units) if circ_ok else None
        results.append(self._thickness_result(
            ctx,
            check_id="viii1.ug27c1",
            title="Cylindrical shell — required thickness, circumferential stress",
            clause=self.clause("UG-27(c)(1)", "Thickness of shells under internal pressure — circumferential stress (longitudinal joints)"),
            formula="t = P·R / (S·E − 0.6·P)",
            t_req=t_circ,
            t_avail=t_avail,
            char_dim=("R", "inside radius, corroded", R),
            valid=circ_ok and (t_circ is None or t_circ <= 0.5 * R) and t_avail <= 0.5 * R,
            validity_note="applies for t ≤ 0.5·R and P ≤ 0.385·S·E; outside this domain use Mandatory Appendix 1-2 (thick shells)",
            substitution=(
                f"t = ({fmt(ctx.P, ctx.p_units)} × {fmt(R, ctx.l_units)}) / "
                f"({fmt(ctx.S, ctx.p_units)} × {ctx.E:g} − 0.6 × {fmt(ctx.P, ctx.p_units)})"
                + (f" = {fmt(t_circ, ctx.l_units)}" if t_circ is not None else "")
            ),
        ))

        # UG-27(c)(2) — longitudinal stress
        long_ok = ctx.P <= 1.25 * ctx.S * ctx.E
        t_long = (ctx.P * R / (2 * ctx.S * ctx.E + 0.4 * ctx.P)).to(ctx.l_units) if long_ok else None
        results.append(self._thickness_result(
            ctx,
            check_id="viii1.ug27c2",
            title="Cylindrical shell — required thickness, longitudinal stress",
            clause=self.clause("UG-27(c)(2)", "Thickness of shells under internal pressure — longitudinal stress (circumferential joints)"),
            formula="t = P·R / (2·S·E + 0.4·P)",
            t_req=t_long,
            t_avail=t_avail,
            char_dim=("R", "inside radius, corroded", R),
            valid=long_ok and (t_long is None or t_long <= 0.5 * R) and t_avail <= 0.5 * R,
            validity_note="applies for t ≤ 0.5·R and P ≤ 1.25·S·E; outside this domain use Mandatory Appendix 1-2 (thick shells)",
            substitution=(
                f"t = ({fmt(ctx.P, ctx.p_units)} × {fmt(R, ctx.l_units)}) / "
                f"(2 × {fmt(ctx.S, ctx.p_units)} × {ctx.E:g} + 0.4 × {fmt(ctx.P, ctx.p_units)})"
                + (f" = {fmt(t_long, ctx.l_units)}" if t_long is not None else "")
            ),
        ))

        # MAWP at available (corroded) thickness
        mawp_circ = (ctx.S * ctx.E * t_avail / (R + 0.6 * t_avail)).to(ctx.p_units)
        mawp_long = (2 * ctx.S * ctx.E * t_avail / (R - 0.4 * t_avail)).to(ctx.p_units)
        mawp = min(mawp_circ, mawp_long)
        results.append(self._mawp_result(
            ctx, mawp,
            formula="MAWP = min[ S·E·t/(R + 0.6·t) , 2·S·E·t/(R − 0.4·t) ]",
            substitution=(
                f"MAWP = min[ {fmt(mawp_circ, ctx.p_units)} (circumferential), "
                f"{fmt(mawp_long, ctx.p_units)} (longitudinal) ] = {fmt(mawp, ctx.p_units)}"
            ),
            extra=[
                ComputedValue(symbol="t", description="available thickness, corroded", value=f"{t_avail:~}"),
                ComputedValue(symbol="R", description="inside radius, corroded", value=f"{R:~}"),
            ],
        ))
        results.append(self._ug16b(ctx, t_avail))
        results.append(self._ug99(ctx, mawp))
        return results

    def _spherical(self, ctx: _Ctx, geom: SphericalShell) -> list[CheckResult]:
        R = geom.inside_diameter / 2 + ctx.CA
        t_avail = geom.nominal_thickness - ctx.CA
        return self._spherical_family(
            ctx, R, t_avail,
            check_id="viii1.ug27d",
            title="Spherical shell — required thickness",
            clause=self.clause("UG-27(d)", "Thickness of shells under internal pressure — spherical shells"),
            radius_symbol="R",
            radius_desc="inside radius, corroded",
        )

    def _hemispherical(self, ctx: _Ctx, geom: HemisphericalHead) -> list[CheckResult]:
        L = geom.inside_diameter / 2 + ctx.CA
        t_avail = geom.nominal_thickness - ctx.CA
        return self._spherical_family(
            ctx, L, t_avail,
            check_id="viii1.ug32.hemi",
            title="Hemispherical head — required thickness",
            clause=self.clause("UG-32", "Formed heads, pressure on concave side — hemispherical heads"),
            radius_symbol="L",
            radius_desc="inside spherical radius, corroded",
        )

    def _spherical_family(
        self, ctx: _Ctx, R: Quantity, t_avail: Quantity, *,
        check_id: str, title: str, clause, radius_symbol: str, radius_desc: str,
    ) -> list[CheckResult]:
        ok = ctx.P <= 0.665 * ctx.S * ctx.E
        t_req = (ctx.P * R / (2 * ctx.S * ctx.E - 0.2 * ctx.P)).to(ctx.l_units) if ok else None
        results = [self._thickness_result(
            ctx,
            check_id=check_id,
            title=title,
            clause=clause,
            formula=f"t = P·{radius_symbol} / (2·S·E − 0.2·P)",
            t_req=t_req,
            t_avail=t_avail,
            char_dim=(radius_symbol, radius_desc, R),
            valid=ok and (t_req is None or t_req <= 0.356 * R) and t_avail <= 0.356 * R,
            validity_note=f"applies for t ≤ 0.356·{radius_symbol} and P ≤ 0.665·S·E; outside this domain use Mandatory Appendix 1-3",
            substitution=(
                f"t = ({fmt(ctx.P, ctx.p_units)} × {fmt(R, ctx.l_units)}) / "
                f"(2 × {fmt(ctx.S, ctx.p_units)} × {ctx.E:g} − 0.2 × {fmt(ctx.P, ctx.p_units)})"
                + (f" = {fmt(t_req, ctx.l_units)}" if t_req is not None else "")
            ),
        )]
        mawp = (2 * ctx.S * ctx.E * t_avail / (R + 0.2 * t_avail)).to(ctx.p_units)
        results.append(self._mawp_result(
            ctx, mawp,
            formula=f"MAWP = 2·S·E·t / ({radius_symbol} + 0.2·t)",
            substitution=f"MAWP = {fmt(mawp, ctx.p_units)}",
            extra=[ComputedValue(symbol="t", description="available thickness, corroded", value=f"{t_avail:~}")],
        ))
        results.append(self._ug16b(ctx, t_avail))
        results.append(self._ug99(ctx, mawp))
        return results

    def _ellipsoidal(self, ctx: _Ctx, geom: EllipsoidalHead) -> list[CheckResult]:
        D = geom.inside_diameter + 2 * ctx.CA
        t_avail = geom.nominal_thickness - ctx.CA
        ar = geom.aspect_ratio
        K = (2 + ar**2) / 6
        t_req = (ctx.P * D * K / (2 * ctx.S * ctx.E - 0.2 * ctx.P)).to(ctx.l_units)
        warnings = []
        if not (1.0 <= ar <= 3.0):
            warnings.append(
                f"D/2h = {ar:g} is outside the 1.0–3.0 range covered by Appendix 1-4(c); result not valid"
            )
        thin = (t_req / D).to("dimensionless").magnitude < 0.002
        if thin:
            warnings.append(
                "t/D < 0.002: thin formed heads require the supplemental rules of "
                "Mandatory Appendix 1-4(f); this check alone is insufficient"
            )
        result = self._thickness_result(
            ctx,
            check_id="viii1.app14c",
            title=f"Ellipsoidal head (D/2h = {ar:g}) — required thickness",
            clause=self.clause(
                "Mandatory Appendix 1-4(c)", "Formed heads — ellipsoidal heads (K factor)",
                note="Reduces to the UG-32 equation for 2:1 ellipsoidal heads when D/2h = 2 (K = 1).",
            ),
            formula="t = P·D·K / (2·S·E − 0.2·P),  K = [2 + (D/2h)²] / 6",
            t_req=t_req,
            t_avail=t_avail,
            char_dim=("D", "inside diameter, corroded", D),
            valid=not warnings or (thin and len(warnings) == 1),
            validity_note="K-factor form per Appendix 1-4(c)",
            substitution=(
                f"K = (2 + {ar:g}²)/6 = {K:.6g};  "
                f"t = ({fmt(ctx.P, ctx.p_units)} × {fmt(D, ctx.l_units)} × {K:.6g}) / "
                f"(2 × {fmt(ctx.S, ctx.p_units)} × {ctx.E:g} − 0.2 × {fmt(ctx.P, ctx.p_units)}) "
                f"= {fmt(t_req, ctx.l_units)}"
            ),
            extra_warnings=warnings,
        )
        mawp = (2 * ctx.S * ctx.E * t_avail / (K * D + 0.2 * t_avail)).to(ctx.p_units)
        return [
            result,
            self._mawp_result(
                ctx, mawp,
                formula="MAWP = 2·S·E·t / (K·D + 0.2·t)",
                substitution=f"MAWP = {fmt(mawp, ctx.p_units)}",
                extra=[ComputedValue(symbol="K", description="ellipsoidal head factor", value=f"{K:.10g}")],
            ),
            self._ug16b(ctx, t_avail),
            self._ug99(ctx, mawp),
        ]

    def _torispherical(self, ctx: _Ctx, geom: TorisphericalHead) -> list[CheckResult]:
        D = geom.inside_diameter + 2 * ctx.CA
        L = (geom.crown_radius if geom.crown_radius is not None else geom.inside_diameter) + ctx.CA
        r = geom.knuckle_radius if geom.knuckle_radius is not None else 0.06 * L
        t_avail = geom.nominal_thickness - ctx.CA
        ratio = (L / r).to("dimensionless").magnitude
        M = (3 + math.sqrt(ratio)) / 4
        valid = ratio <= 16.667 + 1e-6 and L <= D + 1e-9 * D
        t_req = (ctx.P * L * M / (2 * ctx.S * ctx.E - 0.2 * ctx.P)).to(ctx.l_units)
        warnings = []
        if r < 0.06 * L:
            warnings.append("knuckle radius r < 0.06·L violates the Code minimum for torispherical heads")
        if (t_req / L).to("dimensionless").magnitude < 0.002:
            warnings.append(
                "t/L < 0.002: thin formed heads require the supplemental rules of "
                "Mandatory Appendix 1-4(f); this check alone is insufficient"
            )
        result = self._thickness_result(
            ctx,
            check_id="viii1.app14d",
            title="Torispherical head — required thickness",
            clause=self.clause(
                "Mandatory Appendix 1-4(d)", "Formed heads — torispherical heads (M factor)",
                note="At L/r = 16⅔ this reduces to the familiar UG-32 form t = 0.885·P·L/(S·E − 0.1·P).",
            ),
            formula="t = P·L·M / (2·S·E − 0.2·P),  M = ¼·[3 + √(L/r)]",
            t_req=t_req,
            t_avail=t_avail,
            char_dim=("L", "inside crown radius, corroded", L),
            valid=valid,
            validity_note="applies for L/r ≤ 16⅔ and L ≤ D",
            substitution=(
                f"L/r = {ratio:.6g};  M = ¼·(3 + √{ratio:.6g}) = {M:.6g};  "
                f"t = ({fmt(ctx.P, ctx.p_units)} × {fmt(L, ctx.l_units)} × {M:.6g}) / "
                f"(2 × {fmt(ctx.S, ctx.p_units)} × {ctx.E:g} − 0.2 × {fmt(ctx.P, ctx.p_units)}) "
                f"= {fmt(t_req, ctx.l_units)}"
            ),
            extra_warnings=warnings,
        )
        mawp = (2 * ctx.S * ctx.E * t_avail / (M * L + 0.2 * t_avail)).to(ctx.p_units)
        return [
            result,
            self._mawp_result(
                ctx, mawp,
                formula="MAWP = 2·S·E·t / (M·L + 0.2·t)",
                substitution=f"MAWP = {fmt(mawp, ctx.p_units)}",
                extra=[ComputedValue(symbol="M", description="torispherical head factor", value=f"{M:.10g}")],
            ),
            self._ug16b(ctx, t_avail),
            self._ug99(ctx, mawp),
        ]

    # --------------------------------------------------------- result helpers

    def _thickness_result(
        self, ctx: _Ctx, *, check_id: str, title: str, clause, formula: str,
        t_req: Quantity | None, t_avail: Quantity, char_dim: tuple[str, str, Quantity],
        valid: bool, validity_note: str, substitution: str,
        extra_warnings: list[str] | None = None,
    ) -> CheckResult:
        assumptions = list(ctx.assumptions)
        warnings = list(extra_warnings or [])
        computed = [
            ComputedValue(symbol=char_dim[0], description=char_dim[1], value=f"{char_dim[2]:~}"),
            ComputedValue(symbol="S", description="maximum allowable stress at design temperature", value=f"{ctx.S:~}"),
            ComputedValue(symbol="E", description="joint efficiency (UW-12)", value=f"{ctx.E:g}"),
            ComputedValue(symbol="t_available", description="nominal thickness minus corrosion allowance", value=f"{t_avail:~}"),
        ]
        if t_req is None or not valid:
            return CheckResult(
                check_id=check_id, title=title, clause=clause,
                disposition=Disposition.NOT_APPLICABLE,
                formula=formula, substitution=substitution if t_req is not None else None,
                computed=computed, criterion=validity_note,
                assumptions=assumptions, warnings=warnings,
                message=f"Outside the validity domain of this equation ({validity_note}); "
                        "evaluate under the referenced alternative rules.",
            )
        computed.insert(0, ComputedValue(symbol="t_required", description="minimum required thickness", value=f"{t_req:~}"))
        margin = capacity_margin(t_avail, t_req)
        passed = margin is None or margin >= 0
        if margin is None:
            message = "No thickness is required for pressure at zero design pressure; other checks still apply."
        elif passed:
            message = None
        else:
            message = (f"Required thickness {fmt(t_req, ctx.l_units)} exceeds available "
                       f"thickness {fmt(t_avail, ctx.l_units)}.")
        return CheckResult(
            check_id=check_id, title=title, clause=clause,
            disposition=Disposition.PASS if passed else Disposition.FAIL,
            formula=formula, substitution=substitution, computed=computed,
            criterion="t_available ≥ t_required",
            margin=margin, assumptions=assumptions, warnings=warnings,
            message=message,
        )

    def _mawp_result(
        self, ctx: _Ctx, mawp: Quantity, *, formula: str, substitution: str,
        extra: list[ComputedValue],
    ) -> CheckResult:
        margin = capacity_margin(mawp, ctx.P)
        passed = margin is None or margin >= 0
        return CheckResult(
            check_id="viii1.mawp",
            title="Maximum allowable working pressure at available thickness",
            clause=self.clause(
                "UG-98 / Appendix 3-2", "Maximum allowable working pressure",
                note="MAWP computed at the corroded available thickness, new-and-cold static head neglected.",
            ),
            disposition=Disposition.PASS if passed else Disposition.FAIL,
            formula=formula, substitution=substitution,
            computed=[ComputedValue(symbol="MAWP", description="maximum allowable working pressure", value=f"{mawp:~}"),
                      ComputedValue(symbol="P", description="internal design gage pressure", value=f"{ctx.P:~}"),
                      *extra],
            criterion="MAWP ≥ P (design pressure)",
            margin=margin,
            assumptions=list(ctx.assumptions),
            message=None if passed else "Design pressure exceeds the MAWP of this component.",
        )

    def _ug16b(self, ctx: _Ctx, t_avail: Quantity) -> CheckResult:
        margin = float((t_avail / MIN_THICKNESS).to("dimensionless").magnitude) - 1.0
        return CheckResult(
            check_id="viii1.ug16b",
            title="Minimum thickness of shells and heads",
            clause=self.clause(
                "UG-16(b)", "Design — general: minimum thickness",
                note="1/16 in. (1.5 mm) minimum exclusive of corrosion allowance; exceptions for "
                     "specific services (e.g. heat-exchanger tubes) are not modeled.",
            ),
            disposition=Disposition.PASS if margin >= 0 else Disposition.FAIL,
            formula="t_available ≥ 1/16 in (1.5 mm)",
            substitution=f"{fmt(t_avail, ctx.l_units)} vs {fmt(MIN_THICKNESS.to(ctx.l_units))}",
            computed=[ComputedValue(symbol="t_available", description="thickness after corrosion allowance", value=f"{t_avail:~}")],
            criterion="t_available ≥ 1/16 in",
            margin=margin,
        )

    def _ug99(self, ctx: _Ctx, mawp: Quantity) -> CheckResult:
        p_test = (HYDRO_FACTOR * mawp).to(ctx.p_units)
        return CheckResult(
            check_id="viii1.ug99b",
            title="Minimum hydrostatic test pressure (informational)",
            clause=self.clause(
                "UG-99(b)", "Standard hydrostatic test",
                note="P_test ≥ 1.3 × MAWP × LSR, where LSR is the lowest ratio of test-temperature "
                     "to design-temperature allowable stress. LSR is taken as 1.0 here; correct it "
                     "when test and design temperatures differ.",
            ),
            disposition=Disposition.INFO,
            formula="P_test ≥ 1.3 · MAWP · LSR",
            substitution=f"P_test ≥ 1.3 × {fmt(mawp, ctx.p_units)} × 1.0 = {fmt(p_test, ctx.p_units)}",
            computed=[ComputedValue(symbol="P_test", description="minimum standard hydrostatic test pressure", value=f"{p_test:~}")],
            assumptions=["Lowest stress ratio (LSR) taken as 1.0 (test and design allowable stresses equal)."],
        )


register(AsmeViiiDiv1())
