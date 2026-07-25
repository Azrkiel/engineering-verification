"""Evidence graph: digest identity, staleness, blast radius, attestation voiding."""

import json

import pytest

from everify.graph import (
    Author,
    AuthorKind,
    Dependency,
    Freshness,
    GraphStore,
    Node,
    NodeType,
    add_part,
    ai_exposure,
    attest_claims,
    attestation_status,
    attestations,
    impact,
    node_status,
    status,
)
from everify.models import Part

PART_DOC = {
    "id": "G-1",
    "name": "graph test shell",
    "material": "SA-516-70",
    "geometry": {
        "type": "cylindrical_shell",
        "inside_diameter": "48 inch",
        "nominal_thickness": "0.500 inch",
    },
    "design_conditions": {
        "design_pressure": "250 psi",
        "design_temperature": "500 degF",
        "corrosion_allowance": "0.125 inch",
        "joint_efficiency": 0.85,
    },
    "standards": ["asme-viii-div1"],
}


@pytest.fixture()
def store(tmp_path):
    s = GraphStore(tmp_path)
    s.init()
    return s


@pytest.fixture()
def populated(store, library):
    add_part(store, Part.model_validate(PART_DOC), library=library)
    return store


def claim_keys(store):
    return sorted(n.key for n in store.by_type(NodeType.CLAIM))


class TestDigestIdentity:
    def test_same_content_same_digest_regardless_of_key_order(self):
        a = Node(key="k", type=NodeType.MATERIAL, content={"x": 1, "y": [1, 2], "z": "s"})
        b = Node(key="k", type=NodeType.MATERIAL, content={"z": "s", "y": [1, 2], "x": 1})
        assert a.digest == b.digest

    def test_content_change_changes_digest(self):
        a = Node(key="k", type=NodeType.MATERIAL, content={"x": 1})
        b = Node(key="k", type=NodeType.MATERIAL, content={"x": 1.0000001})
        assert a.digest != b.digest

    def test_dependency_digest_folds_into_node_digest(self):
        base = Node(key="k", type=NodeType.CLAIM,
                    dependencies=[Dependency(key="m", digest="a" * 64)])
        moved = Node(key="k", type=NodeType.CLAIM,
                     dependencies=[Dependency(key="m", digest="b" * 64)])
        assert base.digest != moved.digest

    def test_dependency_order_does_not_matter(self):
        d1 = Dependency(key="m", digest="a" * 64)
        d2 = Dependency(key="g", digest="b" * 64)
        assert (Node(key="k", type=NodeType.CLAIM, dependencies=[d1, d2]).digest
                == Node(key="k", type=NodeType.CLAIM, dependencies=[d2, d1]).digest)

    def test_timestamp_and_label_do_not_affect_identity(self):
        a = Node(key="k", type=NodeType.MATERIAL, content={"x": 1},
                 created_at="2020-01-01T00:00:00+00:00", label="one")
        b = Node(key="k", type=NodeType.MATERIAL, content={"x": 1},
                 created_at="2026-07-25T12:00:00+00:00", label="two")
        # Re-adding unchanged content must not look like a change.
        assert a.digest == b.digest

    def test_author_is_part_of_identity(self):
        human = Node(key="k", type=NodeType.GEOMETRY, content={"x": 1},
                     author=Author(kind=AuthorKind.HUMAN, id="dana"))
        ai = Node(key="k", type=NodeType.GEOMETRY, content={"x": 1},
                  author=Author(kind=AuthorKind.AI, id="some-model"))
        assert human.digest != ai.digest


class TestStore:
    def test_put_get_round_trip(self, store):
        node = Node(key="material:X", type=NodeType.MATERIAL, content={"a": 1})
        digest = store.put(node)
        assert store.get(digest).content == {"a": 1}
        assert store.current_digest("material:X") == digest

    def test_objects_are_immutable_history(self, store):
        first = Node(key="material:X", type=NodeType.MATERIAL, content={"S": 20000})
        d1 = store.put(first)
        second = Node(key="material:X", type=NodeType.MATERIAL, content={"S": 17500})
        d2 = store.put(second)
        assert d1 != d2
        assert store.get(d1).content["S"] == 20000  # old version still auditable
        assert store.current_digest("material:X") == d2
        assert len(store.history("material:X")) == 2

    def test_state_root_changes_with_any_update(self, populated):
        before = populated.state_root()
        populated.put(Node(key="material:SA-516-70", type=NodeType.MATERIAL,
                           content={"changed": True}))
        assert populated.state_root() != before

    def test_uninitialized_store_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="graph init"):
            GraphStore(tmp_path / "nope").refs()


class TestBuild:
    def test_decomposes_part_into_typed_nodes(self, populated):
        types = {n.type for n in populated.all_current()}
        assert {NodeType.MATERIAL, NodeType.GEOMETRY, NodeType.DESIGN_CONDITIONS,
                NodeType.PART, NodeType.CLAIM} <= types

    def test_claims_match_engine_results(self, populated):
        assert claim_keys(populated) == [
            "claim:G-1:viii1.mawp", "claim:G-1:viii1.ug16b", "claim:G-1:viii1.ug27c1",
            "claim:G-1:viii1.ug27c2", "claim:G-1:viii1.ug99b",
        ]

    def test_claim_records_input_digests(self, populated):
        claim = populated.get_current("claim:G-1:viii1.ug27c1")
        assert claim.depends_on("material:SA-516-70") == \
            populated.current_digest("material:SA-516-70")
        assert claim.depends_on("geometry:G-1") == populated.current_digest("geometry:G-1")

    def test_re_adding_unchanged_part_is_idempotent(self, populated, library):
        before = populated.state_root()
        add_part(populated, Part.model_validate(PART_DOC), library=library)
        assert populated.state_root() == before

    def test_load_cases_become_nodes(self, store, library):
        part = Part.model_validate({
            "id": "F-1", "name": "fitting", "material": "7075-T6-sheet",
            "load_cases": [{"name": "2.5g", "limit_stress": "30 ksi"}],
            "standards": ["far-25"],
        })
        add_part(store, part, library=library)
        assert store.get_current("loadcase:F-1:2.5g") is not None


class TestStaleness:
    def _revise_material(self, store):
        """Simulate a shared material record being revised org-wide, without
        anybody re-running the analyses that depend on it."""
        current = store.get_current("material:SA-516-70")
        revised = current.model_copy(update={
            "content": {**current.content, "revision_note": "allowables revised"},
        })
        store.put(revised)
        return revised

    def test_claims_fresh_when_nothing_changed(self, populated):
        assert all(s.freshness is Freshness.FRESH for s in status(populated))

    def test_upstream_change_makes_every_dependent_claim_stale(self, populated):
        self._revise_material(populated)
        states = {s.node.key: s for s in status(populated)}
        assert len(states) == 5
        assert all(s.freshness is Freshness.STALE for s in states.values())

    def test_stale_claim_names_the_changed_input(self, populated):
        self._revise_material(populated)
        st = node_status(populated, populated.get_current("claim:G-1:viii1.ug27c1"))
        described = [d.describe() for d in st.drift]
        assert any("material:SA-516-70" in d and "→" in d for d in described)

    def test_staleness_propagates_transitively_through_the_part_node(self, populated):
        # Claims depend on the part node, which depends on the geometry.
        current = populated.get_current("geometry:G-1")
        populated.put(current.model_copy(update={
            "content": {**current.content, "nominal_thickness": "0.4375 in"},
        }))
        assert all(s.stale for s in status(populated))

    def test_recompute_restores_freshness(self, populated, library):
        self._revise_material(populated)
        assert all(s.stale for s in status(populated))
        add_part(populated, Part.model_validate(PART_DOC), library=library)
        assert all(s.freshness is Freshness.FRESH for s in status(populated))

    def test_orphaned_when_dependency_removed(self, populated):
        refs = populated.refs()
        del refs["material:SA-516-70"]
        populated._write_refs(refs)
        assert all(s.freshness is Freshness.ORPHANED for s in status(populated))


class TestImpact:
    def test_blast_radius_matches_brute_force_reachability(self, populated):
        affected = {n.key for n in impact(populated, "material:SA-516-70")}

        # Independent reference: repeatedly close over direct dependents.
        nodes = populated.all_current()
        expected, frontier = set(), {"material:SA-516-70"}
        while frontier:
            nxt = set()
            for node in nodes:
                if node.key in expected:
                    continue
                if any(d.key in frontier for d in node.dependencies):
                    expected.add(node.key)
                    nxt.add(node.key)
            frontier = nxt
        assert affected == expected

    def test_impact_includes_claims_and_part(self, populated):
        keys = {n.key for n in impact(populated, "geometry:G-1")}
        assert "part:G-1" in keys
        assert "claim:G-1:viii1.ug27c1" in keys

    def test_leaf_change_has_no_dependents(self, populated):
        assert impact(populated, "claim:G-1:viii1.mawp") == []

    def test_unknown_key_raises(self, populated):
        with pytest.raises(KeyError):
            impact(populated, "material:does-not-exist")


class TestAttestation:
    def test_attestation_valid_when_nothing_changed(self, populated):
        attest_claims(populated, claim_keys(populated), reviewer="Dana Ruiz", scope="rev-A")
        assert all(a.valid for a in attestations(populated))

    def test_attestation_voids_when_a_reviewed_claim_changes(self, populated, library):
        node = attest_claims(populated, claim_keys(populated), reviewer="Dana Ruiz", scope="rev-A")
        assert attestation_status(populated, node).valid

        thinner = dict(PART_DOC, geometry={**PART_DOC["geometry"],
                                           "nominal_thickness": "0.4375 inch"})
        add_part(populated, Part.model_validate(thinner), library=library)

        after = attestation_status(populated, populated.get_current(node.key))
        assert not after.valid
        assert after.verdict == "VOID"
        assert len(after.drift) == 5

    def test_signed_attestation_carries_signature(self, populated, tmp_path):
        from everify.certificates import generate_keys

        keys = tmp_path / "keys"
        generate_keys(keys, "Acme Engineering")
        node = attest_claims(populated, claim_keys(populated), reviewer="Dana Ruiz",
                             scope="rev-A", keys_dir=keys)
        sig = node.content["signature"]
        assert sig["algorithm"] == "Ed25519"
        assert sig["organization"] == "Acme Engineering"

    def test_attesting_unknown_claim_raises(self, populated):
        with pytest.raises(KeyError):
            attest_claims(populated, ["claim:G-1:nope"], reviewer="R", scope="s")

    def test_empty_attestation_rejected(self, populated):
        with pytest.raises(KeyError):
            attest_claims(populated, [], reviewer="R", scope="s")


class TestAiProvenance:
    @pytest.fixture()
    def ai_graph(self, store, library):
        add_part(store, Part.model_validate(PART_DOC), library=library,
                 geometry_author=Author(kind=AuthorKind.AI, id="test-model-v1"))
        return store

    def test_ai_authored_input_is_tracked_with_dependent_claims(self, ai_graph):
        exposure = ai_exposure(ai_graph)
        assert len(exposure) == 1
        assert exposure[0].node.key == "geometry:G-1"
        assert exposure[0].node.author.id == "test-model-v1"
        assert len(exposure[0].dependent_claims) == 5

    def test_ai_claims_start_unattested(self, ai_graph):
        assert len(ai_exposure(ai_graph)[0].unattested) == 5

    def test_human_attestation_clears_ai_exposure(self, ai_graph):
        attest_claims(ai_graph, claim_keys(ai_graph), reviewer="Dana Ruiz", scope="ai-review")
        assert ai_exposure(ai_graph)[0].unattested == []

    def test_voided_attestation_reopens_ai_exposure(self, ai_graph, library):
        attest_claims(ai_graph, claim_keys(ai_graph), reviewer="Dana Ruiz", scope="ai-review")
        assert ai_exposure(ai_graph)[0].unattested == []

        thinner = dict(PART_DOC, geometry={**PART_DOC["geometry"],
                                           "nominal_thickness": "0.4375 inch"})
        add_part(ai_graph, Part.model_validate(thinner), library=library,
                 geometry_author=Author(kind=AuthorKind.AI, id="test-model-v1"))

        # The AI revised the design after sign-off: coverage must lapse.
        assert len(ai_exposure(ai_graph)[0].unattested) == 5

    def test_tool_authored_graph_has_no_ai_exposure(self, populated):
        assert ai_exposure(populated) == []


class TestGraphCli:
    def test_end_to_end_flow(self, tmp_path, monkeypatch):
        import os

        from typer.testing import CliRunner

        from everify.cli import app

        os.environ["COLUMNS"] = "250"
        runner = CliRunner()
        part_file = tmp_path / "part.yaml"
        part_file.write_text(json.dumps(PART_DOC))  # JSON is valid YAML
        root = ["--root", str(tmp_path)]

        assert runner.invoke(app, ["graph", "init", *root]).exit_code == 0
        add = runner.invoke(app, ["graph", "add", str(part_file), *root,
                                  "--geometry-author", "test-model-v1"])
        assert add.exit_code == 0, add.output

        st = runner.invoke(app, ["graph", "status", *root])
        assert st.exit_code == 0, st.output
        assert "FRESH" in st.output

        att = runner.invoke(app, ["attest", *root, "--reviewer", "Dana Ruiz, P.E.",
                                  "--scope", "rev-A"])
        assert att.exit_code == 0, att.output

        # Change the design; status must report VOID and exit non-zero.
        part_file.write_text(json.dumps(dict(
            PART_DOC, geometry={**PART_DOC["geometry"], "nominal_thickness": "0.4375 inch"})))
        assert runner.invoke(app, ["graph", "add", str(part_file), *root]).exit_code == 0

        after = runner.invoke(app, ["graph", "status", *root])
        assert after.exit_code == 1
        assert "VOID" in after.output

        js = runner.invoke(app, ["graph", "status", *root, "--json"])
        doc = json.loads(js.output)
        assert doc["attestations"][0]["verdict"] == "VOID"
        assert doc["state_root"]

        imp = runner.invoke(app, ["graph", "impact", "material:SA-516-70", *root])
        assert imp.exit_code == 0
        assert "claim:G-1" in imp.output

        log = runner.invoke(app, ["graph", "log", "geometry:G-1", *root])
        assert log.exit_code == 0
        assert log.output.count("by") >= 2  # two recorded versions
