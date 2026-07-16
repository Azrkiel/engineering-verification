"""everify command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from everify import __version__
from everify.certificates import (
    build_certificate,
    certificate_id,
    generate_keys,
    render_certificate,
    verify_certificate,
)
from everify.engine.results import Disposition, VerificationRun
from everify.engine.verifier import verify_part
from everify.materials import load_material_library
from everify.models.part import Part
from everify.standards import list_modules

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Standards-based engineering verification with verifiable certificates. "
         "everify performs and documents design-by-rule calculations; it does not "
         "confer ASME stamping, FAA approval, or any regulatory certification.",
)
console = Console()

_STYLE = {
    Disposition.PASS: "bold green",
    Disposition.FAIL: "bold red",
    Disposition.WARN: "bold yellow",
    Disposition.INFO: "bold blue",
    Disposition.NOT_APPLICABLE: "dim",
    Disposition.ERROR: "bold red",
}


def _fail_exit(run: VerificationRun) -> int:
    return 1 if run.overall_disposition in (Disposition.FAIL, Disposition.ERROR) else 0


def _load_part(part_file: Path, standard: list[str] | None) -> Part:
    part = Part.from_yaml(part_file)
    if standard:
        part = part.model_copy(update={"standards": list(standard)})
    return part


def _print_run(run: VerificationRun, verbose: bool) -> None:
    part = run.part
    console.print(f"\n[bold]{part.name}[/bold]  (id {part.id}, rev {part.revision})")
    for s in run.standards:
        console.print(f"  standard: {s.title} — edition {s.edition}", style="dim")
    table = Table(show_lines=verbose)
    table.add_column("Check")
    table.add_column("Clause")
    table.add_column("Result")
    table.add_column("Margin", justify="right")
    table.add_column("Detail", overflow="fold")
    warned: set[str] = set()
    for r in run.results:
        margin = f"{r.margin:+.4f}" if r.margin is not None else "—"
        detail = r.substitution or r.message or ""
        if verbose and r.message and r.substitution:
            detail = f"{r.substitution}\n{r.message}"
        table.add_row(
            r.title,
            r.clause.clause,
            f"[{_STYLE[r.disposition]}]{r.disposition.value}[/]",
            margin,
            detail,
        )
        for w in r.warnings:
            warned.add(w)
    console.print(table)
    for w in sorted(warned):
        console.print(f"[yellow]⚠ {w}[/yellow]")
    style = _STYLE[run.overall_disposition]
    console.print(f"\nOverall: [{style}]{run.overall_disposition.value}[/]\n")


@app.command()
def version() -> None:
    """Print the everify version."""
    console.print(__version__)


@app.command()
def standards() -> None:
    """List available standard modules and their editions."""
    table = Table(title="Standard modules")
    table.add_column("Id")
    table.add_column("Title")
    table.add_column("Edition")
    table.add_column("Aliases")
    table.add_column("Scope note", overflow="fold")
    for m in list_modules():
        table.add_row(m.id, m.title, m.edition, ", ".join(m.aliases), m.note)
    console.print(table)


@app.command()
def materials(
    spec: Optional[str] = typer.Argument(None, help="Material id to show in detail"),
    materials_dir: list[Path] = typer.Option(
        [], "--materials", help="Extra directories of material YAML records (shadow bundled data)"
    ),
) -> None:
    """List the material library, or show one material in detail."""
    library = load_material_library(materials_dir)
    if spec is None:
        table = Table(title="Material library")
        table.add_column("Id")
        table.add_column("Name")
        table.add_column("Category")
        table.add_column("Data status")
        for mat in sorted(library.values(), key=lambda m: m.id):
            status = (
                "[green]verified by user[/green]"
                if mat.provenance.verified_by_user
                else "[yellow]EXAMPLE — requires verification[/yellow]"
            )
            table.add_row(mat.id, mat.name, mat.category, status)
        console.print(table)
        return
    mat = library.get(spec)
    if mat is None:
        console.print(f"[red]material {spec!r} not found[/red]")
        raise typer.Exit(2)
    console.print(Panel.fit(json.dumps(mat.model_dump(mode="json"), indent=2), title=mat.id))


@app.command()
def check(
    part_file: Path = typer.Argument(..., exists=True, readable=True),
    standard: list[str] = typer.Option(
        [], "--standard", "-s", help="Override the standards listed in the part file"
    ),
    materials_dir: list[Path] = typer.Option([], "--materials"),
    json_out: bool = typer.Option(False, "--json", help="Emit the run as JSON instead of a table"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Verify a part definition against its standards. Exit 1 on FAIL/ERROR."""
    part = _load_part(part_file, standard)
    run = verify_part(part, load_material_library(materials_dir))
    if json_out:
        print(json.dumps(run.model_dump(mode="json"), indent=2, ensure_ascii=False))
    else:
        _print_run(run, verbose)
    raise typer.Exit(_fail_exit(run))


@app.command()
def keygen(
    org: str = typer.Option(..., "--org", help="Organization name to bind to the keypair"),
    out: Path = typer.Option(Path("keys"), "--out", "-o", help="Directory for the keypair"),
) -> None:
    """Generate an Ed25519 signing keypair for certificate issuance."""
    meta = generate_keys(out, org)
    console.print(f"Generated Ed25519 keypair for [bold]{org}[/bold] in {out}/")
    console.print(f"  key fingerprint: [cyan]{meta['key_fingerprint']}[/cyan]")
    console.print(
        "[yellow]Protect the private key (everify_org.key) like any signing credential; "
        "distribute only the public key.[/yellow]"
    )


@app.command()
def certify(
    part_file: Path = typer.Argument(..., exists=True, readable=True),
    keys: Path = typer.Option(Path("keys"), "--keys", help="Directory containing the org keypair"),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Certificate JSON path"),
    html: Optional[Path] = typer.Option(None, "--html", help="Also render printable HTML here"),
    standard: list[str] = typer.Option([], "--standard", "-s"),
    materials_dir: list[Path] = typer.Option([], "--materials"),
) -> None:
    """Run verification and issue a signed verification certificate."""
    part = _load_part(part_file, standard)
    run = verify_part(part, load_material_library(materials_dir))
    _print_run(run, verbose=False)
    cert = build_certificate(run, keys)
    out = out or part_file.with_suffix(".cert.json")
    out.write_text(json.dumps(cert, indent=2, ensure_ascii=False) + "\n")
    console.print(f"Certificate [cyan]{certificate_id(cert)}[/cyan] written to {out}")
    if run.overall_disposition is not Disposition.PASS:
        console.print(
            f"[yellow]Note: the certificate records an overall disposition of "
            f"{run.overall_disposition.value} — it documents the outcome, it does not "
            "excuse it.[/yellow]"
        )
    if html is not None:
        html.write_text(render_certificate(cert))
        console.print(f"Printable rendering written to {html}")
    console.print(
        "[dim]This certificate attests to the computational verification only; see its "
        "scope statement. Engineering acceptance requires qualified review.[/dim]"
    )
    raise typer.Exit(_fail_exit(run))


@app.command()
def verify(
    cert_file: Path = typer.Argument(..., exists=True, readable=True),
    pubkey: Optional[Path] = typer.Option(
        None, "--pubkey", help="Trusted issuer public key (PEM) to pin against"
    ),
    no_recompute: bool = typer.Option(
        False, "--no-recompute", help="Skip re-running the checks from embedded inputs"
    ),
) -> None:
    """Verify a certificate offline: signature, input digest, and full recomputation."""
    outcome = verify_certificate(cert_file, pinned_pubkey=pubkey, recompute=not no_recompute)

    def yn(v: bool | None, true_txt: str, false_txt: str, none_txt: str) -> str:
        if v is None:
            return f"[dim]{none_txt}[/dim]"
        return f"[green]{true_txt}[/green]" if v else f"[red]{false_txt}[/red]"

    console.print(f"\nCertificate: {cert_file}")
    console.print(f"  issuer:        {outcome.organization}  "
                  f"[dim](key {outcome.key_fingerprint[:16]}…)[/dim]")
    console.print(f"  recorded overall disposition: {outcome.overall_disposition}")
    console.print(f"  signature:     {yn(outcome.signature_valid, 'VALID', 'INVALID', '-')}")
    console.print(f"  key pinning:   {yn(outcome.issuer_key_pinned, 'matches trusted key', 'DOES NOT MATCH', 'no trusted key supplied')}")
    console.print(f"  input digest:  {yn(outcome.inputs_hash_valid, 'VALID', 'INVALID', '-')}")
    console.print(f"  recompute:     {yn(outcome.reproduced, 'REPRODUCED', 'NOT REPRODUCED', 'skipped')}")
    if not outcome.tool_version_match:
        console.print("  [yellow]tool version differs from the issuing version[/yellow]")
    for d in outcome.diffs:
        console.print(f"  [yellow]Δ {d}[/yellow]")
    for e in outcome.errors:
        console.print(f"  [red]✗ {e}[/red]")
    if outcome.ok or (no_recompute and outcome.signature_valid and outcome.inputs_hash_valid
                      and outcome.issuer_key_pinned is not False):
        console.print("\n[bold green]Certificate verifies.[/bold green]\n")
        raise typer.Exit(0)
    console.print("\n[bold red]Certificate does NOT verify.[/bold red]\n")
    raise typer.Exit(1)


@app.command()
def render(
    cert_file: Path = typer.Argument(..., exists=True, readable=True),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
) -> None:
    """Render a certificate JSON document to printable HTML."""
    cert = json.loads(cert_file.read_text())
    out = out or cert_file.with_suffix(".html")
    out.write_text(render_certificate(cert))
    console.print(f"Wrote {out}")


if __name__ == "__main__":
    app()
