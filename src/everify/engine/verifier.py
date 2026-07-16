"""Verification orchestration: resolve the part, run its requested standards."""

from __future__ import annotations

from everify.engine.results import CheckResult, ClauseRef, Disposition, VerificationRun
from everify.materials import load_material_library
from everify.models.material import Material
from everify.models.part import Part
from everify.standards import UnknownStandardError, resolve

MATERIAL_DATA_WARNING = (
    "Material property values for {mid} are unverified example data (source: {src}). "
    "Verify them against the governing code edition / approved data source and set "
    "provenance.verified_by_user: true before relying on these results."
)


def verify_part(part: Part, library: dict[str, Material] | None = None) -> VerificationRun:
    if library is None:
        library = load_material_library()
    rpart = part.resolved(library)

    results: list[CheckResult] = []
    standards_info = []
    for sid in rpart.standards:
        try:
            module = resolve(sid)
        except UnknownStandardError as exc:
            results.append(CheckResult(
                check_id=f"engine.unknown_standard.{sid}",
                title=f"Requested standard '{sid}'",
                clause=ClauseRef(standard="everify engine", edition="-", clause="-",
                                 title="standard module resolution"),
                disposition=Disposition.ERROR,
                message=str(exc),
            ))
            continue
        standards_info.append(module.info())
        if not module.applicable(rpart):
            results.append(CheckResult(
                check_id=f"{module.id}.not_applicable",
                title=f"{module.title}",
                clause=ClauseRef(standard=module.title, edition=module.edition, clause="-",
                                 title="applicability"),
                disposition=Disposition.NOT_APPLICABLE,
                message=f"No checks in module '{module.id}' apply to this part "
                        "(geometry/load definition does not match the module's scope).",
            ))
            continue
        results.extend(module.run(rpart))

    mat = rpart.material
    if isinstance(mat, Material) and mat.provenance.requires_verification \
            and not mat.provenance.verified_by_user:
        warning = MATERIAL_DATA_WARNING.format(mid=mat.id, src=mat.provenance.source)
        for r in results:
            r.warnings.append(warning)

    return VerificationRun(part=rpart, standards=standards_info, results=results)
