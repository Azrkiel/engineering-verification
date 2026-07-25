"""Content-addressed node store, deliberately git-shaped and file-based.

Layout::

    .everify/
      objects/<digest>.json   immutable node objects
      refs.json               logical key -> current digest (the working state)

Objects are never mutated or deleted, so the full history of every claim
remains auditable; ``refs.json`` is the only mutable file and it simply names
which version of each key is current. Plain JSON on disk keeps the evidence
diffable and reviewable in version control alongside the design itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from everify.graph.nodes import Node

STORE_DIR = ".everify"


class NodeNotFoundError(KeyError):
    pass


class GraphStore:
    def __init__(self, root: str | Path = "."):
        self.root = Path(root)
        self.dir = self.root / STORE_DIR
        self.objects = self.dir / "objects"
        self.refs_path = self.dir / "refs.json"

    # ------------------------------------------------------------- lifecycle

    @property
    def initialized(self) -> bool:
        return self.dir.is_dir()

    def init(self) -> Path:
        self.objects.mkdir(parents=True, exist_ok=True)
        if not self.refs_path.exists():
            self._write_refs({})
        return self.dir

    def _require(self) -> None:
        if not self.initialized:
            raise FileNotFoundError(
                f"no evidence graph at {self.root} — run 'everify graph init' first"
            )

    # ----------------------------------------------------------------- refs

    def refs(self) -> dict[str, str]:
        self._require()
        if not self.refs_path.exists():
            return {}
        return json.loads(self.refs_path.read_text())

    def _write_refs(self, refs: dict[str, str]) -> None:
        self.refs_path.write_text(json.dumps(refs, indent=2, sort_keys=True) + "\n")

    def current_digest(self, key: str) -> str | None:
        return self.refs().get(key)

    # --------------------------------------------------------------- objects

    def put(self, node: Node, update_ref: bool = True) -> str:
        """Store a node; returns its digest. Idempotent for identical content."""
        self._require()
        digest = node.digest
        path = self.objects / f"{digest}.json"
        if not path.exists():
            path.write_text(
                json.dumps(node.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
            )
        if update_ref:
            refs = self.refs()
            refs[node.key] = digest
            self._write_refs(refs)
        return digest

    def get(self, digest: str) -> Node:
        self._require()
        path = self.objects / f"{digest}.json"
        if not path.exists():
            raise NodeNotFoundError(f"no node object {digest[:12]} in {self.objects}")
        return Node.model_validate(json.loads(path.read_text()))

    def get_current(self, key: str) -> Node | None:
        digest = self.current_digest(key)
        return self.get(digest) if digest else None

    def all_current(self) -> list[Node]:
        return [self.get(d) for d in self.refs().values()]

    def by_type(self, node_type) -> list[Node]:
        return [n for n in self.all_current() if n.type is node_type]

    def history(self, key: str) -> list[Node]:
        """Every stored version of a key, oldest first — the audit trail."""
        self._require()
        out = []
        for path in self.objects.glob("*.json"):
            node = Node.model_validate(json.loads(path.read_text()))
            if node.key == key:
                out.append(node)
        return sorted(out, key=lambda n: n.created_at)

    def state_root(self) -> str:
        """Merkle root over the whole working state — one hash for the graph."""
        from everify.certificates.canonical import canonical_bytes, sha256_hex

        return sha256_hex(canonical_bytes(self.refs()))
