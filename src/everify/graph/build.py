"""Decompose parts into evidence nodes and bind verification claims to them.

A claim records the digest of every input it consumed. That binding is what
makes staleness provable later: the claim does not merely say "this part
passed", it says "this part passed *given exactly these inputs*", and anyone
can check whether those inputs are still the current ones.
"""

from __future__ import annotations

from everify.engine.results import CheckResult, Disposition
from everify.engine.verifier import verify_part
from everify.graph.nodes import Author, Dependency, Node, NodeType
from everify.graph.store import GraphStore
from everify.materials import load_material_library
from everify.models.material import Material
from everify.models.part import Part


def material_key(material: Material) -> str:
    return f"material:{material.id}"


def geometry_key(part: Part) -> str:
    return f"geometry:{part.id}"


def conditions_key(part: Part) -> str:
    return f"conditions:{part.id}"


def load_case_key(part: Part, case_name: str) -> str:
    return f"loadcase:{part.id}:{case_name}"


def part_key(part: Part) -> str:
    return f"part:{part.id}"


def claim_key(part: Part, check_id: str) -> str:
    return f"claim:{part.id}:{check_id}"


def _dep(store: GraphStore, node: Node) -> Dependency:
    return Dependency(key=node.key, digest=node.digest)


def add_part(
    store: GraphStore,
    part: Part,
    author: Author | None = None,
    library: dict[str, Material] | None = None,
    geometry_author: Author | None = None,
) -> list[Node]:
    """Decompose a part into input nodes, verify it, and store claim nodes.

    ``geometry_author`` lets callers mark geometry as AI-authored while the
    rest of the record stays tool-authored — the common case when a model
    proposes a design and everify checks it.
    """
    author = author or Author.tool()
    library = library if library is not None else load_material_library()
    resolved = part.resolved(library)
    material: Material = resolved.material

    stored: list[Node] = []
    input_deps: list[Dependency] = []

    def emit(node: Node) -> Node:
        store.put(node)
        stored.append(node)
        return node

    mat_node = emit(Node(
        key=material_key(material),
        type=NodeType.MATERIAL,
        content=material.model_dump(mode="json"),
        author=author,
        label=material.name,
    ))
    input_deps.append(_dep(store, mat_node))

    if resolved.geometry is not None:
        geom_node = emit(Node(
            key=geometry_key(resolved),
            type=NodeType.GEOMETRY,
            content=resolved.geometry.model_dump(mode="json"),
            author=geometry_author or author,
            label=f"{resolved.name} geometry",
        ))
        input_deps.append(_dep(store, geom_node))

    if resolved.design_conditions is not None:
        cond_node = emit(Node(
            key=conditions_key(resolved),
            type=NodeType.DESIGN_CONDITIONS,
            content=resolved.design_conditions.model_dump(mode="json"),
            author=author,
            label=f"{resolved.name} design conditions",
        ))
        input_deps.append(_dep(store, cond_node))

    for case in resolved.load_cases:
        case_node = emit(Node(
            key=load_case_key(resolved, case.name),
            type=NodeType.LOAD_CASE,
            content=case.model_dump(mode="json"),
            author=author,
            label=case.name,
        ))
        input_deps.append(_dep(store, case_node))

    part_node = emit(Node(
        key=part_key(resolved),
        type=NodeType.PART,
        content={
            "id": resolved.id,
            "name": resolved.name,
            "revision": resolved.revision,
            "description": resolved.description,
            "standards": resolved.standards,
            "notes": resolved.notes,
        },
        dependencies=list(input_deps),
        author=author,
        label=resolved.name,
    ))
    part_dep = _dep(store, part_node)

    run = verify_part(resolved, library)
    for result in run.results:
        emit(_claim_node(resolved, result, [part_dep, *input_deps], author))

    return stored


def _claim_node(
    part: Part, result: CheckResult, deps: list[Dependency], author: Author
) -> Node:
    return Node(
        key=claim_key(part, result.check_id),
        type=NodeType.CLAIM,
        content={
            "check_id": result.check_id,
            "title": result.title,
            "clause": result.clause.model_dump(mode="json"),
            "disposition": result.disposition.value,
            "margin": result.margin,
            "formula": result.formula,
            "substitution": result.substitution,
            "computed": [c.model_dump(mode="json") for c in result.computed],
            "criterion": result.criterion,
            "assumptions": result.assumptions,
            "warnings": result.warnings,
            "message": result.message,
        },
        dependencies=deps,
        author=author,
        label=result.title,
    )


def claim_disposition(node: Node) -> Disposition:
    return Disposition(node.content["disposition"])
