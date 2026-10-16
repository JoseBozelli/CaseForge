"""Hierarchical graph tests: fast path, parallel workers, clarification and escalation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.composition import build_container
from caseforge.reasoning.fake import FakeReasoner
from caseforge.simulation.provider import TemplateSimulationProvider
from caseforge.simulation.spec import load_families

ROOT = Path(__file__).resolve().parents[2]
FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
AS_OF = START + timedelta(minutes=1560)
S1, S2 = "routine-stalled-task", "missing-document"
CHUNK = "document-requests#wrong-document-received"
TIMELINE = {
    "action": "call_tool",
    "rationale": "Read the timeline.",
    "tool": {"tool": "get_timeline", "arguments": {}},
}
POLICY_SEARCH = {
    "action": "call_tool",
    "rationale": "Search the procedures.",
    "tool": {"tool": "search_policies", "arguments": {"query": "wrong document type uploaded"}},
}
POLICY_FINISH = {
    "action": "finish",
    "rationale": "The requirement is clear.",
    "findings": {
        "summary": "A wrong document must be requested again.",
        "requirements": [{"statement": "Request the correct type.", "source_ids": [CHUNK]}],
    },
}
ESCALATE = {
    "decision": "escalate",
    "rationale": "Not enough to act on.",
    "escalation_reason": "The case needs a human decision.",
}


@pytest.fixture(scope="module")
def seed() -> int:
    """First missing-document seed whose wrong document has arrived (no triage rule matches)."""
    provider = TemplateSimulationProvider(
        load_families(ROOT / "config" / "simulation" / "families")
    )
    for candidate in range(50):
        world = provider.create(S2, candidate, tenant_id="tenant-demo", start_at=START)
        if any(e.source_type == "doc.in" for e in world.observable_view(AS_OF).events):
            return candidate
    raise AssertionError("no suitable seed in 0-49")


def _event_id(seed: int) -> str:
    return f"sim:mdoc-{seed:04d}-wrong_doc"


def _evidence_finish(event_id: str) -> dict:
    return {
        "action": "finish",
        "rationale": "The facts are sufficient.",
        "findings": {
            "summary": "A document of the wrong type arrived.",
            "facts": [{"statement": "A different document arrived.", "source_ids": [event_id]}],
        },
    }


def _plan(*workers: str) -> dict:
    plan = {
        "objective": "Resolve the document problem.",
        "workers": list(workers),
        "rationale": "Select what the case needs.",
    }
    for worker in workers:
        plan[f"{worker}_question"] = f"What does the {worker} worker find?"
    return plan


def _propose(action: str, refs: list[str]) -> dict:
    return {
        "decision": "propose_action",
        "rationale": "The findings support this action.",
        "candidate_actions": [action, "escalate_case"],
        "proposal": {"action_type": action, "evidence_refs": refs},
    }


def _clarify() -> dict:
    return {
        "decision": "clarify",
        "rationale": "One fact is missing.",
        "clarification": {"worker": "evidence", "question": "Did a second document arrive?"},
    }


def _run(config_copy, script: dict, seed: int, environ=None, repeat: int = 1):
    reasoner = FakeReasoner(script)
    with build_container(
        config_copy, environ=environ or {}, reasoner=reasoner, clock=lambda: FIXED
    ) as container:
        world = container.open_simulated_case(S2, seed)
        final = None
        for _ in range(repeat):
            final = container.run_case("run-0001", world.case_id)
    return final, world


def _nodes(final: dict) -> list[str]:
    return [step["node"] for step in final["trace"]]


def test_routine_case_takes_fast_path(config_copy) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED) as container:
        world = container.open_simulated_case(S1, 7)
        final = container.run_case("run-0001", world.case_id)
    assert _nodes(final) == ["intake", "triage", "act", "observe"]
    assert final["decision"]["source"] == "triage"
    assert final["llm_calls"] == []


def test_unmatched_case_runs_both_workers_in_parallel(config_copy, seed) -> None:
    event_id = _event_id(seed)
    script = {
        "supervisor_plan": [_plan("evidence", "policy")],
        "evidence": [TIMELINE, _evidence_finish(event_id)],
        "policy": [POLICY_SEARCH, POLICY_FINISH],
        "supervisor_synthesis": [_propose("request_document", [event_id, CHUNK])],
    }
    final, world = _run(config_copy, script, seed)
    nodes = _nodes(final)
    assert nodes[:3] == ["intake", "triage", "supervisor_plan"]
    assert sorted(s["worker"] for s in final["trace"] if s["node"] == "run_worker") == [
        "evidence",
        "policy",
    ]
    assert nodes[-3:] == ["synthesize", "act", "observe"]
    assert {r["status"] for r in final["worker_results"]} == {"completed"}
    assert final["decision"] == {
        "source": "supervisor",
        "action_type": "request_document",
        "evidence_refs": [event_id, CHUNK],
    }
    assert (len(final["llm_calls"]), len(final["tool_calls"])) == (6, 3)
    assert [a.action_type for a in world.ground_truth().actions] == ["request_document"]


def test_plan_without_workers_goes_straight_to_synthesis(config_copy, seed) -> None:
    script = {"supervisor_plan": [_plan()], "supervisor_synthesis": [ESCALATE]}
    final, _ = _run(config_copy, script, seed)
    assert _nodes(final) == [
        "intake",
        "triage",
        "supervisor_plan",
        "synthesize",
        "escalate",
        "act",
        "observe",
    ]
    plan_step = next(s for s in final["trace"] if s["node"] == "supervisor_plan")
    assert plan_step["skipped"] == ["evidence", "policy"]
    assert final["decision"]["action_type"] == "escalate_case"


def test_clarification_round_runs_one_more_worker(config_copy, seed) -> None:
    event_id = _event_id(seed)
    finish = _evidence_finish(event_id)
    script = {
        "supervisor_plan": [_plan("evidence")],
        "evidence": [TIMELINE, finish, TIMELINE, finish],
        "supervisor_synthesis": [_clarify(), _propose("request_document", [event_id])],
    }
    final, _ = _run(config_copy, script, seed)
    assert [r["round"] for r in final["worker_results"]] == [0, 1]
    assert final["synthesis_round"] == 2
    assert final["decision"]["source"] == "supervisor"
    call_ids = [c["call_id"] for c in final["llm_calls"]]
    assert len(call_ids) == len(set(call_ids))


def test_exhausted_clarification_escalates(config_copy, seed) -> None:
    finish = _evidence_finish(_event_id(seed))
    script = {
        "supervisor_plan": [_plan("evidence")],
        "evidence": [TIMELINE, finish, TIMELINE, finish],
        "supervisor_synthesis": [_clarify(), _clarify()],
    }
    final, _ = _run(config_copy, script, seed)
    assert final["decision"]["source"] == "escalation"
    assert "no clarification rounds remain" in final["decision"]["reason"]


def test_ungrounded_proposal_escalates(config_copy, seed) -> None:
    script = {
        "supervisor_plan": [_plan("evidence")],
        "evidence": [TIMELINE, _evidence_finish(_event_id(seed))],
        "supervisor_synthesis": [_propose("request_document", ["evt-unknown"])],
    }
    final, world = _run(config_copy, script, seed)
    assert final["decision"]["source"] == "escalation"
    assert "not found by any worker" in final["decision"]["reason"]
    assert [a.action_type for a in world.ground_truth().actions] == ["escalate_case"]


def test_model_failure_escalates_safely(config_copy, seed) -> None:
    final, world = _run(config_copy, {}, seed)
    assert "escalate" in _nodes(final)
    assert final["decision"]["reason"].startswith("plan failed")
    assert [a.action_type for a in world.ground_truth().actions] == ["escalate_case"]


def test_deterministic_mode_never_calls_agents(config_copy, seed) -> None:
    final, _ = _run(config_copy, {}, seed, environ={"CASEFORGE__ENGINE__MODE": "deterministic"})
    assert _nodes(final) == ["intake", "triage", "act", "observe"]
    assert final["decision"] == {
        "source": "triage",
        "action_type": "escalate_case",
        "rule_id": None,
    }


def test_rerun_resets_per_run_fields(config_copy, seed) -> None:
    event_id = _event_id(seed)
    script = {
        "supervisor_plan": [_plan("evidence", "policy")] * 2,
        "evidence": [TIMELINE, _evidence_finish(event_id)] * 2,
        "policy": [POLICY_SEARCH, POLICY_FINISH] * 2,
        "supervisor_synthesis": [_propose("request_document", [event_id, CHUNK])] * 2,
    }
    final, _ = _run(config_copy, script, seed, repeat=2)
    assert len(final["worker_results"]) == 2
    assert len(final["llm_calls"]) == 6
    assert final["intake"]["duplicates"] > 0


def test_escalation_action_must_be_allowed(config_copy) -> None:
    text = config_copy.read_text(encoding="utf-8")
    config_copy.write_text(
        text.replace("escalation_action: escalate_case", "escalation_action: shred_case", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="escalation_action"):
        build_container(config_copy, environ={})
