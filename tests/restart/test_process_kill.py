"""Process-kill restart tests: a separate process is stopped abruptly, then a new one resumes.

These assertions use only durable state: checkpoints, the record store and ledger, and the
simulated world's own log, each read by a fresh process.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.process

DRIVER = Path(__file__).with_name("driver.py")
KILLED = 86
S1, S3 = "routine-stalled-task", "policy-question"
FAULT_POINTS = [
    "act.before_dispatch",
    "act.after_dispatch",
    "act.after_execute",
    "act.after_record",
]
SCRIPT = {
    "supervisor_plan": [
        {"objective": "Decide the request.", "workers": [], "rationale": "Summary suffices."}
    ],
    "supervisor_synthesis": [
        {
            "decision": "propose_action",
            "rationale": "Approve the exception.",
            "candidate_actions": ["grant_policy_exception"],
            "proposal": {"action_type": "grant_policy_exception", "evidence_refs": []},
        }
    ],
}
SUCCEEDED_ONCE = {"status": "succeeded", "attempts": 1}


def _drive(command: str, config_copy: Path, family: str, seed: int, *extra: str):
    return subprocess.run(
        [
            sys.executable,
            str(DRIVER),
            command,
            "--config",
            str(config_copy),
            "--run-id",
            "run-0001",
            "--family",
            family,
            "--seed",
            str(seed),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _summary(process) -> dict:
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout.strip().splitlines()[-1])


@pytest.fixture
def script_path(tmp_path: Path) -> Path:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(SCRIPT), encoding="utf-8")
    return path


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_killed_process_recovers_with_exactly_one_action(config_copy, point: str) -> None:
    killed = _drive("run", config_copy, S1, 7, "--kill-at", point)
    assert killed.returncode == KILLED, killed.stderr
    summary = _summary(_drive("resume", config_copy, S1, 7))
    assert summary["world_actions"] == ["run-0001:send_reminder"]
    assert summary["ledger"] == SUCCEEDED_ONCE


def test_stopped_while_awaiting_approval_resumes_in_a_new_process(config_copy, script_path) -> None:
    paused = _summary(_drive("run", config_copy, S3, 1, "--script", str(script_path)))
    assert paused["pending_approval"]["action_type"] == "grant_policy_exception"
    assert paused["world_actions"] == []
    approved = _summary(_drive("approve", config_copy, S3, 1))
    assert approved["world_actions"] == ["run-0001:grant_policy_exception"]
    assert approved["ledger"] == SUCCEEDED_ONCE


def test_killed_during_approved_execution_recovers(config_copy, script_path) -> None:
    _summary(_drive("run", config_copy, S3, 1, "--script", str(script_path)))
    killed = _drive("approve", config_copy, S3, 1, "--kill-at", "act.after_execute")
    assert killed.returncode == KILLED, killed.stderr
    summary = _summary(_drive("resume", config_copy, S3, 1))
    assert summary["world_actions"] == ["run-0001:grant_policy_exception"]
    assert summary["ledger"] == SUCCEEDED_ONCE
