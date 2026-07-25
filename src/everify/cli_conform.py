"""CLI for the conformance suite: `everify conform ...`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from everify.conformance import Category, load_cases, run_suite, suite_digest

conform_app = typer.Typer(
    no_args_is_help=True,
    help="Conformance suite: the tests any implementation of these standards must pass.",
)
console = Console()

_STATUS_STYLE = {"PASS": "bold green", "FAIL": "bold red", "ERROR": "bold red"}


@conform_app.command("list")
def conform_list(
    standard: Optional[str] = typer.Option(None, "--standard", "-s"),
    suite_dir: list[Path] = typer.Option([], "--suite", help="Additional suite directories"),
) -> None:
    """List conformance cases and what each one asserts."""
    cases = load_cases(suite_dir)
    table = Table(title=f"Conformance suite — digest {suite_digest(cases)[:16]}…")
    table.add_column("Case")
    table.add_column("Standard")
    table.add_column("Category")
    table.add_column("Title", overflow="fold")
    for case in cases:
        if standard and case.standard != standard:
            continue
        table.add_row(case.id, case.standard, case.category.value, case.title)
    console.print(table)


@conform_app.command("run")
def conform_run(
    standard: Optional[str] = typer.Option(None, "--standard", "-s"),
    category: Optional[Category] = typer.Option(None, "--category", "-c"),
    suite_dir: list[Path] = typer.Option([], "--suite"),
    json_out: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show each case's rationale"),
) -> None:
    """Run the conformance suite against this engine. Exit 1 on any failure."""
    report = run_suite(standard=standard, category=category, extra_dirs=suite_dir)

    if json_out:
        print(json.dumps(report.to_dict(), indent=2))
        raise typer.Exit(0 if report.ok else 1)

    table = Table(title=f"Conformance run — suite digest {report.suite_digest[:16]}…")
    table.add_column("Case")
    table.add_column("Category")
    table.add_column("Result")
    table.add_column("Detail", overflow="fold")
    for result in report.results:
        detail = result.error or "\n".join(result.failures)
        table.add_row(
            result.case.id,
            result.case.category.value,
            f"[{_STATUS_STYLE[result.status]}]{result.status}[/]",
            detail,
        )
    console.print(table)

    if verbose:
        for result in report.results:
            console.print(f"\n[bold]{result.case.id}[/bold] — {result.case.title}")
            console.print(f"[dim]{result.case.rationale.strip()}[/dim]")

    if report.ok:
        console.print(
            f"\n[bold green]{report.passed}/{len(report.results)} conformance cases pass.[/bold green]\n"
        )
        raise typer.Exit(0)
    console.print(
        f"\n[bold red]{report.failed} of {len(report.results)} conformance cases FAILED.[/bold red]\n"
    )
    raise typer.Exit(1)


@conform_app.command("digest")
def conform_digest(
    suite_dir: list[Path] = typer.Option([], "--suite"),
) -> None:
    """Print the suite digest — cite this to state which suite an engine satisfied."""
    cases = load_cases(suite_dir)
    console.print(suite_digest(cases))
