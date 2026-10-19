"""The configuration fingerprint must not depend on the process that computes it."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from caseforge.settings.models import GovernanceSettings

ROOT = Path(__file__).resolve().parents[2]
PRINT_HASH = (
    "from caseforge.common.hashing import sha256_hex\n"
    "from caseforge.settings.loader import load_settings\n"
    "s = load_settings('config/caseforge.yaml', environ={}).settings\n"
    "print(sha256_hex(s.model_dump(mode='json')))\n"
)


def test_sets_are_serialized_sorted() -> None:
    settings = GovernanceSettings.model_validate(
        {
            "roles": {"admin": ["reconcile_action", "approve_action", "emergency_stop"]},
            "operators": {"admin-1": ["admin"]},
        }
    )
    assert settings.model_dump(mode="json")["roles"]["admin"] == [
        "approve_action",
        "emergency_stop",
        "reconcile_action",
    ]


@pytest.mark.process
def test_configuration_hash_is_identical_across_processes() -> None:
    hashes = {
        subprocess.run(
            [sys.executable, "-c", PRINT_HASH],
            cwd=ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for seed in ("1", "2", "3")
    }
    assert len(hashes) == 1
