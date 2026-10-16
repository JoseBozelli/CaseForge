"""Control Plane: append-only audit log, roles and permissions, governed approvals."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.composition import build_container
from caseforge.governance.control_plane import ControlPlane, PermissionDenied
from caseforge.governance.models import AuditEntry
from caseforge.governance.permissions import APPROVE_ACTION
from caseforge.governance.store import GovernanceError, GovernanceStore
from caseforge.reasoning.fake import FakeReasoner
from caseforge.settings.models import GovernanceSettings

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
SETTINGS = GovernanceSettings.model_validate(
    {
        "roles": {"viewer": [], "approver": [APPROVE_ACTION]},
        "operators": {"viewer-1": ["viewer"], "approver-1": ["approver"]},
    }
)
SCRIPT = {
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


@pytest.fixture
def store(tmp_path: Path):
    instance = GovernanceStore(tmp_path / "governance.db")
    yield instance
    instance.close()


@pytest.fixture
def control_plane(store) -> ControlPlane:
    return ControlPlane(store, SETTINGS, clock=lambda: FIXED)


def _entry(action: str = "approve_action") -> AuditEntry:
    return AuditEntry(
        at=FIXED, actor="approver-1", action=action, target="run-1", outcome="allowed"
    )


def test_audit_entries_are_numbered_and_listed_in_order(store) -> None:
    first = store.append_audit(_entry())
    second = store.append_audit(_entry(action="approval.approved"))
    assert (first.seq, second.seq) == (1, 2)
    assert [e.action for e in store.audit_entries()] == ["approve_action", "approval.approved"]
    assert store.audit_entries(action="approval.approved") == (second,)


def test_audit_log_refuses_updates_and_deletes(store) -> None:
    store.append_audit(_entry())
    conn = sqlite3.connect(store._db.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE audit_log SET actor = 'someone-else'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM audit_log")
    finally:
        conn.close()
    assert len(store.audit_entries()) == 1


def test_limitation_a_privileged_process_can_remove_the_protection(store) -> None:
    """Documents the limit: triggers stop the application, not a schema-level attacker."""
    store.append_audit(_entry())
    conn = sqlite3.connect(store._db.path)
    try:
        conn.execute("DROP TRIGGER audit_log_no_delete")
        conn.execute("DELETE FROM audit_log")
        conn.commit()
    finally:
        conn.close()
    assert store.audit_entries() == ()


def test_unknown_governance_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "governance.db"
    GovernanceStore(path).close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_info SET value = 'governance.v0' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    with pytest.raises(GovernanceError, match="unsupported governance schema"):
        GovernanceStore(path)


def test_authorization_follows_roles_and_is_always_audited(control_plane) -> None:
    allowed = control_plane.authorize("approver-1", APPROVE_ACTION, target="run-1")
    denied = control_plane.authorize("viewer-1", APPROVE_ACTION, target="run-1")
    stranger = control_plane.authorize("nobody", APPROVE_ACTION, target="run-1")
    assert [allowed.outcome, denied.outcome, stranger.outcome] == ["allowed", "denied", "denied"]
    assert len(control_plane.audit_entries(target="run-1")) == 3


def test_require_raises_after_recording_the_denial(control_plane) -> None:
    with pytest.raises(PermissionDenied, match="viewer-1"):
        control_plane.require("viewer-1", APPROVE_ACTION, target="run-1")
    assert [e.outcome for e in control_plane.audit_entries()] == ["denied"]


def test_unknown_permission_is_a_programming_error(control_plane) -> None:
    with pytest.raises(ValueError, match="unknown permission"):
        control_plane.authorize("approver-1", "launch_rockets", target="run-1")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "approver: [approve_action]",
            "approver: [approve_action, launch_rockets]",
            "unknown permissions",
        ),
        ("approver-1: [approver]", "approver-1: [superuser]", "undefined roles"),
    ],
)
def test_governance_configuration_is_validated(
    config_copy, old: str, new: str, message: str
) -> None:
    text = config_copy.read_text(encoding="utf-8")
    assert old in text
    config_copy.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        build_container(config_copy, environ={})


def _paused_container(config_copy):
    container = build_container(
        config_copy, environ={}, clock=lambda: FIXED, reasoner=FakeReasoner(SCRIPT)
    )
    world = container.open_simulated_case("policy-question", 1)
    container.run_case("run-0001", world.case_id)
    return container, world


def test_approval_by_an_operator_without_the_role_is_denied_and_audited(config_copy) -> None:
    container, world = _paused_container(config_copy)
    with container:
        with pytest.raises(PermissionDenied):
            container.approve("run-0001", actor="viewer-1")
        assert container.pending_approval("run-0001") is not None
        audit = container.control_plane.audit_entries(target="run-0001")
    assert world.ground_truth().actions == ()
    assert [(e.actor, e.action, e.outcome) for e in audit] == [
        ("viewer-1", APPROVE_ACTION, "denied")
    ]


def test_approval_by_an_approver_is_allowed_and_audited(config_copy) -> None:
    container, world = _paused_container(config_copy)
    with container:
        container.approve("run-0001", actor="approver-1")
        audit = container.control_plane.audit_entries(target="run-0001")
    assert [a.action_type for a in world.ground_truth().actions] == ["grant_policy_exception"]
    assert [(e.action, e.outcome) for e in audit] == [
        (APPROVE_ACTION, "allowed"),
        ("approval.approved", "recorded"),
    ]
