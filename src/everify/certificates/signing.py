"""Ed25519 key management and signatures for certificates.

The signature proves INTEGRITY and ORIGIN of a certificate document: that it
was produced by the holder of the organization's key and has not been altered.
It is not a Professional Engineer's seal and confers no regulatory status.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from everify.certificates.canonical import sha256_hex

PRIVATE_KEY_NAME = "everify_org.key"
PUBLIC_KEY_NAME = "everify_org.pub"
META_NAME = "everify_org.json"


def fingerprint(pub_raw: bytes) -> str:
    return sha256_hex(pub_raw)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def generate_keys(out_dir: str | Path, organization: str) -> dict:
    """Create an organization keypair. The private key file is chmod 0600 and
    must be protected like any signing credential."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key_path = out / PRIVATE_KEY_NAME
    if key_path.exists():
        raise FileExistsError(f"{key_path} already exists; refusing to overwrite a signing key")

    private = Ed25519PrivateKey.generate()
    pem_private = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    pem_public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    key_path.write_bytes(pem_private)
    os.chmod(key_path, 0o600)
    (out / PUBLIC_KEY_NAME).write_bytes(pem_public)
    meta = {
        "organization": organization,
        "key_fingerprint": fingerprint(pub_raw),
        "algorithm": "Ed25519",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / META_NAME).write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def load_private_key(keys_dir: str | Path) -> tuple[Ed25519PrivateKey, dict]:
    keys = Path(keys_dir)
    private = serialization.load_pem_private_key((keys / PRIVATE_KEY_NAME).read_bytes(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise TypeError(f"{keys / PRIVATE_KEY_NAME} is not an Ed25519 private key")
    meta = json.loads((keys / META_NAME).read_text())
    return private, meta


def load_public_key_raw(path: str | Path) -> bytes:
    public = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(public, Ed25519PublicKey):
        raise TypeError(f"{path} is not an Ed25519 public key")
    return public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def sign(private: Ed25519PrivateKey, data: bytes) -> bytes:
    return private.sign(data)


def signature_valid(pub_raw: bytes, signature: bytes, data: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(signature, data)
        return True
    except InvalidSignature:
        return False
