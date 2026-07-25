"""CLI for the evidence graph: `everify graph ...` and `everify attest`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from everify.graph import (
    Author,
    AuthorKind,
    Freshness,
    GraphStore,
    NodeType,
    add_part,
    ai_exposure,
    attest_claims,
    attestations,
    attested_claim_keys,
    impact,
    status,
)
from everify.materials import load_material_library
from everify.models.part import Part

graph_app = typer.Typer(no_args_is_help=True, help="Evidence graph: track whether claims are still true.")
console = Console()

_FRESH_STYLE = {
    Freshness.FRESH: "bold green",
    Freshness.STALE: "bold yellow",
    Freshness.ORPHANED: "bold red",
}


def _store(root: Path) -> GraphStore:
    store = GraphStore(root)
    if not store.initialized:
        console.print(f"[red]error:[/red] no evidence graph at {root} — run 'everify graph init'")
        raise typer.Exit(2)
    return store


@graph_app.command("init")
def graph_init(
    root: Path = typer.Option(Path("."), "--root", help="Directory to hold the .everify store"),
) -> None:
    """Create an evidence graph store."""
    path = GraphStore(root).init()
    console.print(f"Initialized evidence graph at {path}")


@graph_app.command("add")
def graph_add(
    part_file: Path = typer.Argument(..., exists=True, readable=True),
    root: Path = typer.Option(Path("."), "--root"),
    author: str = typer.Option("everify", "--author", help="Who authored these inputs"),
    author_kind: AuthorKind = typer.Option(AuthorKind.TOOL, "--author-kind"),
    geometry_author: Optional[str] = typer.Option(
        None, "--geometry-author",
        help="Mark geometry as authored by someone/something else (e.g. an AI model id)",
    ),
    geometry_author_kind: AuthorKind = typer.Option(AuthorKind.AI, "--geometry-author-kind"),
    materials_dir: list[Path] = typer.Option([], "--materials"),
) -> None:
    """Add a part to the graph: decompose inputs, verify, and record claims."""
    store = _store(root)
    part = Part.from_yaml(part_file)
    geom_author = (
        Author(kind=geometry_author_kind, id=geometry_author) if geometry_author else None
    )
    nodes = add_part(
        store,
        part,
        author=Author(kind=author_kind, id=author),
        library=load_material_library(materials_dir),
        geometry_author=geom_author,
    )
    claims = [n for n in nodes if n.type is NodeType.CLAIM]
    console.print(
        f"Added [bold]{part.name}[/bold]: {len(nodes)} nodes ({len(claims)} claims)"
    )
    console.print(f"  graph state root: [cyan]{store.state_root()[:16]}…[/cyan]")


@graph_app.command("status")
def graph_status(
    root: Path = typer.Option(Path("."), "--root"),
    all_nodes: bool = typer.Option(False, "--all", help="Show every node, not just claims"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show which claims are still true and which have gone stale."""
    store = _store(root)
    statuses = status(store, None if all_nodes else NodeType.CLAIM)
    covered = attested_claim_keys(store)

    if json_out:
        att_states = attestations(store)
        print(json.dumps({
            "state_root": store.state_root(),
            "nodes": [
                {
                    "key": s.node.key,
                    "type": s.node.type.value,
                    "freshness": s.freshness.value,
                    "digest": s.node.digest,
                    "attested": s.node.key in covered,
                    "drift": [d.describe() for d in s.drift],
                }
                for s in statuses
            ],
            "attestations": [
                {
                    "key": a.node.key,
                    "reviewer": a.node.content.get("reviewer"),
                    "scope": a.node.content.get("scope"),
                    "verdict": a.verdict,
                    "drift": [d.describe() for d in a.drift],
                }
                for a in att_states
            ],
            "ai_exposure": [
                {
                    "key": e.node.key,
                    "author": e.node.author.id,
                    "dependent_claims": len(e.dependent_claims),
                    "unattested_claims": [c.key for c in e.unattested],
                }
                for e in ai_exposure(store)
            ],
        }, indent=2))
        stale_or_void = any(s.stale for s in statuses) or any(not a.valid for a in att_states)
        raise typer.Exit(1 if stale_or_void else 0)

    table = Table(title=f"Evidence graph — state root {store.state_root()[:16]}…")
    table.add_column("Node")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Attested")
    table.add_column("Changed inputs", overflow="fold")
    for s in statuses:
        attested = "[green]yes[/green]" if s.node.key in covered else "[dim]no[/dim]"
        table.add_row(
            s.node.key,
            s.node.type.value,
            f"[{_FRESH_STYLE[s.freshness]}]{s.freshness.value}[/]",
            attested if s.node.type is NodeType.CLAIM else "—",
            "\n".join(d.describe() for d in s.drift),
        )
    console.print(table)

    att = attestations(store)
    if att:
        console.print("\n[bold]Attestations[/bold]")
        for a in att:
            style = "bold green" if a.valid else "bold red"
            console.print(
                f"  [{style}]{a.verdict}[/] {a.node.content.get('reviewer')} — "
                f"{a.node.content.get('scope')} ({len(a.node.dependencies)} claims)"
            )
            for d in a.drift:
                console.print(f"      [yellow]Δ {d.describe()}[/yellow]")

    exposure = ai_exposure(store)
    if exposure:
        console.print("\n[bold]AI-authored inputs[/bold]")
        for e in exposure:
            unattested = len(e.unattested)
            style = "yellow" if unattested else "green"
            console.print(
                f"  [{style}]{e.node.key}[/{style}] (by {e.node.author.id}): "
                f"{len(e.dependent_claims)} dependent claims, "
                f"{unattested} without valid human attestation"
            )

    stale = [s for s in statuses if s.stale]
    void = [a for a in att if not a.valid]
    if stale or void:
        if stale:
            console.print(
                f"\n[bold yellow]{len(stale)} node(s) need re-verification.[/bold yellow]"
            )
        if void:
            console.print(
                f"[bold red]{len(void)} attestation(s) VOID — the signed-off design changed "
                "and requires re-review.[/bold red]"
            )
        console.print()
        raise typer.Exit(1)
    console.print("\n[bold green]All claims current and attestations valid.[/bold green]\n")


@graph_app.command("impact")
def graph_impact(
    key: str = typer.Argument(..., help="Node key, e.g. material:SA-516-70"),
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    """Show the blast radius: everything that depends on this node."""
    store = _store(root)
    try:
        affected = impact(store, key)
    except KeyError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(2) from None
    console.print(f"\nChanging [bold]{key}[/bold] would invalidate {len(affected)} node(s):\n")
    table = Table()
    table.add_column("Node")
    table.add_column("Type")
    table.add_column("Label", overflow="fold")
    for node in affected:
        table.add_row(node.key, node.type.value, node.label or "")
    console.print(table)


@graph_app.command("verify")
def graph_verify(
    part_file: list[Path] = typer.Argument(..., help="Part files to re-verify into the graph"),
    root: Path = typer.Option(Path("."), "--root"),
    materials_dir: list[Path] = typer.Option([], "--materials"),
) -> None:
    """Recompute claims for the given parts, refreshing the graph."""
    store = _store(root)
    library = load_material_library(materials_dir)
    for path in part_file:
        part = Part.from_yaml(path)
        nodes = add_part(store, part, library=library)
        claims = [n for n in nodes if n.type is NodeType.CLAIM]
        console.print(f"Re-verified {part.name}: {len(claims)} claims")
    remaining = [s for s in status(store) if s.stale]
    if remaining:
        console.print(f"[yellow]{len(remaining)} claim(s) still stale.[/yellow]")
        raise typer.Exit(1)
    console.print("[green]All claims current.[/green]")


@graph_app.command("log")
def graph_log(
    key: str = typer.Argument(..., help="Node key to show history for"),
    root: Path = typer.Option(Path("."), "--root"),
) -> None:
    """Show every recorded version of a node — the audit trail."""
    store = _store(root)
    history = store.history(key)
    if not history:
        console.print(f"[red]error:[/red] no history for {key!r}")
        raise typer.Exit(2)
    current = store.current_digest(key)
    for node in history:
        marker = "[green]* current[/green]" if node.digest == current else "  "
        console.print(
            f"{marker} [cyan]{node.short}[/cyan]  {node.created_at}  "
            f"by {node.author.id} ({node.author.kind.value})"
        )


def attest_command(
    claim: list[str] = typer.Option(
        [], "--claim", help="Claim key to attest (repeatable); default is all current claims"
    ),
    reviewer: str = typer.Option(..., "--reviewer", help="Name of the reviewing engineer"),
    scope: str = typer.Option("review", "--scope", help="Short label for this sign-off"),
    root: Path = typer.Option(Path("."), "--root"),
    keys: Optional[Path] = typer.Option(None, "--keys", help="Sign the attestation with this keypair"),
    license_number: Optional[str] = typer.Option(None, "--license"),
    jurisdiction: Optional[str] = typer.Option(None, "--jurisdiction"),
) -> None:
    """Record a reviewing engineer's sign-off over current claims.

    The sign-off is bound to the exact claim versions reviewed and becomes
    void automatically if any input they depend on changes.
    """
    store = _store(root)
    keys_to_attest = claim or [
        s.node.key for s in status(store, NodeType.CLAIM) if not s.stale
    ]
    if not keys_to_attest:
        console.print("[red]error:[/red] no current claims to attest")
        raise typer.Exit(2)
    try:
        node = attest_claims(
            store, keys_to_attest, reviewer=reviewer, scope=scope, keys_dir=keys,
            license_number=license_number, jurisdiction=jurisdiction,
        )
    except (KeyError, FileNotFoundError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(2) from None
    signed = "signed " if keys else ""
    console.print(
        f"Recorded {signed}attestation [cyan]{node.short}[/cyan] by {reviewer} "
        f"over {len(node.dependencies)} claim(s)."
    )
    console.print(
        "[dim]This sign-off is void automatically if any input it depends on changes.[/dim]"
    )
