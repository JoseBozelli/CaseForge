"""Approval interrupt: pause before configured actions, approve or reject, survive restarts."""

from datetime import UTC, datetime

import pytest

from caseforge.common.errors import ConfigError
from caseforge.composition import build_container
from caseforge.reasoning.fake import FakeReasoner

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S3 = "policy-question"
KEY = "run-0001:grant_policy_exception"
PLAN = {
    "objective": "Decide the exception request.",
    "workers": [],
    "rationale": "Summary suffices.",
}
GRANT = {
    "decision": "propose_action",
    "rationale": "Approve the exception.",
    "candidate_actions": ["grant_policy_exception"],
    "proposal": {"action_type": "grant_policy_exception", "evidence_refs": []},
}


def _container(config_copy, scripted: bool = True):
    reasoner = FakeReasoner({"supervisor_plan": [PLAN], "supervisor_synthesis": [GRANT]})
    return build_container(
        config_copy, environ={}, clock=lambda: FIXED, reasoner=reasoner if scripted else None
    )


def test_action_requiring_approval_pauses_before_anything_is_executed(config_copy) -> None:
    with _container(config_copy) as container:
        world = container.open_simulated_case(S3, 1)
        container.run_case("run-0001", world.case_id)
        request = container.pending_approval("run-0001")
        assert container.store.get_decision("run-0001") is None
        assert container.store.get_action(KEY) is None
    assert request["action_type"] == "grant_policy_exception"
    assert request["source"] == "supervisor"
    assert world.ground_truth().actions == ()


def test_approval_resumes_and_executes_once(config_copy) -> None:
    with _container(config_copy) as container:
        world = container.open_simulated_case(S3, 1)
        container.run_case("run-0001", world.case_id)
        final = container.approve("run-0001", actor="approver-1", note="Justified by the facts.")
        approvals = container.store.approvals_for_run("run-0001")
        assert container.pending_approval("run-0001") is None
    assert final["action"]["ledger_status"] == "succeeded"
    assert [a.action_id for a in world.ground_truth().actions] == [KEY]
    assert [(a.decision, a.actor) for a in approvals] == [("approved", "approver-1")]


def test_rejection_records_the_answer_and_executes_nothing(config_copy) -> None:
    with _container(config_copy) as container:
        world = container.open_simulated_case(S3, 1)
        container.run_case("run-0001", world.case_id)
        final = container.reject("run-0001", actor="approver-1", note="Not justified.")
        approvals = container.store.approvals_for_run("run-0001")
        entry = container.store.get_action(KEY)
    assert final["action"]["ledger_status"] == "not_executed"
    assert final["action"]["reason"] == "approval rejected"
    assert final["outcome"]["status"] == "unavailable"
    assert entry is None
    assert world.ground_truth().actions == ()
    assert [a.decision for a in approvals] == ["rejected"]


def test_paused_approval_survives_a_restart(config_copy) -> None:
    with _container(config_copy) as first:
        first.run_case("run-0001", first.open_simulated_case(S3, 1).case_id)
    with _container(config_copy, scripted=False) as second:
        assert second.pending_approval("run-0001")["action_type"] == "grant_policy_exception"
        final = second.approve("run-0001", actor="approver-1")
        world = second.open_simulated_case(S3, 1)
    assert final["action"]["ledger_status"] == "succeeded"
    assert [a.action_id for a in world.ground_truth().actions] == [KEY]


def test_answering_a_run_that_is_not_waiting_is_refused(config_copy) -> None:
    with (
        _container(config_copy) as container,
        pytest.raises(ValueError, match="not awaiting approval"),
    ):
        container.approve("run-9999", actor="approver-1")


def test_approval_required_actions_must_be_allowed(config_copy) -> None:
    text = config_copy.read_text(encoding="utf-8")
    config_copy.write_text(
        text.replace(
            "approval_required: [grant_policy_exception]",
            "approval_required: [grant_policy_exception, shred_case]",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="approval_required"):
        build_container(config_copy, environ={})
