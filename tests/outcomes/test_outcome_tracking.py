"""Decision-outcome records: written on completion, refreshed once outcomes are known."""

from datetime import UTC, datetime, timedelta

from caseforge.composition import build_container
from caseforge.reasoning.fake import FakeReasoner

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1, S3 = "routine-stalled-task", "policy-question"
OBSERVED = {"success", "failure", "unobservable"}
GRANT_SCRIPT = {
    "supervisor_plan": [
        {"objective": "Decide the request.", "workers": [], "rationale": "Summary suffices."}
    ],
    "supervisor_synthesis": [
        {
            "decision": "propose_action",
            "rationale": "Approve the exception.",
            "candidate_actions": ["grant_policy_exception", "escalate_case"],
            "proposal": {"action_type": "grant_policy_exception", "evidence_refs": []},
        }
    ],
}


def _container(config_copy, script=None):
    reasoner = FakeReasoner(script) if script else None
    return build_container(config_copy, environ={}, clock=lambda: FIXED, reasoner=reasoner)


def test_completed_run_writes_a_pending_decision_outcome(config_copy) -> None:
    with _container(config_copy) as container:
        container.run_case("run-0001", container.open_simulated_case(S1, 7).case_id)
        record = container.store.get_decision_outcome("run-0001")
        manifest = container.store.get_manifest("run-0001")
    assert (record.decision_source, record.action_type) == ("triage", "send_reminder")
    assert record.candidate_actions == ("send_reminder",)
    assert (record.ledger_status, record.outcome_status) == ("succeeded", "pending")
    assert record.config_sha256 == manifest.effective_config_sha256
    assert record.llm_calls == 0


def test_refresh_before_resolution_keeps_the_outcome_pending(config_copy) -> None:
    with _container(config_copy) as container:
        container.run_case("run-0001", container.open_simulated_case(S1, 7).case_id)
        updated = container.refresh_outcomes(container.default_as_of() + timedelta(minutes=1))
        record = container.store.get_decision_outcome("run-0001")
    assert updated == 0
    assert record.outcome_status == "pending"


def test_refresh_after_the_horizon_records_the_outcome_and_updates_the_episode(
    config_copy,
) -> None:
    with _container(config_copy) as container:
        container.run_case("run-0001", container.open_simulated_case(S1, 7).case_id)
        later = container.default_as_of() + timedelta(days=3)
        assert container.refresh_outcomes(later) == 1
        assert container.refresh_outcomes(later) == 0  # nothing pending is left
        record = container.store.get_decision_outcome("run-0001")
        (episode,) = container.store.episodes_for_tenant("tenant-demo")
    assert record.outcome_status in OBSERVED
    assert record.horizon_end is not None
    assert episode.outcome_status == record.outcome_status
    assert f"Outcome: {record.outcome_status}." in episode.summary


def test_supervised_and_approved_run_records_candidates_approval_and_spend(config_copy) -> None:
    with _container(config_copy, GRANT_SCRIPT) as container:
        container.run_case("run-0001", container.open_simulated_case(S3, 1).case_id)
        assert container.store.get_decision_outcome("run-0001") is None  # paused for approval
        container.approve("run-0001", actor="approver-1")
        record = container.store.get_decision_outcome("run-0001")
    assert record.decision_source == "supervisor"
    assert record.candidate_actions == ("grant_policy_exception", "escalate_case")
    assert record.approval == "approved"
    assert (record.llm_calls, record.tool_calls) == (2, 1)


def test_rejected_action_is_recorded_as_unavailable_and_not_refreshed(config_copy) -> None:
    with _container(config_copy, GRANT_SCRIPT) as container:
        container.run_case("run-0001", container.open_simulated_case(S3, 1).case_id)
        container.reject("run-0001", actor="approver-1")
        updated = container.refresh_outcomes(container.default_as_of() + timedelta(days=5))
        record = container.store.get_decision_outcome("run-0001")
    assert (record.approval, record.ledger_status) == ("rejected", "not_executed")
    assert record.outcome_status == "unavailable"
    assert updated == 0


def test_halted_run_writes_no_decision_outcome(config_copy) -> None:
    with _container(config_copy) as container:
        container.control_plane.engage_emergency_stop("admin-1", "maintenance")
        container.run_case("run-0001", container.open_simulated_case(S1, 7).case_id)
        record = container.store.get_decision_outcome("run-0001")
    assert record is None
