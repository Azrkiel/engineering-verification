"""The conformance suite, and the mutation tests that prove the suite has teeth."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from everify.conformance import (
    Category,
    ConformanceCase,
    load_cases,
    run_case,
    run_suite,
    suite_digest,
)

SRC = Path(__file__).resolve().parent.parent / "src"


class TestSuiteContent:
    def test_suite_loads_and_is_non_trivial(self):
        cases = load_cases()
        assert len(cases) >= 10
        assert len({c.id for c in cases}) == len(cases)

    def test_every_standard_module_is_covered(self):
        standards = {c.standard for c in load_cases()}
        assert {"asme-viii-div1", "asme-b31-3", "far-25"} <= standards

    def test_every_category_is_represented(self):
        categories = {c.category for c in load_cases()}
        assert categories == set(Category)

    def test_every_case_states_its_rationale(self):
        for case in load_cases():
            assert len(case.rationale.strip()) > 80, f"{case.id} lacks a substantive rationale"

    def test_cases_are_portable_and_do_not_rely_on_bundled_materials(self):
        # Bundled material records carry unverified example values; a conformance
        # case must define its own so it means the same thing everywhere.
        for case in load_cases():
            material = case.part.get("material")
            if isinstance(material, str):
                assert material in case.materials, (
                    f"{case.id} references library material {material!r} instead of "
                    "defining a case-local one"
                )

    def test_suite_digest_is_stable_and_content_dependent(self):
        cases = load_cases()
        assert suite_digest(cases) == suite_digest(list(reversed(cases)))
        mutated = [c.model_copy() for c in cases]
        mutated[0] = mutated[0].model_copy(update={"title": "changed"})
        assert suite_digest(mutated) != suite_digest(cases)


class TestSuitePasses:
    def test_whole_suite_passes(self):
        report = run_suite()
        failures = [
            f"{r.case.id}: {r.error or '; '.join(r.failures)}"
            for r in report.results if not r.passed
        ]
        assert not failures, "\n".join(failures)
        assert report.passed == len(report.results)

    @pytest.mark.parametrize("standard", ["asme-viii-div1", "asme-b31-3", "far-25"])
    def test_per_standard_selection(self, standard):
        report = run_suite(standard=standard)
        assert report.results and report.ok

    def test_category_selection(self):
        report = run_suite(category=Category.DOMAIN_GUARD)
        assert report.results and report.ok


class TestSuiteDetectsBadEngines:
    """A suite that cannot fail is worthless. These prove it fails when it should."""

    def _case(self, case_id: str) -> ConformanceCase:
        return next(c for c in load_cases() if c.id == case_id)

    def test_wrong_expected_margin_is_reported(self):
        case = self._case("viii1.ug27.golden.cylinder")
        broken = case.model_copy(update={
            "expect": [e.model_copy(update={"margin": 0.9}) if e.check_id == "viii1.ug27c1"
                       else e for e in case.expect],
        })
        result = run_case(broken)
        assert not result.passed
        assert any("viii1.ug27c1" in f and "margin" in f for f in result.failures)

    def test_wrong_expected_disposition_is_reported(self):
        case = self._case("viii1.golden.undersized-fails")
        broken = case.model_copy(update={
            "expect": [e.model_copy(update={"disposition": "PASS"}) for e in case.expect],
        })
        assert not run_case(broken).passed

    def test_broken_identity_pair_is_reported(self):
        # Change the comparison part's geometry: the identity must stop holding.
        case = self._case("viii1.identity.hemisphere-equals-sphere")
        transform = case.agrees_with[0]
        part = json.loads(json.dumps(transform.part))
        part["geometry"]["inside_diameter"] = "72 inch"
        broken = case.model_copy(update={
            "agrees_with": [transform.model_copy(update={"part": part})],
        })
        result = run_case(broken)
        assert not result.passed

    def test_unverifiable_case_becomes_an_error_not_a_crash(self):
        case = self._case("viii1.ug27.golden.cylinder")
        part = json.loads(json.dumps(case.part))
        part["geometry"]["inside_diameter"] = "not a length"
        result = run_case(case.model_copy(update={"part": part}))
        assert not result.passed
        assert result.error and result.status == "ERROR"

    def test_missing_check_is_reported(self):
        case = self._case("viii1.ug27.golden.cylinder")
        broken = case.model_copy(update={
            "expect": [*case.expect,
                       case.expect[0].model_copy(update={"check_id": "viii1.nonexistent"})],
        })
        result = run_case(broken)
        assert not result.passed
        assert any("not produced" in f for f in result.failures)


@pytest.mark.parametrize(
    ("target", "old", "new", "description"),
    [
        ("asme_viii_div1.py", "ctx.S * ctx.E - 0.6 * ctx.P", "ctx.S * ctx.E - 0.65 * ctx.P",
         "UG-27(c)(1) denominator coefficient"),
        ("asme_viii_div1.py", "2 * ctx.S * ctx.E - 0.2 * ctx.P", "2 * ctx.S * ctx.E - 0.25 * ctx.P",
         "formed-head denominator coefficient"),
        ("asme_b31_3.py", "2 * (ctx.S * ctx.E * ctx.W + ctx.P * ctx.Y)",
         "2 * (ctx.S * ctx.E * ctx.W + ctx.P * ctx.Y * 1.05)", "B31.3 Y-term"),
        ("far_part25.py", "dv.Ftu / (ff * fs * f)", "dv.Ftu / (ff * 1.4 * f)",
         "14 CFR 25.303 factor of safety"),
    ],
)
def test_mutating_an_engine_coefficient_fails_the_suite(tmp_path, target, old, new, description):
    """Corrupt a real coefficient in a copy of the engine; the suite must catch it.

    This is the test that makes the whole corpus meaningful: it demonstrates the
    suite detects wrong physics, not merely that the code runs.
    """
    workspace = tmp_path / "mutant"
    shutil.copytree(SRC, workspace)
    module = workspace / "everify" / "standards" / target
    source = module.read_text()
    assert source.count(old) >= 1, f"mutation target not found in {target}: {old!r}"
    module.write_text(source.replace(old, new, 1))

    env = dict(os.environ, PYTHONPATH=str(workspace))
    proc = subprocess.run(
        [sys.executable, "-c",
         "from everify.conformance import run_suite; "
         "r = run_suite(); "
         "print(r.failed)"],
        capture_output=True, text=True, env=env, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    failed = int(proc.stdout.strip().splitlines()[-1])
    assert failed > 0, f"suite failed to detect a corrupted {description}"


class TestConformanceCli:
    def test_run_list_and_digest(self):
        from typer.testing import CliRunner

        from everify.cli import app

        os.environ["COLUMNS"] = "250"
        runner = CliRunner()

        run = runner.invoke(app, ["conform", "run"])
        assert run.exit_code == 0, run.output
        assert "conformance cases pass" in run.output

        listing = runner.invoke(app, ["conform", "list"])
        assert listing.exit_code == 0
        assert "viii1.ug27.golden.cylinder" in listing.output

        js = runner.invoke(app, ["conform", "run", "--json"])
        doc = json.loads(js.output)
        assert doc["failed"] == 0
        assert doc["total"] == doc["passed"]
        assert len(doc["suite_digest"]) == 64

        digest = runner.invoke(app, ["conform", "digest"])
        assert digest.exit_code == 0
        assert doc["suite_digest"][:16] in digest.output
