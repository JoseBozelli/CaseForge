"""End-to-end tests of the thin case graph through the composition root."""

from datetime import UTC, datetime

import pytest

from caseforge.composition import build_container
from caseforge.persistence.ports import RecordConflictError

FIXED_NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1, S2 = "routine-stalled-task", "missing-document"


@pytest.fixture
def container(config_copy):
    with build_container(config_copy, environ={}, clock=lambda: FIXED_NOW) as built:
        yield built


def test_s1_case_runs_end_to_end(container) -> None:
    world = container.open_simulated_case(S1, 7)
    final = container.run_case("run-0001", world.case_id)
    assert [step["node"] for step in final["trace"]] == ["intake", "triage", "act", "observe"]
    assert final["intake"] == {"inserted": 4, "duplicates": 0, "conflicts": 0, "rejected": 0}
    assert final["triage"] == {
        "rule_id": "stalled-task-reminder",
        "action_type": "send_reminder",
        "event_types": ["case.created", "task.delayed", "task.requested"],
        "route": "fast_path",
    }
    assert final["action"]["applied"] is True
    assert final["outcome"]["status"] == "pending"
    assert container.store.get_manifest("run-0001") is not None
    assert [a.action_id for a in world.ground_truth().actions] == ["run-0001:send_reminder"]


def test_rerunning_same_run_is_idempotent(container) -> None:
    world = container.open_simulated_case(S1, 7)
    container.run_case("run-0001", world.case_id)
    final = container.run_case("run-0001", world.case_id)
    assert final["intake"]["inserted"] == 0
    assert final["intake"]["duplicates"] == 4
    assert final["action"]["applied"] is False
    assert len(world.ground_truth().actions) == 1
    assert len(final["trace"]) == 8


def test_completed_run_survives_reopen(config_copy) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED_NOW) as first:
        first.run_case("run-0001", first.open_simulated_case(S1, 7).case_id)
    with build_container(config_copy, environ={}, clock=lambda: FIXED_NOW) as reopened:
        state = reopened.graph.get_state({"configurable": {"thread_id": "run-0001"}})
        assert state.values["action"]["action_type"] == "send_reminder"
        assert reopened.store.get_manifest("run-0001") is not None


def test_rerun_with_different_configuration_rejected(config_copy) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED_NOW) as first:
        first.run_case("run-0001", first.open_simulated_case(S1, 7).case_id)
    changed = {"CASEFORGE__RUN__SEED": "7"}
    with build_container(config_copy, environ=changed, clock=lambda: FIXED_NOW) as second:
        case_id = second.open_simulated_case(S1, 7).case_id
        with pytest.raises(RecordConflictError, match="different configuration"):
            second.run_case("run-0001", case_id)


def test_s2_triage_follows_configured_rules(container) -> None:
    for seed in range(20):
        case_id = container.open_simulated_case(S2, seed).case_id
        final = container.run_case(f"run-s2-{seed:02d}", case_id)
        present = set(final["triage"]["event_types"])
        expected = "escalate_case" if "document.received" in present else "send_reminder"
        assert final["triage"]["action_type"] == expected
