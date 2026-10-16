"""Ledger-guarded execution: committed decisions, crash recovery and failure handling."""

from datetime import UTC, datetime

import pytest

from caseforge.composition import build_container
from caseforge.persistence.records import LedgerStatus
from caseforge.reasoning.fake import FakeReasoner

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1, S3 = "routine-stalled-task", "policy-question"
KEY = "run-0001:send_reminder"
FAULT_POINTS = [
    "act.before_dispatch",
    "act.after_dispatch",
    "act.after_execute",
    "act.after_record",
]


class SimulatedCrash(RuntimeError):
    """Stands in for the process dying at a fault point."""


class CrashOnce:
    def __init__(self, point: str) -> None:
        self.point = point
        self.fired = False

    def __call__(self, point: str) -> None:
        if point == self.point and not self.fired:
            self.fired = True
            raise SimulatedCrash(point)


def _container(config_copy, **kwargs):
    return build_container(config_copy, environ={}, clock=lambda: FIXED, **kwargs)


def test_successful_run_commits_decision_and_ledger(config_copy) -> None:
    with _container(config_copy) as container:
        world = container.open_simulated_case(S1, 7)
        final = container.run_case("run-0001", world.case_id)
        decision = container.store.get_decision("run-0001")
        entry = container.store.get_action(KEY)
    assert (decision.source, decision.action_type) == ("triage", "send_reminder")
    assert (entry.status, entry.attempts, entry.result) == (
        LedgerStatus.SUCCEEDED,
        1,
        {"applied": True},
    )
    assert final["action"]["ledger_status"] == "succeeded"
    assert final["action"]["decision_status"] == "inserted"


def test_supervisor_path_persists_model_and_tool_records(config_copy) -> None:
    script = {
        "supervisor_plan": [
            {"objective": "Decide the request.", "workers": [], "rationale": "Summary suffices."}
        ],
        "supervisor_synthesis": [
            {
                "decision": "escalate",
                "rationale": "A person must decide.",
                "escalation_reason": "Exception requests need human review.",
            }
        ],
    }
    with _container(config_copy, reasoner=FakeReasoner(script)) as container:
        world = container.open_simulated_case(S3, 1)
        container.run_case("run-0001", world.case_id)
        llm_calls = container.store.llm_calls_for_run("run-0001")
        tool_calls = container.store.tool_invocations_for_run("run-0001")
    assert [c.node for c in llm_calls] == ["supervisor_plan", "supervisor_synthesis"]
    assert [t.tool for t in tool_calls] == ["get_case"]


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_crash_at_any_point_executes_exactly_once(config_copy, point: str) -> None:
    with _container(config_copy, fault_injector=CrashOnce(point)) as container:
        world = container.open_simulated_case(S1, 7)
        with pytest.raises(SimulatedCrash):
            container.run_case("run-0001", world.case_id)
        final = container.resume("run-0001")
        entry = container.store.get_action(KEY)
    assert [a.action_id for a in world.ground_truth().actions] == [KEY]
    assert entry.status == LedgerStatus.SUCCEEDED
    assert entry.attempts == 1
    assert final["action"]["ledger_status"] == "succeeded"
    assert final["outcome"]["status"] == "pending"


def test_non_idempotent_executor_marks_unknown_and_does_not_resend(config_copy) -> None:
    with _container(config_copy, fault_injector=CrashOnce("act.after_execute")) as container:
        container.environment.supports_idempotency_keys = False
        world = container.open_simulated_case(S1, 7)
        with pytest.raises(SimulatedCrash):
            container.run_case("run-0001", world.case_id)
        final = container.resume("run-0001")
        entry = container.store.get_action(KEY)
    assert entry.status == LedgerStatus.UNKNOWN
    assert final["action"]["applied"] is None
    assert final["outcome"]["status"] == "unavailable"
    assert len(world.ground_truth().actions) == 1


def test_rerun_with_a_different_decision_uses_the_committed_one(config_copy) -> None:
    with _container(config_copy) as first:
        first.run_case("run-0001", first.open_simulated_case(S3, 1).case_id)
    script = {
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
    with _container(config_copy, reasoner=FakeReasoner(script)) as second:
        world = second.open_simulated_case(S3, 1)
        final = second.run_case("run-0001", world.case_id)
    assert final["decision"]["action_type"] == "grant_policy_exception"
    assert final["action"]["decision_status"] == "conflict"
    assert final["action"]["action_type"] == "escalate_case"
    assert final["action"]["applied"] is False
    assert world.ground_truth().actions == ()


def test_failed_execution_is_recorded_then_retried_on_rerun(config_copy) -> None:
    with _container(config_copy) as container:
        world = container.open_simulated_case(S1, 7)
        original = container.environment.execute
        calls = {"count": 0}

        def flaky(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("external system did not answer")
            return original(**kwargs)

        container.environment.execute = flaky
        first = container.run_case("run-0001", world.case_id)
        failed = container.store.get_action(KEY)
        second = container.run_case("run-0001", world.case_id)
        done = container.store.get_action(KEY)
    assert (failed.status, failed.error) == (LedgerStatus.FAILED, "TimeoutError")
    assert first["outcome"]["status"] == "unavailable"
    assert (done.status, done.attempts) == (LedgerStatus.SUCCEEDED, 2)
    assert second["action"]["applied"] is True
    assert len(world.ground_truth().actions) == 1
