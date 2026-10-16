"""Supervisor tests: plan and synthesis contracts plus code-enforced decision rules."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from caseforge.agents.contracts import SupervisorPlan, Synthesis
from caseforge.agents.supervisor import Supervisor, SupervisorStatus
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.models import ModelSpec
from caseforge.reasoning.prompts import PromptRegistry
from caseforge.reasoning.structured import StructuredCaller

ROOT = Path(__file__).resolve().parents[2]
FIXED = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
ALLOWED = frozenset({"send_reminder", "reassign_task", "escalate_case"})
SUMMARY = {"case_id": "case-0001", "event_count": 3, "event_types": {"task.delayed": 1}}
PLAN = {
    "objective": "Get the stalled task completed.",
    "workers": ["evidence"],
    "evidence_question": "Why is the task late?",
    "rationale": "Only facts are needed.",
}
WORKER_RESULTS = [
    {
        "worker": "evidence",
        "status": "completed",
        "findings": {
            "summary": "The task is overdue.",
            "facts": [{"statement": "Due time passed.", "source_ids": ["evt-0001"]}],
        },
        "error": None,
    }
]


def _propose(action: str = "send_reminder", refs=("evt-0001",), candidates=None) -> dict:
    return {
        "decision": "propose_action",
        "rationale": "A reminder fits the facts.",
        "candidate_actions": list(candidates or [action, "reassign_task"]),
        "proposal": {"action_type": action, "evidence_refs": list(refs)},
    }


@pytest.fixture(scope="module")
def prompts() -> PromptRegistry:
    return PromptRegistry.from_directory(ROOT / "config" / "prompts")


def _supervisor(prompts, script: dict, max_rounds: int = 1) -> Supervisor:
    caller = StructuredCaller(
        FakeReasoner(script), prompts, ModelSpec(provider="fake", model="m"), clock=lambda: FIXED
    )
    return Supervisor(
        caller=caller,
        plan_version=1,
        synthesis_version=1,
        allowed_actions=ALLOWED,
        max_clarification_rounds=max_rounds,
    )


def _synthesize(supervisor, round_index: int = 0, worker_results=WORKER_RESULTS):
    return supervisor.synthesize(
        run_id="run-0001",
        case_id="case-0001",
        case_summary=SUMMARY,
        worker_results=worker_results,
        round_index=round_index,
    )


def test_plan_selects_workers_and_records_the_call(prompts) -> None:
    result = _supervisor(prompts, {"supervisor_plan": [PLAN]}).plan(
        run_id="run-0001", case_id="case-0001", case_summary=SUMMARY
    )
    assert result.status == SupervisorStatus.OK
    assert result.output["workers"] == ["evidence"]
    assert result.llm_call.call_id == "run-0001:supervisor_plan:0"


def test_plan_with_inconsistent_questions_fails(prompts) -> None:
    bad = {**PLAN, "evidence_question": None}
    result = _supervisor(prompts, {"supervisor_plan": [bad]}).plan(
        run_id="run-0001", case_id="case-0001", case_summary=SUMMARY
    )
    assert result.status == SupervisorStatus.FAILED
    assert result.llm_call.status == "invalid_output"


def test_model_error_fails_without_raising(prompts) -> None:
    result = _supervisor(prompts, {}).plan(
        run_id="run-0001", case_id="case-0001", case_summary=SUMMARY
    )
    assert result.status == SupervisorStatus.FAILED


def test_grounded_proposal_is_accepted(prompts) -> None:
    result = _synthesize(_supervisor(prompts, {"supervisor_synthesis": [_propose()]}))
    assert result.status == SupervisorStatus.OK
    assert result.output["proposal"]["action_type"] == "send_reminder"
    assert result.llm_call.call_id == "run-0001:supervisor_synthesis:0"


def test_proposal_citing_unfound_evidence_is_invalid(prompts) -> None:
    supervisor = _supervisor(prompts, {"supervisor_synthesis": [_propose(refs=["evt-9999"])]})
    result = _synthesize(supervisor)
    assert result.status == SupervisorStatus.INVALID
    assert "evt-9999" in result.error


def test_action_outside_allowed_list_is_invalid(prompts) -> None:
    supervisor = _supervisor(
        prompts, {"supervisor_synthesis": [_propose(action="grant_policy_exception")]}
    )
    result = _synthesize(supervisor)
    assert result.status == SupervisorStatus.INVALID
    assert "grant_policy_exception" in result.error


def test_clarification_allowed_while_rounds_remain(prompts) -> None:
    clarify = {
        "decision": "clarify",
        "rationale": "The owner's other work is unknown.",
        "clarification": {
            "worker": "evidence",
            "question": "Does the owner have other late tasks?",
        },
    }
    supervisor = _supervisor(prompts, {"supervisor_synthesis": [clarify, clarify]})
    assert _synthesize(supervisor, round_index=0).status == SupervisorStatus.OK
    exhausted = _synthesize(supervisor, round_index=1)
    assert exhausted.status == SupervisorStatus.INVALID
    assert exhausted.error == "no clarification rounds remain"


def test_escalation_is_accepted(prompts) -> None:
    escalate = {
        "decision": "escalate",
        "rationale": "The evidence conflicts.",
        "escalation_reason": "Two sources disagree about the due time.",
    }
    result = _synthesize(_supervisor(prompts, {"supervisor_synthesis": [escalate]}))
    assert result.status == SupervisorStatus.OK
    assert result.output["decision"] == "escalate"


@pytest.mark.parametrize(
    "decision",
    [
        {"decision": "propose_action", "rationale": "x"},
        {"decision": "clarify", "rationale": "x", "escalation_reason": "y"},
        {
            "decision": "propose_action",
            "rationale": "x",
            "candidate_actions": ["reassign_task"],
            "proposal": {"action_type": "send_reminder"},
        },
    ],
)
def test_synthesis_contract_rejects_inconsistent_decisions(decision) -> None:
    with pytest.raises(ValidationError):
        Synthesis.model_validate(decision)


def test_plan_contract_rejects_duplicate_workers() -> None:
    duplicated = {
        **PLAN,
        "workers": ["evidence", "evidence"],
    }
    with pytest.raises(ValidationError, match="unique"):
        SupervisorPlan.model_validate(duplicated)


def test_shipped_supervisor_prompts_match_contracts(prompts) -> None:
    plan = prompts.get("supervisor_plan", 1)
    synthesis = prompts.get("supervisor_synthesis", 1)
    assert (plan.output_schema, synthesis.output_schema) == ("SupervisorPlan", "Synthesis")
    assert plan.variables() == {"case_id", "case_summary"}
    assert synthesis.variables() == {
        "case_id",
        "case_summary",
        "worker_results",
        "allowed_actions",
        "clarifications_remaining",
    }
