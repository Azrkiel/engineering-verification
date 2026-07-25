"""FAA 14 CFR Part 25 — structural substantiation margin checks.

14 CFR (the Federal Aviation Regulations) is a U.S. Government work in the
public domain, so the operative text is quoted verbatim in each citation.

everify verifies FACTOR APPLICATION and MARGINS on user-supplied limit
stresses: the stress analysis itself (FEA, hand analysis) and its pedigree
remain the engineer's responsibility, as does everything these checks do not
cover (stability, fatigue and damage tolerance per 25.571, flutter, etc.).
Showings of compliance are made to the FAA or its designees — this tool
cannot make them.
"""

from __future__ import annotations

import re

from everify.engine.results import CheckResult, ComputedValue, Disposition
from everify.models.loads import LoadCase
from everify.models.material import Material
from everify.models.part import Part
from everify.standards.base import StandardModule, register
from everify.units import fmt

Q25_303 = (
    "Unless otherwise specified, a factor of safety of 1.5 must be applied to the "
    "prescribed limit load which are considered external loads on the structure."
)
Q25_305A = (
    "The structure must be able to support limit loads without detrimental permanent "
    "deformation. At any load up to limit loads, the deformation may not interfere with "
    "safe operation."
)
Q25_305B = (
    "The structure must be able to support ultimate loads without failure for at least 3 seconds."
)
Q25_613B = (
    "Design values must be chosen to minimize the probability of structural failures due to "
    "material variability. ... (1) Where applied loads are eventually distributed through a "
    "single member within an assembly, the failure of which would result in loss of structural "
    "integrity of the component, 99 percent probability with 95 percent confidence. (2) For "
    "redundant structure, in which the failure of individual elements would result in applied "
    "loads being safely distributed to other load carrying members, 90 percent probability "
    "with 95 percent confidence."
)
Q25_625 = (
    "For each fitting (a part or terminal used to join one structural member to another) ... "
    "a fitting factor of at least 1.15 must be applied to each part of the fitting, the means "
    "of attachment, and the bearing on the joined members."
)

ANALYSIS_ASSUMPTION = (
    "Limit stress is user-supplied from the governing stress analysis; everify verifies "
    "factor application and margins, not the stress analysis itself."
)
YIELD_ASSUMPTION = (
    "Tensile yield strength Fty is used as the allowable for the no-detrimental-permanent-"
    "deformation criterion of § 25.305(a), per standard industry practice."
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class FarPart25(StandardModule):
    id = "far-25"
    aliases = ("14-cfr-25", "faa-part-25", "part-25")
    title = "Title 14 CFR Part 25 — Airworthiness Standards: Transport Category Airplanes"
    edition = "e-CFR, revised as of 2025"
    note = (
        "Static strength margin and design-value basis checks on user-supplied limit stresses "
        "only. Stability, fatigue and damage tolerance (25.571), flutter, and all other "
        "airworthiness requirements are not evaluated. Findings of compliance are made by the "
        "FAA or its designees."
    )

    def applicable(self, part: Part) -> bool:
        return bool(part.load_cases)

    def run(self, part: Part) -> list[CheckResult]:
        if not self.applicable(part):
            return [CheckResult(
                check_id=f"{self.id}.not_applicable",
                title=self.title,
                clause=self.clause("§ 25.1", "Applicability"),
                disposition=Disposition.NOT_APPLICABLE,
                message="Part defines no load_cases; no Part 25 margin checks apply.",
            )]
        mat = part.material
        if not isinstance(mat, Material):
            return [self._error("material reference was not resolved to a material record")]
        dv = mat.design_values
        if dv is None or dv.Ftu is None or dv.Fty is None:
            return [self._error(
                f"material {mat.id!r} lacks design values (Ftu, Fty) required for Part 25 "
                "margin checks; supply design_values with a declared statistical basis (25.613)"
            )]
        results: list[CheckResult] = []
        used: dict[str, int] = {}
        for case in part.load_cases:
            base = _slug(case.name)
            n = used.get(base, 0)
            used[base] = n + 1
            slug = base if n == 0 else f"{base}-{n + 1}"  # distinct names can share a slug
            results.extend(self._case_checks(case, mat, slug))
        return results

    def _error(self, message: str) -> CheckResult:
        return CheckResult(
            check_id="far25.setup",
            title="Part 25 input validation",
            clause=self.clause("§ 25.613", "Material strength properties and material design values"),
            disposition=Disposition.ERROR,
            message=message,
        )

    def _case_checks(self, case: LoadCase, mat: Material, slug: str) -> list[CheckResult]:
        dv = mat.design_values
        ff = case.fitting_factor if case.is_fitting else 1.0
        fs = case.factor_of_safety
        f = case.limit_stress
        s_units = f"{f.units:~}"

        assumptions = [ANALYSIS_ASSUMPTION]
        if case.is_fitting:
            assumptions.append(
                f"Fitting factor {ff:g} applied per § 25.625 (strength not proven by limit and "
                "ultimate load tests)."
            )

        ms_ult = float((dv.Ftu / (ff * fs * f)).to("dimensionless").magnitude) - 1.0
        ult = CheckResult(
            check_id=f"far25.ultimate.{slug}",
            title=f"Ultimate strength margin — load case '{case.name}'",
            clause=self.clause(
                "§§ 25.303, 25.305(b)", "Factor of safety; strength and deformation (ultimate)",
                quote=f"25.303: {Q25_303} 25.305(b): {Q25_305B}",
            ),
            disposition=Disposition.PASS if ms_ult >= 0 else Disposition.FAIL,
            formula="MS_ult = Ftu / (FF · FS · f_limit) − 1 ≥ 0",
            substitution=(
                f"MS_ult = {fmt(dv.Ftu, s_units)} / ({ff:g} × {fs:g} × {fmt(f, s_units)}) − 1 "
                f"= {ms_ult:+.4f}"
            ),
            computed=[
                ComputedValue(symbol="Ftu", description=f"design ultimate tensile strength ({dv.basis or 'unstated'}-basis)", value=f"{dv.Ftu:~}"),
                ComputedValue(symbol="f_limit", description="limit stress from analysis", value=f"{f:~}"),
                ComputedValue(symbol="FS", description="factor of safety (§ 25.303)", value=f"{fs:g}"),
                ComputedValue(symbol="FF", description="fitting factor (§ 25.625)", value=f"{ff:g}"),
            ],
            criterion="margin of safety at ultimate load ≥ 0",
            margin=ms_ult,
            assumptions=assumptions,
        )

        ms_lim = float((dv.Fty / (ff * f)).to("dimensionless").magnitude) - 1.0
        lim = CheckResult(
            check_id=f"far25.limit.{slug}",
            title=f"Limit load / permanent deformation margin — load case '{case.name}'",
            clause=self.clause(
                "§ 25.305(a)", "Strength and deformation (limit)",
                quote=Q25_305A,
            ),
            disposition=Disposition.PASS if ms_lim >= 0 else Disposition.FAIL,
            formula="MS_limit = Fty / (FF · f_limit) − 1 ≥ 0",
            substitution=(
                f"MS_limit = {fmt(dv.Fty, s_units)} / ({ff:g} × {fmt(f, s_units)}) − 1 = {ms_lim:+.4f}"
            ),
            computed=[
                ComputedValue(symbol="Fty", description=f"design tensile yield strength ({dv.basis or 'unstated'}-basis)", value=f"{dv.Fty:~}"),
                ComputedValue(symbol="f_limit", description="limit stress from analysis", value=f"{f:~}"),
                ComputedValue(symbol="FF", description="fitting factor (§ 25.625)", value=f"{ff:g}"),
            ],
            criterion="margin of safety at limit load ≥ 0",
            margin=ms_lim,
            assumptions=[*assumptions, YIELD_ASSUMPTION],
        )

        basis = self._basis_check(case, mat, slug)
        return [ult, lim, basis]

    def _basis_check(self, case: LoadCase, mat: Material, slug: str) -> CheckResult:
        dv = mat.design_values
        clause = self.clause(
            "§ 25.613(b)", "Material strength properties and material design values",
            quote=Q25_613B,
            note="Fitting factor text for reference — § 25.625: " + Q25_625,
        )
        common = {
            "check_id": f"far25.basis.{slug}",
            "title": f"Material design-value basis — load case '{case.name}'",
            "clause": clause,
            "criterion": "single load path ⇒ A-basis (99%/95%) or S-basis; redundant ⇒ B-basis (90%/95%) acceptable",
            "computed": [
                ComputedValue(symbol="basis", description="declared statistical basis of design values", value=dv.basis or "unstated"),
                ComputedValue(symbol="load_path", description="declared load path for this case", value=case.load_path),
            ],
        }
        if dv.basis is None:
            return CheckResult(
                **common,
                disposition=Disposition.WARN,
                message="Design-value basis is undeclared; declare A/B/S basis and its source "
                        "(e.g. MMPDS) to substantiate § 25.613 compliance.",
            )
        if case.load_path == "single" and dv.basis == "B":
            return CheckResult(
                **common,
                disposition=Disposition.FAIL,
                message="Single-load-path structure requires A-basis (99% probability, 95% "
                        "confidence) or S-basis design values; B-basis is insufficient per § 25.613(b)(1).",
            )
        return CheckResult(**common, disposition=Disposition.PASS)


register(FarPart25())
