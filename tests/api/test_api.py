"""Operator API: isolated runs, approvals, emergency stop, evaluation, replayed demos."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseforge.api.app import create_app
from caseforge.api.service import DemoService
from caseforge.reasoning.fake import FakeReasoner

ROOT = Path(__file__).resolve().parents[2]
FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1_RUN = {"family": "routine-stalled-task", "seed": 7, "mode": "deterministic"}
GRANT = {
    "single_agent": [
        {
            "action": "decide",
            "rationale": "Grant.",
            "decision": {
                "decision": "propose_action",
                "rationale": "Justified.",
                "candidate_actions": ["grant_policy_exception", "escalate_case"],
                "proposal": {"action_type": "grant_policy_exception", "evidence_refs": []},
            },
        }
    ]
}


def _client(config_copy, script=None) -> TestClient:
    factory = (lambda mode: FakeReasoner(script)) if script is not None else None
    service = DemoService(config_copy, reasoner_factory=factory, clock=lambda: FIXED)
    return TestClient(create_app(service=service))


def test_health_and_demo_cases(config_copy) -> None:
    client = _client(config_copy)
    assert client.get("/health").json() == {"status": "ok"}
    keys = [case["key"] for case in client.get("/cases").json()]
    assert "policy-question/001/none" in keys
    assert all(key.endswith("/none") for key in keys)
    assert client.get("/models").json() == ["claude-sonnet-5-5", "claude-haiku-5-5"]


def test_rules_only_run_completes(config_copy) -> None:
    client = _client(config_copy)
    run = client.post("/runs", json=S1_RUN).json()
    assert (run["status"], run["decision"]["source"]) == ("completed", "triage")
    assert run["action"]["ledger_status"] == "succeeded"
    assert client.get(f"/runs/{run['run_id']}").json()["status"] == "completed"


def test_approval_is_role_checked(config_copy) -> None:
    client = _client(config_copy, GRANT)
    run = client.post(
        "/runs", json={"family": "policy-question", "seed": 1, "mode": "single_agent"}
    ).json()
    assert run["status"] == "awaiting_approval" and run["pending_approval"] is not None
    denied = client.post(f"/runs/{run['run_id']}/approve", json={"actor": "viewer-1"})
    assert denied.status_code == 403
    done = client.post(
        f"/runs/{run['run_id']}/approve", json={"actor": "approver-1", "note": "ok"}
    ).json()
    assert done["status"] == "completed"
    assert done["action"]["action_type"] == "grant_policy_exception"


def test_emergency_stop_halts_runs_until_released(config_copy) -> None:
    client = _client(config_copy)
    stop = {"actor": "viewer-1", "reason": "x"}
    assert client.post("/governance/emergency-stop", json=stop).status_code == 403
    engaged = client.post(
        "/governance/emergency-stop", json={"actor": "admin-1", "reason": "maintenance"}
    ).json()
    assert engaged["emergency_stop"] is not None
    run = client.post("/runs", json=S1_RUN).json()
    assert (run["status"], run["action"]) == ("halted", None)
    client.post("/governance/emergency-stop/release", json={"actor": "admin-1"})
    assert client.post(f"/runs/{run['run_id']}/resume").json()["status"] == "completed"
    audit = [entry["action"] for entry in client.get("/governance").json()["audit"]]
    assert "run.halted" in audit


def test_errors_map_to_http_status(config_copy) -> None:
    client = _client(config_copy)
    assert client.get("/runs/deterministic-nope-000-abcdef").status_code == 404
    assert client.get("/runs/NOT_A_VALID_ID").status_code == 404
    bad = client.post("/runs", json={"family": "ghost", "seed": 1, "mode": "deterministic"})
    assert bad.status_code == 400


def test_evaluation_lists_committed_reports(config_copy) -> None:
    results = config_copy.parent.parent / "eval_results"
    results.mkdir(exist_ok=True)
    report = {"label": "r", "mode": "deterministic", "cases": [], "summary": {"cases": 0}}
    (results / "r.json").write_text(json.dumps(report), encoding="utf-8")
    body = _client(config_copy).get("/evaluation").json()
    assert [r["label"] for r in body["reports"]] == ["r"]


@pytest.mark.parametrize(
    ("model", "label"),
    [
        ("claude-sonnet-5-5", "bench-v1-sonnet-single"),
        ("claude-haiku-5-5", "bench-v1-haiku-single"),
    ],
)
def test_demo_replays_the_recorded_benchmark_decision(config_copy, model: str, label: str) -> None:
    cassettes = config_copy.parent.parent / "eval_results" / "cassettes"
    cassettes.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        ROOT / "eval_results" / "cassettes" / f"{label}.jsonl", cassettes / f"{label}.jsonl"
    )
    report = json.loads((ROOT / "eval_results" / f"{label}.json").read_text("utf-8"))
    expected = next(c for c in report["cases"] if c["key"] == "missing-document/001/none")

    run = (
        _client(config_copy)
        .post(
            "/runs",
            json={"family": "missing-document", "seed": 1, "mode": "single_agent", "model": model},
        )
        .json()
    )
    assert run["model"] == model
    assert run["decision_outcome"]["action_type"] == expected["action_type"]
    assert run["usage"]["llm_calls"] == expected["llm_calls"]
