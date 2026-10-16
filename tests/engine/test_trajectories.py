"""Expected route per scenario family, plus one scripted end-to-end trajectory per new family."""

from datetime import UTC, datetime

import pytest

from caseforge.composition import build_container
from caseforge.reasoning.fake import FakeReasoner

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
APPROVAL = "policy-exceptions#approval-required"
ROUTES = {
    "routine-stalled-task": "fast_path",
    "policy-question": "supervisor",
    "exception-on-late-task": "supervisor",
    "conflicting-records": "supervisor",
}
TIMELINE = {
    "action": "call_tool",
    "rationale": "Read the timeline.",
    "tool": {"tool": "get_timeline", "arguments": {}},
}
APPROVAL_SEARCH = {
    "action": "call_tool",
    "rationale": "Find the exception procedure.",
    "tool": {
        "tool": "search_policies",
        "arguments": {"query": "who must approve a policy exception"},
    },
}
APPROVAL_FINISH = {
    "action": "finish",
    "rationale": "The procedure is clear.",
    "findings": {
        "summary": "Exceptions need an authorized approver.",
        "requirements": [{"statement": "An approver must approve.", "source_ids": [APPROVAL]}],
    },
}


def _evidence_finish(event_id: str) -> dict:
    return {
        "action": "finish",
        "rationale": "The facts are sufficient.",
        "findings": {
            "summary": "The relevant event was found.",
            "facts": [{"statement": "The event is on record.", "source_ids": [event_id]}],
        },
    }


def _plan(**questions: str) -> dict:
    plan = {
        "objective": "Resolve the case.",
        "workers": list(questions),
        "rationale": "Select what the case needs.",
    }
    plan.update({f"{worker}_question": q for worker, q in questions.items()})
    return plan


def _propose(action: str, refs: list[str]) -> dict:
    return {
        "decision": "propose_action",
        "rationale": "The findings support this action.",
        "candidate_actions": [action, "escalate_case"],
        "proposal": {"action_type": action, "evidence_refs": refs},
    }


def _run(config_copy, family_id: str, seed: int, script: dict):
    with build_container(
        config_copy, environ={}, reasoner=FakeReasoner(script), clock=lambda: FIXED
    ) as container:
        world = container.open_simulated_case(family_id, seed)
        final = container.run_case("run-0001", world.case_id)
    return final, world


def _workers_run(final: dict) -> list[str]:
    return sorted(step["worker"] for step in final["trace"] if step["node"] == "run_worker")


@pytest.mark.parametrize(("family_id", "route"), sorted(ROUTES.items()))
def test_triage_routes_each_family_as_designed(config_copy, family_id: str, route: str) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED) as container:
        for seed in range(10):
            world = container.open_simulated_case(family_id, seed)
            final = container.run_case(f"run-{family_id}-{seed}", world.case_id)
            assert final["triage"]["route"] == route, (family_id, seed)


def test_policy_question_uses_policy_worker_only(config_copy) -> None:
    script = {
        "supervisor_plan": [_plan(policy="Who must approve a policy exception?")],
        "policy": [APPROVAL_SEARCH, APPROVAL_FINISH],
        "supervisor_synthesis": [_propose("grant_policy_exception", [APPROVAL])],
    }
    final, world = _run(config_copy, "policy-question", 1, script)
    assert _workers_run(final) == ["policy"]
    plan_step = next(s for s in final["trace"] if s["node"] == "supervisor_plan")
    assert plan_step["skipped"] == ["evidence"]
    assert final["decision"]["action_type"] == "grant_policy_exception"
    assert [a.action_type for a in world.ground_truth().actions] == ["grant_policy_exception"]


def test_exception_on_late_task_uses_both_workers(config_copy) -> None:
    late = "sim:elt-0002-task_main_late"
    script = {
        "supervisor_plan": [
            _plan(evidence="Why is the task late?", policy="Who must approve a policy exception?")
        ],
        "evidence": [TIMELINE, _evidence_finish(late)],
        "policy": [APPROVAL_SEARCH, APPROVAL_FINISH],
        "supervisor_synthesis": [_propose("reassign_task", [late, APPROVAL])],
    }
    final, world = _run(config_copy, "exception-on-late-task", 2, script)
    assert _workers_run(final) == ["evidence", "policy"]
    assert {r["status"] for r in final["worker_results"]} == {"completed"}
    assert final["decision"]["source"] == "supervisor"
    assert [a.action_type for a in world.ground_truth().actions] == ["reassign_task"]


def test_conflicting_records_clarify_then_escalate(config_copy) -> None:
    signed = "sim:cr-0003-doc_in_signed"
    reason = "The receipt records conflict."
    script = {
        "supervisor_plan": [_plan(evidence="Which document was received?")],
        "evidence": [TIMELINE, _evidence_finish(signed)] * 2,
        "supervisor_synthesis": [
            {
                "decision": "clarify",
                "rationale": "The two receipts disagree.",
                "clarification": {"worker": "evidence", "question": "Which receipt is current?"},
            },
            {"decision": "escalate", "rationale": "Still unresolved.", "escalation_reason": reason},
        ],
    }
    final, world = _run(config_copy, "conflicting-records", 3, script)
    assert [r["round"] for r in final["worker_results"]] == [0, 1]
    assert final["decision"] == {
        "source": "escalation",
        "action_type": "escalate_case",
        "reason": reason,
    }
    assert [a.action_type for a in world.ground_truth().actions] == ["escalate_case"]
