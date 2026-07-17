"""Certificate integrity: signing, tamper detection, reproducibility."""

import json

import pytest

from everify.certificates import build_certificate, generate_keys, verify_certificate
from everify.certificates.canonical import canonical_bytes
from everify.certificates.signing import b64, load_private_key, sign
from everify.engine import verify_part
from everify.materials import load_material_library
from everify.models import Part

PART_DOC = {
    "id": "C-1",
    "name": "certificate test shell",
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


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    generate_keys(d, "Test Engineering LLC")
    return d


@pytest.fixture()
def cert(keys):
    run = verify_part(Part.model_validate(PART_DOC), load_material_library())
    return build_certificate(run, keys)


def _write(tmp_path, cert):
    p = tmp_path / "part.cert.json"
    p.write_text(json.dumps(cert, indent=2, ensure_ascii=False))
    return p


def test_round_trip_verifies(tmp_path, keys, cert):
    path = _write(tmp_path, cert)
    out = verify_certificate(path, pinned_pubkey=keys / "everify_org.pub")
    assert out.signature_valid
    assert out.inputs_hash_valid
    assert out.issuer_key_pinned is True
    assert out.reproduced is True
    assert out.ok


def test_certificate_carries_scope_statement(cert):
    assert "NOT an ASME Code Symbol Stamp" in cert["scope_statement"]
    assert cert["professional_review"]["reviewer_name"] is None


def test_result_tamper_breaks_signature(tmp_path, cert):
    cert["results"][0]["margin"] = 99.9
    out = verify_certificate(_write(tmp_path, cert))
    assert not out.signature_valid
    assert not out.ok


def test_input_tamper_breaks_hash_and_signature(tmp_path, cert):
    cert["subject"]["part"]["geometry"]["nominal_thickness"] = "1.000 in"
    out = verify_certificate(_write(tmp_path, cert))
    assert not out.inputs_hash_valid
    assert not out.signature_valid
    assert not out.ok


def test_single_byte_tamper_detected(tmp_path, keys, cert):
    path = _write(tmp_path, cert)
    raw = path.read_text()
    corrupted = raw.replace("250 psi", "251 psi", 1)
    assert corrupted != raw
    path.write_text(corrupted)
    out = verify_certificate(path, pinned_pubkey=keys / "everify_org.pub")
    assert not out.ok


def test_resigned_forgery_fails_recompute(tmp_path, keys, cert):
    # An attacker WITH the org key still cannot alter results undetected,
    # because verification recomputes every check from the embedded inputs.
    cert["results"][0]["margin"] = 1.234
    cert["overall_disposition"] = "PASS"
    body = {k: v for k, v in cert.items() if k != "signature"}
    private, _ = load_private_key(keys)
    cert["signature"]["value"] = b64(sign(private, canonical_bytes(body)))
    out = verify_certificate(_write(tmp_path, cert))
    assert out.signature_valid  # signature is formally valid...
    assert out.reproduced is False  # ...but the math does not reproduce
    assert not out.ok


def test_wrong_pinned_key_rejected(tmp_path, cert, tmp_path_factory):
    other = tmp_path_factory.mktemp("otherkeys")
    generate_keys(other, "Somebody Else Inc")
    out = verify_certificate(_write(tmp_path, cert), pinned_pubkey=other / "everify_org.pub")
    assert out.issuer_key_pinned is False
    assert not out.ok


def test_file_formatting_and_key_order_independence(tmp_path, keys, cert):
    # Signature covers the canonical form, so key order, indentation, and
    # ASCII escaping of the on-disk file must not matter.
    reordered = dict(reversed(list(cert.items())))
    path = tmp_path / "reordered.cert.json"
    path.write_text(json.dumps(reordered, indent=4, ensure_ascii=True))
    out = verify_certificate(path, pinned_pubkey=keys / "everify_org.pub")
    assert out.ok


def test_unknown_signature_algorithm_rejected(tmp_path, cert):
    cert["signature"]["algorithm"] = "none"
    out = verify_certificate(_write(tmp_path, cert))
    assert not out.ok
    assert any("unsupported signature algorithm" in e for e in out.errors)


def test_fingerprint_pinning(tmp_path, cert):
    fp = cert["issuer"]["key_fingerprint"]
    ok = verify_certificate(_write(tmp_path, cert), pinned_fingerprint=fp[:20].upper())
    assert ok.issuer_key_pinned is True and ok.ok
    bad = verify_certificate(_write(tmp_path, cert), pinned_fingerprint="deadbeef" * 4)
    assert bad.issuer_key_pinned is False and not bad.ok
    malformed = verify_certificate(_write(tmp_path, cert), pinned_fingerprint="xyz")
    assert malformed.issuer_key_pinned is False and not malformed.ok
