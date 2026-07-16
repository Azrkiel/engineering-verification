"""Build signed verification certificates.

A certificate is a self-contained JSON document embedding the complete inputs
(part definition including full material data), every check result with its
clause citation and math, the tool version, an explicit scope statement, a
block for the reviewing engineer, and an Ed25519 signature over the canonical
form of everything above. Anyone can verify it offline — and re-run the
checks from the embedded inputs — with `everify verify`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from everify import __version__
from everify.certificates.canonical import canonical_bytes, sha256_hex
from everify.certificates.signing import b64, fingerprint, load_private_key, sign
from everify.engine.results import VerificationRun

from cryptography.hazmat.primitives import serialization

SCHEMA = "everify.certificate/v1"

SCOPE_STATEMENT = (
    "This certificate attests only that the computational verifications listed herein were "
    "performed by the everify software, at the stated version, on the stated inputs, against "
    "the cited clauses of the referenced standards, producing the recorded results. It is NOT "
    "an ASME Code Symbol Stamp or Certificate of Authorization, NOT an FAA approval or finding "
    "of compliance, and NOT a certificate of regulatory conformity of any kind; it does not by "
    "itself establish fitness for service. The cited checks cover only the specific rules "
    "listed and never the entirety of any standard. Engineering acceptance requires review and "
    "approval by a qualified engineer (where applicable, a licensed Professional Engineer or "
    "authorized representative), verification of material data against the governing code "
    "edition, and compliance with all requirements of the applicable regulatory framework."
)

PROFESSIONAL_REVIEW_STATEMENT = (
    "Engineering acceptance of these computational results requires independent review. "
    "The reviewing engineer completes this block (and applies any seal required by their "
    "jurisdiction) on the rendered certificate."
)


def build_certificate(run: VerificationRun, keys_dir: str | Path) -> dict:
    private, meta = load_private_key(keys_dir)
    pub_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    part_doc = run.part.model_dump(mode="json")
    cert: dict = {
        "schema": SCHEMA,
        "kind": "engineering-verification-certificate",
        "tool": {"name": "everify", "version": __version__},
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "issuer": {
            "organization": meta["organization"],
            "public_key": b64(pub_raw),
            "key_fingerprint": fingerprint(pub_raw),
        },
        "subject": {"part": part_doc},
        "inputs_sha256": sha256_hex(canonical_bytes(part_doc)),
        "standards": [s.model_dump(mode="json") for s in run.standards],
        "results": [r.model_dump(mode="json") for r in run.results],
        "overall_disposition": run.overall_disposition.value,
        "scope_statement": SCOPE_STATEMENT,
        "professional_review": {
            "statement": PROFESSIONAL_REVIEW_STATEMENT,
            "reviewer_name": None,
            "license_number": None,
            "jurisdiction": None,
            "reviewed_at": None,
        },
    }
    signature = sign(private, canonical_bytes(cert))
    cert["signature"] = {
        "algorithm": "Ed25519",
        "value": b64(signature),
        "covers": "canonical JSON (sorted keys, compact separators, UTF-8) of this document "
                  "without the 'signature' member",
    }
    return cert


def certificate_id(cert: dict) -> str:
    """Short content-derived identifier for citing a certificate."""
    return sha256_hex(canonical_bytes(cert))[:16]
