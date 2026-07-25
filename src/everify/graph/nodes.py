"""Evidence graph nodes: a Merkle DAG over engineering claims.

Every node carries two identifiers:

- ``key``   — stable logical identity that survives edits
              (e.g. ``material:SA-516-70``, ``geometry:AR-1001-SHELL``)
- ``digest`` — content hash over the node's canonical content *and the digests
              of its dependencies*

Because upstream digests fold into downstream ones, staleness is detected
cryptographically rather than by bookkeeping: a claim records the digest of
every input it consumed, so if anything anywhere upstream changed, the
recorded digest simply no longer matches the current one. There is no
invalidation logic to get wrong and no way for a change to go unnoticed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from everify.certificates.canonical import canonical_bytes, sha256_hex
from everify.models.base import EverifyModel


class NodeType(StrEnum):
    REQUIREMENT = "requirement"
    MATERIAL = "material"
    GEOMETRY = "geometry"
    DESIGN_CONDITIONS = "design_conditions"
    LOAD_CASE = "load_case"
    EXTERNAL_ANALYSIS = "external_analysis"
    PART = "part"
    CLAIM = "claim"
    ATTESTATION = "attestation"


class AuthorKind(StrEnum):
    HUMAN = "human"
    AI = "ai"
    TOOL = "tool"


class Author(EverifyModel):
    """Who or what produced this node.

    The AI kind is what makes machine-generated engineering auditable: the
    graph can answer which inputs were model-authored and whether a human
    ever attested to the claims that depend on them.
    """

    kind: AuthorKind = AuthorKind.HUMAN
    id: str = Field(description="Person, model identifier, or tool name")
    note: str | None = None

    @classmethod
    def tool(cls, name: str = "everify") -> Author:
        return cls(kind=AuthorKind.TOOL, id=name)


class Dependency(EverifyModel):
    """A recorded edge: the logical key consumed, and the exact digest seen."""

    key: str
    digest: str


class Node(EverifyModel):
    """An immutable, content-addressed evidence node."""

    key: str
    type: NodeType
    content: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[Dependency] = Field(default_factory=list)
    author: Author = Field(default_factory=Author.tool)
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    label: str | None = None

    def identity(self) -> dict[str, Any]:
        """The bytes that define this node's identity.

        Deliberately excludes ``created_at`` and ``label``: re-adding
        unchanged content must not manufacture a spurious new version, or
        every rebuild would look like a change and staleness would be noise.
        """
        return {
            "key": self.key,
            "type": self.type.value,
            "content": self.content,
            "dependencies": sorted(
                ({"key": d.key, "digest": d.digest} for d in self.dependencies),
                key=lambda d: (d["key"], d["digest"]),
            ),
            "author": self.author.model_dump(mode="json", exclude_none=True),
        }

    @property
    def digest(self) -> str:
        return sha256_hex(canonical_bytes(self.identity()))

    @property
    def short(self) -> str:
        return self.digest[:12]

    def depends_on(self, key: str) -> str | None:
        for d in self.dependencies:
            if d.key == key:
                return d.digest
        return None
