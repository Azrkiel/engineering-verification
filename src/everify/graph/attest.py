"""Human attestation: a signed sign-off bound to exact claim digests.

This is the mechanism that makes engineering sign-off self-policing. The
reviewer signs specific claims *as they were*. If anyone later edits the
geometry, the material, or the design conditions, the attestation's recorded
digests no longer match and the sign-off is void — provably, with the
changed input named. No process discipline required, and no way to
accidentally ship a design carrying a signature that was given for a
different design.
"""

from __future__ import annotations

from pathlib import Path

from everify.certificates.canonical import canonical_bytes
from everify.certificates.signing import b64, load_private_key, sign
from everify.graph.nodes import Author, AuthorKind, Dependency, Node, NodeType
from everify.graph.store import GraphStore


class NoSuchClaimError(KeyError):
    pass


def attestation_key(reviewer: str, scope: str) -> str:
    slug = reviewer.lower().replace(" ", "-")
    return f"attestation:{slug}:{scope}"


def attest_claims(
    store: GraphStore,
    claim_keys: list[str],
    reviewer: str,
    scope: str,
    keys_dir: str | Path | None = None,
    license_number: str | None = None,
    jurisdiction: str | None = None,
    statement: str | None = None,
) -> Node:
    """Record a reviewer's sign-off over the current version of given claims."""
    refs = store.refs()
    deps: list[Dependency] = []
    for key in claim_keys:
        digest = refs.get(key)
        if digest is None:
            raise NoSuchClaimError(f"no claim {key!r} in the graph")
        deps.append(Dependency(key=key, digest=digest))
    if not deps:
        raise NoSuchClaimError("an attestation must cover at least one claim")

    content: dict = {
        "reviewer": reviewer,
        "scope": scope,
        "license_number": license_number,
        "jurisdiction": jurisdiction,
        "statement": statement or (
            "I have reviewed the computational verification results identified by this "
            "attestation and accept them as the basis for engineering review. This "
            "attestation covers only the cited claims as recorded and is void if any "
            "input they depend on changes."
        ),
    }

    node = Node(
        key=attestation_key(reviewer, scope),
        type=NodeType.ATTESTATION,
        content=content,
        dependencies=deps,
        author=Author(kind=AuthorKind.HUMAN, id=reviewer),
        label=f"{reviewer} — {scope}",
    )

    if keys_dir is not None:
        private, meta = load_private_key(keys_dir)
        signature = sign(private, canonical_bytes(node.identity()))
        node = node.model_copy(update={"content": {
            **content,
            "signature": {
                "algorithm": "Ed25519",
                "value": b64(signature),
                "organization": meta["organization"],
                "key_fingerprint": meta["key_fingerprint"],
                "covers": "canonical JSON of this attestation's identity "
                          "(key, type, content without signature, dependencies, author)",
            },
        }})

    store.put(node)
    return node
