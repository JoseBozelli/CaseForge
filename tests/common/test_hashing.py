"""Tests for canonical JSON serialization and hashing."""

import pytest

from caseforge.common.hashing import canonical_json_bytes, sha256_hex


def test_key_order_does_not_change_serialization() -> None:
    assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert canonical_json_bytes({"a": 2, "b": 1}) == b'{"a":2,"b":1}'


def test_non_ascii_kept_as_utf8() -> None:
    assert canonical_json_bytes({"k": "é"}) == '{"k":"é"}'.encode()


def test_nan_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"x": float("nan")})


def test_sha256_is_stable_and_content_sensitive() -> None:
    digest = sha256_hex({"a": 1, "b": [1, 2]})
    assert len(digest) == 64
    assert digest == sha256_hex({"b": [1, 2], "a": 1})
    assert digest != sha256_hex({"a": 1, "b": [2, 1]})
