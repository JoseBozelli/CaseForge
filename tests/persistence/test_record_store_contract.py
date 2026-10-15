"""Contract tests every RecordStore implementation must pass."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from caseforge.events.mapping import EventNormalizer, load_mapping
from caseforge.persistence.memory import InMemoryRecordStore
from caseforge.persistence.ports import RecordConflictError
from caseforge.persistence.sqlite import SqliteRecordStore
from caseforge.provenance.manifest import GitState, build_run_manifest
from caseforge.settings.loader import load_settings

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


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
