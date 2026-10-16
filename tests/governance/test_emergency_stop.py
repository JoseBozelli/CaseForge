"""Emergency stop: governed switch, boundary checks, halting and resuming runs."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from caseforge.agents.workers import evidence_worker
from caseforge.composition import build_container
from caseforge.governance.control_plane import ControlPlane, PermissionDenied
from caseforge.governance.guards import EmergencyStopEngaged, GovernedReasoner, GovernedTools
from caseforge.governance.permissions import APPROVE_ACTION, EMERGENCY_STOP
from caseforge.governance.store import GovernanceStore
from caseforge.persistence.records import LedgerStatus
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.models import ModelSpec
from caseforge.reasoning.prompts import PromptRegistry
from caseforge.reasoning.structured import StructuredCaller
from caseforge.settings.models import GovernanceSettings
from caseforge.tools.models import ToolCall, ToolContext

ROOT = Path(__file__).resolve().parents[2]
FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1 = "routine-stalled-task"
KEY = "run-0001:send_reminder"
SETTINGS = GovernanceSettings.model_validate(
    {
        "roles": {"viewer": [], "admin": [APPROVE_ACTION, EMERGENCY_STOP]},
        "operators": {"viewer-1": ["viewer"], "admin-1": ["admin"]},
    }
)


def stopped(boundary: str) -> None:
    raise EmergencyStopEngaged(f"test stop at {boundary}")


def _control_plane(path: Path) -> tuple[GovernanceStore, ControlPlane]:
    store = GovernanceStore(path)
    return store, ControlPlane(store, SETTINGS, clock=lambda: FIXED)


def test_engaging_requires_permission_and_is_audited(tmp_path: Path) -> None:
    store, plane = _control_plane(tmp_path / "governance.db")
    with pytest.raises(PermissionDenied):
        plane.engage_emergency_stop("viewer-1", "curious")
    assert plane.emergency_stop() is None
    plane.engage_emergency_stop("admin-1", "incident")
    actions = [(e.action, e.outcome) for e in plane.audit_entries()]
    store.close()
    assert actions == [
        (EMERGENCY_STOP, "denied"),
        (EMERGENCY_STOP, "allowed"),
        ("emergency_stop.engaged", "recorded"),
    ]


def test_stop_is_visible_to_another_process_and_can_be_released(tmp_path: Path) -> None:
    path = tmp_path / "governance.db"
    first_store, first = _control_plane(path)
    first.engage_emergency_stop("admin-1", "incident")
    second_store, second = _control_plane(path)  # stands in for another process
    with pytest.raises(EmergencyStopEngaged, match="incident"):
        second.check("act.dispatch")
    first.release_emergency_stop("admin-1")
    second.check("act.dispatch")  # no longer raises
    first_store.close()
    second_store.close()


def test_governed_wrappers_check_before_delegating() -> None:
    reasoner = FakeReasoner({})
    with pytest.raises(EmergencyStopEngaged):
        GovernedReasoner(reasoner, stopped).complete(None)  # type: ignore[arg-type]
    assert reasoner.requests == []

    class CountingTools:
        calls = 0

        def describe(self, agent):
            return []

        def invoke(self, call, context):
            CountingTools.calls += 1

    context = ToolContext(
        run_id="r", tenant_id="t", case_id="c", as_of=FIXED, agent="evidence", step=0
    )
    with pytest.raises(EmergencyStopEngaged):
        GovernedTools(CountingTools(), stopped).invoke(ToolCall(tool="get_case"), context)
    assert CountingTools.calls == 0


def test_worker_failure_isolation_does_not_swallow_the_stop() -> None:
    prompts = PromptRegistry.from_directory(ROOT / "config" / "prompts")
    caller = StructuredCaller(
        GovernedReasoner(FakeReasoner({"evidence": []}), stopped),
        prompts,
        ModelSpec(provider="fake", model="m"),
        clock=lambda: FIXED,
    )

    class NoTools:
        def describe(self, agent):
            return []

        def invoke(self, call, context):
            raise AssertionError("never reached")

    worker = evidence_worker(caller=caller, tools=NoTools(), template_version=1, max_steps=2)
    with pytest.raises(EmergencyStopEngaged):
        worker.run(run_id="r", tenant_id="t", case_id="c", as_of=FIXED, question="q")


def test_run_started_while_stopped_halts_then_resumes_after_release(config_copy) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED) as container:
        container.control_plane.engage_emergency_stop("admin-1", "maintenance")
        world = container.open_simulated_case(S1, 7)
        halted = container.run_case("run-0001", world.case_id)
        assert halted["halted"] is True
        assert world.ground_truth().actions == ()
        assert len(container.control_plane.audit_entries(action="run.halted")) == 1
        container.control_plane.release_emergency_stop("admin-1")
        final = container.resume("run-0001")
    assert final["action"]["ledger_status"] == "succeeded"
    assert [a.action_id for a in world.ground_truth().actions] == [KEY]


class StopOnceBeforeDispatch:
    def __init__(self) -> None:
        self.container = None
        self.fired = False

    def __call__(self, point: str) -> None:
        if point == "act.before_dispatch" and not self.fired:
            self.fired = True
            self.container.control_plane.engage_emergency_stop("admin-1", "operator intervened")


def test_stop_during_a_run_blocks_dispatch_and_resume_executes_once(config_copy) -> None:
    trigger = StopOnceBeforeDispatch()
    with build_container(
        config_copy, environ={}, clock=lambda: FIXED, fault_injector=trigger
    ) as container:
        trigger.container = container
        world = container.open_simulated_case(S1, 7)
        halted = container.run_case("run-0001", world.case_id)
        assert halted["halted"] is True
        assert container.store.get_action(KEY).status == LedgerStatus.INTENT
        assert world.ground_truth().actions == ()
        container.control_plane.release_emergency_stop("admin-1")
        final = container.resume("run-0001")
        entry = container.store.get_action(KEY)
    assert (entry.status, entry.attempts) == (LedgerStatus.SUCCEEDED, 1)
    assert final["action"]["applied"] is True
    assert [a.action_id for a in world.ground_truth().actions] == [KEY]
