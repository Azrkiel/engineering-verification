"""Canonical JSON encoding: the byte form that hashes and signatures cover.

Sorted keys, compact separators, UTF-8, no ASCII escaping — so the same
document always produces the same bytes regardless of file formatting.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
