"""Contract tests every RecordStore implementation must pass."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from caseforge.events.mapping import EventNormalizer, load_mapping
from caseforge.persistence.errors import LedgerTransitionError, RecordStoreError
from caseforge.persistence.memory import InMemoryRecordStore
from caseforge.persistence.ports import RecordConflictError
from caseforge.persistence.records import (
    ActionLedgerEntry,
    ApprovalRecord,
    DecisionOutcomeRecord,
    DecisionRecord,
    EpisodeRecord,
    LedgerStatus,
)
from caseforge.persistence.sqlite import SqliteRecordStore
from caseforge.provenance.manifest import GitState, build_run_manifest
from caseforge.reasoning.models import LlmCallRecord, TokenUsage
from caseforge.settings.loader import load_settings
from caseforge.tools.models import ToolInvocationRecord

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
KEY = "run-0001:send_reminder"


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    instance = (
        InMemoryRecordStore()
        if request.param == "memory"
        else SqliteRecordStore(tmp_path / "records.db")
    )
    yield instance
    instance.close()


@pytest.fixture
def manifest(shipped_settings_path):
    loaded = load_settings(shipped_settings_path, environ={})
    return build_run_manifest(
        loaded,
        run_id="run-0001",
        created_at=BASE,
        project_root=ROOT,
        git=GitState(commit="a" * 40, dirty=False),
    )


@pytest.fixture
def normalizer(canonical_vocabulary, sim_mapping_path):
    return EventNormalizer(
        load_mapping(sim_mapping_path, canonical_vocabulary), canonical_vocabulary
    )


def _event(make_event, event_id: str, minutes: int, **overrides):
    return make_event(event_id=event_id, recorded_at=BASE + timedelta(minutes=minutes), **overrides)


def test_manifest_round_trip(store, manifest) -> None:
    store.save_manifest(manifest)
    assert store.get_manifest("run-0001") == manifest


def test_saving_identical_manifest_is_idempotent(store, manifest) -> None:
    store.save_manifest(manifest)
    store.save_manifest(manifest)
    assert store.get_manifest("run-0001") == manifest


def test_conflicting_manifest_rejected(store, manifest) -> None:
    store.save_manifest(manifest)
    with pytest.raises(RecordConflictError, match="run-0001"):
        store.save_manifest(manifest.model_copy(update={"seed": 1}))
    assert store.get_manifest("run-0001") == manifest


def test_missing_manifest_returns_none(store) -> None:
    assert store.get_manifest("ghost") is None


def test_events_inserted_and_returned_in_recording_order(store, make_event) -> None:
    late, early = _event(make_event, "evt-b", 30), _event(make_event, "evt-a", 10)
    assert store.append_events([late, early]).inserted == ("evt-b", "evt-a")
    assert store.events_for_case("tenant-a", "case-0001") == (early, late)


def test_duplicate_event_ignored(store, make_event) -> None:
    event = _event(make_event, "evt-a", 10)
    store.append_events([event])
    result = store.append_events([event, event])
    assert (result.inserted, result.duplicates, result.conflicts) == ((), ("evt-a", "evt-a"), ())
    assert store.events_for_case("tenant-a", "case-0001") == (event,)


def test_conflicting_event_reported_and_original_kept(store, make_event) -> None:
    original = _event(make_event, "evt-a", 10)
    changed = _event(make_event, "evt-a", 10, attributes={"due_at": "2026-01-04T18:00:00Z"})
    store.append_events([original])
    assert store.append_events([changed]).conflicts == ("evt-a",)
    assert store.events_for_case("tenant-a", "case-0001") == (original,)


def test_tenants_are_isolated(store, make_event) -> None:
    first = _event(make_event, "evt-a", 10)
    second = _event(make_event, "evt-a", 10, tenant_id="tenant-b")
    assert store.append_events([first, second]).inserted == ("evt-a", "evt-a")
    assert store.events_for_case("tenant-a", "case-0001") == (first,)
    assert store.events_for_case("tenant-b", "case-0001") == (second,)


def test_events_filtered_by_case(store, make_event) -> None:
    first = _event(make_event, "evt-a", 10)
    other = _event(make_event, "evt-b", 20, case_id="case-0002", correlation_id="case-0002")
    store.append_events([first, other])
    assert store.events_for_case("tenant-a", "case-0002") == (other,)
    assert store.events_for_case("tenant-a", "case-9999") == ()


def test_event_round_trip_preserves_content(store, make_event) -> None:
    event = _event(
        make_event,
        "evt-a",
        10,
        causation_id="evt-0",
        attributes={"due_at": "x", "nested": {"k": [1, 2.5, None, True]}},
    )
    store.append_events([event])
    (loaded,) = store.events_for_case("tenant-a", "case-0001")
    assert loaded == event
    assert loaded.recorded_at.utcoffset() == timedelta(0)


def test_rejections_round_trip_and_deduplicate(store, normalizer, make_source_event) -> None:
    unmapped = normalizer.normalize(make_source_event(source_type="tsk.unknown"))
    violation = normalizer.normalize(make_source_event(source_event_id="raw-0002", attributes={}))
    assert store.save_rejections([unmapped, violation]) == 2
    assert store.save_rejections([unmapped]) == 0
    stored = store.list_rejections()
    assert stored == (unmapped, violation)
    assert stored[1].violations == violation.violations


def test_rejections_filtered_by_source(store, normalizer, make_source_event) -> None:
    own = normalizer.normalize(make_source_event(source_type="tsk.unknown"))
    foreign = normalizer.normalize(make_source_event(source_system="other"))
    store.save_rejections([own, foreign])
    assert store.list_rejections(source_system="other") == (foreign,)


def _llm_call(call_id: str = "run-0001:evidence:0", created_at=BASE) -> LlmCallRecord:
    return LlmCallRecord(
        call_id=call_id,
        run_id="run-0001",
        case_id="case-0001",
        node="evidence",
        step=0,
        template_id="evidence",
        template_version=1,
        template_sha256="a" * 64,
        provider="fake",
        model="fake-model",
        params={},
        request_sha256="b" * 64,
        response_sha256="c" * 64,
        status="ok",
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        created_at=created_at,
    )


def _tool_call(invocation_id: str = "run-0001:evidence:0:get_timeline", at=BASE):
    return ToolInvocationRecord(
        invocation_id=invocation_id,
        run_id="run-0001",
        case_id="case-0001",
        agent="evidence",
        step=0,
        tool="get_timeline",
        arguments={},
        arguments_sha256="d" * 64,
        ok=True,
        error_code=None,
        result_sha256="e" * 64,
        started_at=at,
        finished_at=at,
    )


def _decision(action: str = "send_reminder", decided_at=BASE) -> DecisionRecord:
    return DecisionRecord(
        run_id="run-0001",
        case_id="case-0001",
        tenant_id="tenant-a",
        decision_id="run-0001:decision",
        source="supervisor",
        action_type=action,
        evidence_refs=("evt-0001",),
        decided_at=decided_at,
    )


def _intent(action: str = "send_reminder") -> ActionLedgerEntry:
    return ActionLedgerEntry(
        idempotency_key=KEY,
        run_id="run-0001",
        case_id="case-0001",
        tenant_id="tenant-a",
        action_type=action,
        created_at=BASE,
        updated_at=BASE,
    )


def _at(minutes: int):
    return BASE + timedelta(minutes=minutes)


def test_llm_calls_are_append_only_and_deduplicated(store) -> None:
    first, later = _llm_call(), _llm_call(call_id="run-0001:evidence:1")
    rerun = _llm_call(created_at=_at(60))
    assert store.save_llm_calls([first, later]) == 2
    assert store.save_llm_calls([first]) == 0
    assert store.save_llm_calls([rerun]) == 1
    assert store.llm_calls_for_run("run-0001") == (first, later, rerun)
    assert store.llm_calls_for_run("run-9999") == ()


def test_tool_invocations_are_append_only_and_deduplicated(store) -> None:
    first, rerun = _tool_call(), _tool_call(at=_at(60))
    assert store.save_tool_invocations([first, first]) == 1
    assert store.save_tool_invocations([rerun]) == 1
    assert store.tool_invocations_for_run("run-0001") == (first, rerun)


def test_first_committed_decision_wins(store) -> None:
    original = _decision()
    assert store.save_decision(original).status == "inserted"
    repeat = store.save_decision(_decision(decided_at=_at(60)))
    assert (repeat.status, repeat.stored) == ("duplicate", original)
    different = store.save_decision(_decision(action="reassign_task"))
    assert (different.status, different.stored) == ("conflict", original)
    assert store.get_decision("run-0001") == original


def test_missing_decision_returns_none(store) -> None:
    assert store.get_decision("ghost") is None


def test_begin_action_never_overwrites(store) -> None:
    entry = store.begin_action(_intent())
    assert entry.status == LedgerStatus.INTENT
    assert store.begin_action(_intent(action="reassign_task")) == entry


def test_begin_action_requires_intent_status(store) -> None:
    started = _intent().model_copy(update={"status": LedgerStatus.DISPATCHED})
    with pytest.raises(LedgerTransitionError):
        store.begin_action(started)


def test_ledger_happy_path_is_persisted(store) -> None:
    store.begin_action(_intent())
    dispatched = store.transition_action(KEY, LedgerStatus.DISPATCHED, at=_at(1))
    assert dispatched.attempts == 1
    done = store.transition_action(KEY, LedgerStatus.SUCCEEDED, at=_at(2), result={"applied": True})
    assert store.get_action(KEY) == done
    assert done.result == {"applied": True}


def test_invalid_transition_is_rejected_and_entry_unchanged(store) -> None:
    store.begin_action(_intent())
    with pytest.raises(LedgerTransitionError, match="intent -> succeeded"):
        store.transition_action(KEY, LedgerStatus.SUCCEEDED, at=_at(1))
    assert store.get_action(KEY).status == LedgerStatus.INTENT


def test_retry_and_unknown_paths(store) -> None:
    store.begin_action(_intent())
    store.transition_action(KEY, LedgerStatus.DISPATCHED, at=_at(1))
    store.transition_action(KEY, LedgerStatus.FAILED, at=_at(2), error="timeout")
    retried = store.transition_action(KEY, LedgerStatus.DISPATCHED, at=_at(3))
    assert retried.attempts == 2
    store.transition_action(KEY, LedgerStatus.UNKNOWN, at=_at(4))
    reconciled = store.transition_action(KEY, LedgerStatus.SUCCEEDED, at=_at(5))
    assert (reconciled.status, reconciled.attempts) == (LedgerStatus.SUCCEEDED, 2)


def test_transition_of_unknown_action_is_rejected(store) -> None:
    with pytest.raises(RecordStoreError, match="unknown action"):
        store.transition_action("ghost", LedgerStatus.DISPATCHED, at=_at(1))


def _approval(decision: str = "approved") -> ApprovalRecord:
    return ApprovalRecord(
        run_id="run-0001",
        case_id="case-0001",
        tenant_id="tenant-a",
        action_type="grant_policy_exception",
        decision=decision,
        actor="approver-1",
        decided_at=BASE,
    )


def test_approvals_are_append_only(store) -> None:
    approved, rejected = _approval(), _approval(decision="rejected")
    assert store.save_approval(approved) is True
    assert store.save_approval(approved) is False
    assert store.save_approval(rejected) is True
    assert store.approvals_for_run("run-0001") == (approved, rejected)
    assert store.approvals_for_run("run-9999") == ()


def _episode(run_id: str, case_id: str, tenant_id: str = "tenant-a", outcome: str = "pending"):
    return EpisodeRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        case_id=case_id,
        event_types=("task.delayed",),
        decision_source="triage",
        action_type="send_reminder",
        ledger_status="succeeded",
        outcome_status=outcome,
        summary="Case events: task.delayed. Decision by triage: send_reminder.",
        recorded_at=BASE,
    )


def test_episodes_are_replaced_per_run_and_scoped_by_tenant(store) -> None:
    store.save_episode(_episode("run-1", "case-1"))
    store.save_episode(_episode("run-2", "case-2"))
    store.save_episode(_episode("run-3", "case-3", tenant_id="tenant-b"))
    updated = _episode("run-1", "case-1", outcome="success")
    store.save_episode(updated)
    episodes = store.episodes_for_tenant("tenant-a")
    assert [e.run_id for e in episodes] == ["run-1", "run-2"]
    assert episodes[0] == updated


def _outcome_record(run_id: str, status: str = "pending", tenant_id: str = "tenant-a"):
    return DecisionOutcomeRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        case_id="case-1",
        decision_source="triage",
        action_type="send_reminder",
        candidate_actions=("send_reminder",),
        ledger_status="succeeded",
        outcome_status=status,
        acted_at=BASE,
        updated_at=BASE,
    )


def test_decision_outcomes_are_upserted_and_filtered(store) -> None:
    store.save_decision_outcome(_outcome_record("run-1"))
    store.save_decision_outcome(_outcome_record("run-2", tenant_id="tenant-b"))
    refreshed = _outcome_record("run-1", status="success")
    store.save_decision_outcome(refreshed)
    assert store.get_decision_outcome("run-1") == refreshed
    assert [r.run_id for r in store.decision_outcomes()] == ["run-1", "run-2"]
    assert store.decision_outcomes(outcome_status="pending")[0].run_id == "run-2"
    assert store.decision_outcomes(tenant_id="tenant-a") == (refreshed,)
