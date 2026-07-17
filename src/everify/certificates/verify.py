"""Offline certificate verification: authenticity, integrity, reproducibility.

Three independent checks:
1. signature  — the Ed25519 signature verifies against the embedded public key
                (optionally pinned to a trusted key file you hold);
2. input hash — the embedded inputs still hash to inputs_sha256;
3. recompute  — every check is re-run from the embedded inputs with the local
                engine and must reproduce the recorded dispositions and margins.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from everify import __version__
from everify.certificates.canonical import canonical_bytes, sha256_hex
from everify.certificates.signing import load_public_key_raw, signature_valid, unb64
from everify.engine.verifier import verify_part
from everify.models.part import Part

MARGIN_RTOL = 1e-6


@dataclass
class CertificateVerification:
    signature_valid: bool = False
    issuer_key_pinned: bool | None = None  # None = no pin supplied
    inputs_hash_valid: bool = False
    reproduced: bool | None = None  # None = recompute not attempted
    tool_version_match: bool = True
    organization: str = ""
    key_fingerprint: str = ""
    overall_disposition: str = ""
    diffs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (
            self.signature_valid
            and self.inputs_hash_valid
            and self.issuer_key_pinned is not False
            and self.reproduced is True
        )


def _margins_close(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return math.isclose(a, b, rel_tol=MARGIN_RTOL, abs_tol=1e-9)


def verify_certificate(
    path: str | Path,
    pinned_pubkey: str | Path | None = None,
    pinned_fingerprint: str | None = None,
    recompute: bool = True,
) -> CertificateVerification:
    out = CertificateVerification()
    try:
        cert = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        out.errors.append(f"cannot read certificate: {exc}")
        return out

    out.organization = cert.get("issuer", {}).get("organization", "")
    out.key_fingerprint = cert.get("issuer", {}).get("key_fingerprint", "")
    out.overall_disposition = cert.get("overall_disposition", "")

    signature = cert.get("signature")
    if not isinstance(signature, dict) or "value" not in signature:
        out.errors.append("certificate has no signature block")
        return out
    if signature.get("algorithm") != "Ed25519":
        # Refuse unknown/none algorithms outright — no downgrade path.
        out.errors.append(
            f"unsupported signature algorithm {signature.get('algorithm')!r}; expected 'Ed25519'"
        )
        return out
    body = {k: v for k, v in cert.items() if k != "signature"}
    try:
        pub_raw = unb64(cert["issuer"]["public_key"])
        sig = unb64(signature["value"])
    except Exception as exc:
        out.errors.append(f"malformed signature/public key encoding: {exc}")
        return out
    out.signature_valid = signature_valid(pub_raw, sig, canonical_bytes(body))
    if not out.signature_valid:
        out.errors.append("Ed25519 signature does NOT verify: the document was altered or "
                          "was not signed by the embedded key")

    if cert["issuer"].get("key_fingerprint") != sha256_hex(pub_raw):
        out.errors.append("embedded key fingerprint does not match the embedded public key")
        out.signature_valid = False

    pins: list[bool] = []
    if pinned_pubkey is not None:
        try:
            match = load_public_key_raw(pinned_pubkey) == pub_raw
        except Exception as exc:
            match = False
            out.errors.append(f"cannot load pinned public key: {exc}")
        if not match:
            out.errors.append("issuer key does not match the pinned (trusted) public key")
        pins.append(match)
    if pinned_fingerprint is not None:
        fp = pinned_fingerprint.strip().lower().replace(":", "").replace(" ", "")
        actual = sha256_hex(pub_raw)
        if not re.fullmatch(r"[0-9a-f]{16,64}", fp):
            out.errors.append("pinned fingerprint must be 16–64 hex characters")
            pins.append(False)
        elif actual.startswith(fp):
            pins.append(True)
        else:
            out.errors.append("issuer key fingerprint does not match the pinned fingerprint")
            pins.append(False)
    out.issuer_key_pinned = all(pins) if pins else None

    part_doc = cert.get("subject", {}).get("part")
    out.inputs_hash_valid = (
        part_doc is not None
        and cert.get("inputs_sha256") == sha256_hex(canonical_bytes(part_doc))
    )
    if not out.inputs_hash_valid:
        out.errors.append("inputs_sha256 does not match the embedded part definition")

    tool_version = cert.get("tool", {}).get("version")
    out.tool_version_match = tool_version == __version__
    if not out.tool_version_match:
        out.diffs.append(
            f"certificate was issued by everify {tool_version}, verifying with {__version__}; "
            "recompute differences may reflect engine changes"
        )

    if not recompute:
        return out
    if part_doc is None:
        out.reproduced = False
        return out
    try:
        part = Part.model_validate(part_doc)
        rerun = verify_part(part, library={})
    except Exception as exc:
        out.reproduced = False
        out.errors.append(f"recompute failed: {exc}")
        return out

    recorded = {r["check_id"]: r for r in cert.get("results", [])}
    recomputed = {r.check_id: r for r in rerun.results}
    diffs: list[str] = []
    for cid in sorted(set(recorded) | set(recomputed)):
        if cid not in recorded:
            diffs.append(f"{cid}: produced by recompute but absent from certificate")
            continue
        if cid not in recomputed:
            diffs.append(f"{cid}: recorded in certificate but not produced by recompute")
            continue
        rec, new = recorded[cid], recomputed[cid]
        if rec.get("disposition") != new.disposition.value:
            diffs.append(f"{cid}: disposition {rec.get('disposition')} → {new.disposition.value}")
        if not _margins_close(rec.get("margin"), new.margin):
            diffs.append(f"{cid}: margin {rec.get('margin')} → {new.margin}")
    if cert.get("overall_disposition") != rerun.overall_disposition.value:
        diffs.append(
            f"overall: {cert.get('overall_disposition')} → {rerun.overall_disposition.value}"
        )
    out.diffs.extend(diffs)
    out.reproduced = not diffs
    if diffs:
        out.errors.append("recompute did not reproduce the recorded results")
    return out
