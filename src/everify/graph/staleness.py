"""Staleness, blast radius, and attestation validity.

The question this module exists to answer is the one that actually costs
hardware companies money: *the design changed — which of my claims are no
longer true, and which sign-offs just became void?*
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from everify.graph.nodes import AuthorKind, Node, NodeType
from everify.graph.store import GraphStore, NodeNotFoundError


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    ORPHANED = "ORPHANED"  # a dependency no longer exists in the graph


@dataclass
class DependencyDrift:
    key: str
    recorded: str
    current: str | None  # None when the dependency was removed

    def describe(self) -> str:
        if self.current is None:
            return f"{self.key}: input removed from the graph (was {self.recorded[:12]})"
        return f"{self.key}: {self.recorded[:12]} → {self.current[:12]}"


@dataclass
class NodeStatus:
    node: Node
    freshness: Freshness
    drift: list[DependencyDrift] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return self.freshness is not Freshness.FRESH


def node_status(store: GraphStore, node: Node) -> NodeStatus:
    """A node is stale when any recorded dependency digest is no longer current.

    Checked transitively: a dependency that is itself stale makes this node
    stale too, so a change deep in the graph surfaces at every claim above it.
    """
    refs = store.refs()
    drift: list[DependencyDrift] = []
    orphaned = False
    for dep in node.dependencies:
        current = refs.get(dep.key)
        if current is None:
            drift.append(DependencyDrift(dep.key, dep.digest, None))
            orphaned = True
        elif current != dep.digest:
            drift.append(DependencyDrift(dep.key, dep.digest, current))
        else:
            try:
                upstream = store.get(current)
            except NodeNotFoundError:
                drift.append(DependencyDrift(dep.key, dep.digest, None))
                orphaned = True
                continue
            if upstream.dependencies and node_status(store, upstream).stale:
                drift.append(DependencyDrift(dep.key, dep.digest, current))

    if orphaned:
        return NodeStatus(node, Freshness.ORPHANED, drift)
    if drift:
        return NodeStatus(node, Freshness.STALE, drift)
    return NodeStatus(node, Freshness.FRESH, [])


def status(store: GraphStore, node_type: NodeType | None = NodeType.CLAIM) -> list[NodeStatus]:
    nodes = store.all_current() if node_type is None else store.by_type(node_type)
    return sorted(
        (node_status(store, n) for n in nodes), key=lambda s: (s.freshness.value, s.node.key)
    )


def impact(store: GraphStore, key: str) -> list[Node]:
    """Every current node transitively depending on ``key`` — the blast radius.

    This is the answer to "I am about to change this material; what does that
    invalidate?" — available *before* making the change.
    """
    refs = store.refs()
    if key not in refs:
        raise KeyError(f"no node with key {key!r} in the graph")

    nodes = store.all_current()
    dependents: dict[str, list[Node]] = {}
    for node in nodes:
        for dep in node.dependencies:
            dependents.setdefault(dep.key, []).append(node)

    seen: set[str] = set()
    out: list[Node] = []
    frontier = [key]
    while frontier:
        current = frontier.pop()
        for node in dependents.get(current, []):
            if node.key in seen:
                continue
            seen.add(node.key)
            out.append(node)
            frontier.append(node.key)
    return sorted(out, key=lambda n: (n.type.value, n.key))


@dataclass
class AttestationStatus:
    node: Node
    valid: bool
    drift: list[DependencyDrift]

    @property
    def verdict(self) -> str:
        return "VALID" if self.valid else "VOID"


def attestation_status(store: GraphStore, node: Node) -> AttestationStatus:
    """A sign-off is void the moment anything it attested to has changed."""
    st = node_status(store, node)
    return AttestationStatus(node, not st.stale, st.drift)


def attestations(store: GraphStore) -> list[AttestationStatus]:
    return [attestation_status(store, n) for n in store.by_type(NodeType.ATTESTATION)]


def attested_claim_keys(store: GraphStore) -> set[str]:
    """Claim keys covered by a currently-valid human attestation."""
    covered: set[str] = set()
    for st in attestations(store):
        if not st.valid:
            continue
        if st.node.author.kind is not AuthorKind.HUMAN:
            continue
        covered.update(d.key for d in st.node.dependencies)
    return covered


@dataclass
class AiExposure:
    """AI-authored inputs and the claims resting on them.

    ``unattested`` is the number of dependent claims with no valid human
    sign-off — the machine-generated engineering nobody has vouched for.
    """

    node: Node
    dependent_claims: list[Node]
    unattested: list[Node]


def ai_exposure(store: GraphStore) -> list[AiExposure]:
    covered = attested_claim_keys(store)
    out: list[AiExposure] = []
    for node in store.all_current():
        if node.author.kind is not AuthorKind.AI:
            continue
        claims = [n for n in impact(store, node.key) if n.type is NodeType.CLAIM]
        out.append(AiExposure(
            node=node,
            dependent_claims=claims,
            unattested=[c for c in claims if c.key not in covered],
        ))
    return sorted(out, key=lambda e: e.node.key)
