"""Canonical JSON serialization (canonical-json-v1) and SHA-256 helpers.

canonical-json-v1: keys sorted, separators "," and ":" with no whitespace, UTF-8
encoding, non-ASCII characters kept literal, NaN and Infinity rejected. Input must
already be JSON-compatible (for Pydantic models: model_dump(mode="json")).

sha256-lf-v1 (file fingerprints): SHA-256 of a text file's bytes after CRLF is
normalized to LF, so fingerprints match across Windows and Linux checkouts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

CANONICAL_JSON_V1: Final = "canonical-json-v1"
FILE_FINGERPRINT_V1: Final = "sha256-lf-v1"


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize JSON-compatible data deterministically."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(obj: Any) -> str:
    """SHA-256 hex digest of the canonical-json-v1 serialization."""
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def file_sha256(path: str | Path) -> str:
    """SHA-256 hex digest of a text file using the sha256-lf-v1 scheme."""
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()
