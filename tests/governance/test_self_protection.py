"""Reconciliation of unknown actions and proofs that agents cannot reach governance."""

from datetime import UTC, datetime

import pytest

from caseforge.composition import build_container
from caseforge.governance.control_plane import PermissionDenied
from caseforge.governance.permissions import RECONCILE_ACTION
from caseforge.persistence.records import LedgerStatus
from caseforge.reasoning.fake import FakeReasoner
from caseforge.tools.models import ToolErrorCode

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1 = "routine-stalled-task"
KEY = "run-0001:send_reminder"
READ_TOOLS = {"get_case", "get_timeline", "search_policies", "search_prior_episodes"}


class CrashAfterExecute:
    fired = False

    def __call__(self, point: str) -> None:
        if point == "act.after_execute" and not self.fired:
            self.fired = True
            raise RuntimeError("simulated crash")


def _container_with_unknown_action(config_copy):
    container = build_container(
        config_copy, environ={}, clock=lambda: FIXED, fault_injector=CrashAfterExecute()
    )
    container.environment.supports_idempotency_keys = False
    world = container.open_simulated_case(S1, 7)
    with pytest.raises(RuntimeError):
        container.run_case("run-0001", world.case_id)
    container.resume("run-0001")
    assert container.store.get_action(KEY).status == LedgerStatus.UNKNOWN
    return container, world


def test_admin_reconciles_an_unknown_action_and_it_is_never_repeated(config_copy) -> None:
    container, world = _container_with_unknown_action(config_copy)
    with container:
        entry = container.reconcile_action(
            KEY, actor="admin-1", outcome="succeeded", note="Confirmed with the external system."
        )
        rerun = container.run_case("run-0001", world.case_id)
        audit = [e.action for e in container.control_plane.audit_entries(target=f"action:{KEY}")]
    assert entry.status == LedgerStatus.SUCCEEDED
    assert entry.result["reconciled_by"] == "admin-1"
    assert rerun["action"]["applied"] is False
    assert len(world.ground_truth().actions) == 1
    assert audit == [RECONCILE_ACTION, "action.reconciled"]


def test_reconciliation_requires_permission_and_is_audited(config_copy) -> None:
    container, _ = _container_with_unknown_action(config_copy)
    with container:
        with pytest.raises(PermissionDenied):  # noqa: SIM117 - container stays open below
            container.reconcile_action(KEY, actor="approver-1", outcome="failed", note="guess")
        status = container.store.get_action(KEY).status
        audit = container.control_plane.audit_entries(target=f"action:{KEY}")
    assert status == LedgerStatus.UNKNOWN
    assert [(e.actor, e.outcome) for e in audit] == [("approver-1", "denied")]


def test_only_unknown_actions_can_be_reconciled(config_copy) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED) as container:
        container.run_case("run-0001", container.open_simulated_case(S1, 7).case_id)
        with pytest.raises(ValueError, match="only unknown actions"):
            container.reconcile_action(KEY, actor="admin-1", outcome="failed", note="no")


def test_the_tool_cupboard_holds_only_read_only_investigation_tools(config_copy) -> None:
    with build_container(config_copy, environ={}) as container:
        names = set(container.tools.names())
        specs = [container.tools.spec(name) for name in names]
    assert names == READ_TOOLS
    assert {spec.side_effect for spec in specs} == {"read"}
    assert not any(spec.handler.__module__.startswith("caseforge.governance") for spec in specs)


def test_an_agent_cannot_call_governance_operations(config_copy) -> None:
    attempts = [
        {"tool": "engage_emergency_stop", "arguments": {"reason": "because"}},
        {"tool": "reset_breaker", "arguments": {"resource": "executor"}},
    ]
    script = {
        "supervisor_plan": [
            {
                "objective": "Investigate.",
                "workers": ["evidence"],
                "evidence_question": "What happened?",
                "rationale": "Facts needed.",
            }
        ],
        "evidence": [
            *({"action": "call_tool", "rationale": "Try it.", "tool": a} for a in attempts),
            {
                "action": "finish",
                "rationale": "Done.",
                "findings": {"summary": "Nothing to cite."},
            },
        ],
        "supervisor_synthesis": [
            {"decision": "escalate", "rationale": "Escalate.", "escalation_reason": "Review."}
        ],
    }
    with build_container(
        config_copy, environ={}, clock=lambda: FIXED, reasoner=FakeReasoner(script)
    ) as container:
        world = container.open_simulated_case("policy-question", 1)
        final = container.run_case("run-0001", world.case_id)
        stop = container.control_plane.emergency_stop()
        governance_audit = [
            e for e in container.control_plane.audit_entries() if e.action != "budget.exhausted"
        ]
    codes = [c["error_code"] for c in final["tool_calls"] if c["tool"] != "get_case"]
    assert codes == [ToolErrorCode.UNKNOWN_TOOL, ToolErrorCode.UNKNOWN_TOOL]
    assert stop is None
    assert governance_audit == []
