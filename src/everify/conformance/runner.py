"""Execute the conformance suite against the local engine.

The suite is a citable artifact: `suite_digest()` hashes the canonical form of
every case, so a certificate can assert which conformance suite the issuing
engine satisfied. An engine that cannot state that is making an unbacked
claim of correctness.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Iterable

import yaml

from everify.certificates.canonical import canonical_bytes, sha256_hex
from everify.conformance.case import Category, ConformanceCase, ExpectedCheck
from everify.engine.results import CheckResult
from everify.engine.verifier import verify_part
from everify.materials import load_material_library
from everify.models.material import Material
from everify.models.part import Part

SUITE_VERSION = "everify-conformance/v1"


@dataclass
class CaseResult:
    case: ConformanceCase
    passed: bool
    failures: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        return "PASS" if self.passed else "FAIL"


@dataclass
class SuiteReport:
    results: list[CaseResult]
    suite_digest: str

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed and not r.error)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed or r.error)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict:
        return {
            "suite": SUITE_VERSION,
            "suite_digest": self.suite_digest,
            "total": len(self.results),
            "passed": self.passed,
            "failed": self.failed,
            "cases": [
                {
                    "id": r.case.id,
                    "standard": r.case.standard,
                    "category": r.case.category.value,
                    "status": r.status,
                    "failures": r.failures,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


def _suite_root() -> Path:
    return Path(str(resources.files("everify.conformance") / "suite"))


def load_cases(extra_dirs: Iterable[str | Path] = ()) -> list[ConformanceCase]:
    cases: list[ConformanceCase] = []
    seen: set[str] = set()
    roots = [_suite_root(), *(Path(d) for d in extra_dirs)]
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            if not isinstance(data, dict):
                raise ValueError(f"{path}: expected a YAML mapping describing a case")
            case = ConformanceCase.model_validate(data)
            if case.id in seen:
                raise ValueError(f"duplicate conformance case id {case.id!r} in {path}")
            seen.add(case.id)
            cases.append(case)
    return cases


def suite_digest(cases: list[ConformanceCase]) -> str:
    return sha256_hex(canonical_bytes(
        [c.model_dump(mode="json") for c in sorted(cases, key=lambda c: c.id)]
    ))


def _library_for(case: ConformanceCase) -> dict[str, Material]:
    library = dict(load_material_library())
    for mat_id, doc in case.materials.items():
        library[mat_id] = Material.model_validate({"id": mat_id, **doc})
    return library


def _close(a: float, b: float, rel: float) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)


def _check_expectation(exp: ExpectedCheck, results: dict[str, CheckResult]) -> list[str]:
    result = results.get(exp.check_id)
    if result is None:
        return [f"{exp.check_id}: check not produced (produced: {', '.join(sorted(results))})"]
    out: list[str] = []
    if exp.disposition is not None and result.disposition.value != exp.disposition:
        out.append(
            f"{exp.check_id}: disposition expected {exp.disposition}, got {result.disposition.value}"
        )
    if exp.margin_is_none and result.margin is not None:
        out.append(f"{exp.check_id}: margin expected absent, got {result.margin}")
    if exp.margin is not None:
        if result.margin is None:
            out.append(f"{exp.check_id}: margin expected {exp.margin}, got none")
        elif not _close(result.margin, exp.margin, exp.margin_tolerance):
            out.append(
                f"{exp.check_id}: margin expected {exp.margin:.10g} "
                f"(rel tol {exp.margin_tolerance:g}), got {result.margin:.10g}"
            )
    if exp.message_contains and exp.message_contains not in (result.message or ""):
        out.append(
            f"{exp.check_id}: message expected to contain {exp.message_contains!r}, "
            f"got {result.message!r}"
        )
    return out


def run_case(case: ConformanceCase) -> CaseResult:
    try:
        library = _library_for(case)
        part = Part.model_validate(case.part)
        run = verify_part(part, library)
    except Exception as exc:  # a case that cannot even execute is a failure, not a crash
        return CaseResult(case, passed=False, error=f"{type(exc).__name__}: {exc}")

    results = {r.check_id: r for r in run.results}
    failures: list[str] = []

    for exp in case.expect:
        failures.extend(_check_expectation(exp, results))

    if case.expect_overall and run.overall_disposition.value != case.expect_overall:
        failures.append(
            f"overall: expected {case.expect_overall}, got {run.overall_disposition.value}"
        )

    for transform in case.agrees_with:
        try:
            other_part = Part.model_validate(transform.part)
            other = {r.check_id: r for r in verify_part(other_part, library).results}
        except Exception as exc:
            failures.append(f"{transform.description}: failed to verify ({exc})")
            continue
        keys = transform.only_checks or sorted(set(results) & set(other))
        if not transform.only_checks and set(results) != set(other):
            failures.append(
                f"{transform.description}: produced a different set of checks "
                f"({sorted(set(results) ^ set(other))})"
            )
        for key in keys:
            base, comp = results.get(key), other.get(key)
            if base is None or comp is None:
                failures.append(f"{transform.description}: {key} missing from one side")
                continue
            if base.disposition != comp.disposition:
                failures.append(
                    f"{transform.description}: {key} disposition "
                    f"{base.disposition.value} vs {comp.disposition.value}"
                )
            if base.margin is None or comp.margin is None:
                if base.margin is not comp.margin:
                    failures.append(f"{transform.description}: {key} margin presence differs")
            elif not _close(base.margin, comp.margin, transform.margin_tolerance):
                failures.append(
                    f"{transform.description}: {key} margin {base.margin:.12g} vs "
                    f"{comp.margin:.12g} (rel tol {transform.margin_tolerance:g})"
                )

    return CaseResult(case, passed=not failures, failures=failures)


def run_suite(
    cases: list[ConformanceCase] | None = None,
    standard: str | None = None,
    category: Category | None = None,
    extra_dirs: Iterable[str | Path] = (),
) -> SuiteReport:
    all_cases = cases if cases is not None else load_cases(extra_dirs)
    digest = suite_digest(all_cases)
    selected = [
        c for c in all_cases
        if (standard is None or c.standard == standard)
        and (category is None or c.category is category)
    ]
    return SuiteReport([run_case(c) for c in selected], suite_digest=digest)
