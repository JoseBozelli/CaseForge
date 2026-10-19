"""Single-agent mode: same contracts, same governance, same execution path."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caseforge.agents.contracts import SingleAgentStep
from caseforge.composition import build_container
from caseforge.reasoning.fake import FakeReasoner

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
SINGLE = {"CASEFORGE__ENGINE__MODE": "single_agent"}
S1, S3 = "routine-stalled-task", "policy-question"
READ_CASE = {"action": "call_tool", "rationale": "Read the case.", "tool": {"tool": "get_case"}}


def _decide(action: str, refs: list[str], candidates: list[str] | None = None) -> dict:
    return {
        "action": "decide",
        "rationale": "Decide.",
        "decision": {
            "decision": "propose_action",
            "rationale": "Fits the case.",
            "candidate_actions": candidates or [action, "escalate_case"],
            "proposal": {"action_type": action, "evidence_refs": refs},
        },
    }


def _run(config_copy, script: dict | None, family: str, seed: int, environ=None):
    container = build_container(
        config_copy,
        environ={**SINGLE, **(environ or {})},
        clock=lambda: FIXED,
        reasoner=FakeReasoner(script or {}),
    )
    world = container.open_simulated_case(family, seed)
    final = container.run_case("run-0001", world.case_id)
    return container, world, final


def test_single_agent_decision_goes_through_approval_and_the_ledger(config_copy) -> None:
    script = {"single_agent": [READ_CASE, _decide("grant_policy_exception", [])]}
    container, world, final = _run(config_copy, script, S3, 1)
    with container:
        assert final["triage"]["route"] == "single_agent"
        assert container.pending_approval("run-0001") is not None  # approval still required
        done = container.approve("run-0001", actor="approver-1")
        agents = {c["agent"] for c in done["tool_calls"]}
    assert done["action"]["source"] == "single_agent"
    assert done["action"]["ledger_status"] == "succeeded"
    assert [a.action_type for a in world.ground_truth().actions] == ["grant_policy_exception"]
    assert agents == {"single"}


def test_unobserved_evidence_leads_to_escalation(config_copy) -> None:
    script = {"single_agent": [_decide("reassign_task", ["evt-invented"])]}
    container, world, final = _run(config_copy, script, S3, 1)
    container.close()
    assert final["decision"]["source"] == "escalation"
    assert "evidence refs not observed" in final["decision"]["reason"]
    assert [a.action_type for a in world.ground_truth().actions] == ["escalate_case"]


def test_disallowed_action_leads_to_escalation(config_copy) -> None:
    script = {"single_agent": [_decide("delete_records", [], ["delete_records"])]}
    container, _, final = _run(config_copy, script, S3, 1)
    container.close()
    assert final["decision"]["source"] == "escalation"
    assert "actions not allowed" in final["decision"]["reason"]


def test_exhausted_steps_lead_to_escalation(config_copy) -> None:
    script = {"single_agent": [READ_CASE, READ_CASE]}
    environ = {"CASEFORGE__AGENTS__SINGLE__MAX_STEPS": "2"}
    container, _, final = _run(config_copy, script, S3, 1, environ)
    container.close()
    assert final["decision"]["source"] == "escalation"
    assert "step budget exhausted" in final["decision"]["reason"]


def test_model_failure_leads_to_escalation(config_copy) -> None:
    container, world, final = _run(config_copy, None, S3, 1)
    container.close()
    assert final["decision"]["source"] == "escalation"
    assert [a.action_type for a in world.ground_truth().actions] == ["escalate_case"]


def test_rules_fast_path_is_unchanged_in_single_agent_mode(config_copy) -> None:
    container, _, final = _run(config_copy, None, S1, 7)
    with container:
        usage = container.run_usage("run-0001")
    assert final["triage"]["route"] == "fast_path"
    assert usage.llm_calls == 0


def test_single_agent_cannot_ask_for_clarification() -> None:
    with pytest.raises(ValidationError, match="clarification"):
        SingleAgentStep.model_validate(
            {
                "action": "decide",
                "rationale": "Ask.",
                "decision": {
                    "decision": "clarify",
                    "rationale": "Need more.",
                    "clarification": {"worker": "evidence", "question": "What happened?"},
                },
            }
        )
