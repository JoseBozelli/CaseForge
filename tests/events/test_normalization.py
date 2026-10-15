"""Tests for deterministic source-to-canonical normalization."""

from datetime import UTC, datetime

import pytest

from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import (
    EventNormalizer,
    Rejection,
    RejectionCode,
    load_mapping,
)
from caseforge.events.vocabulary import ViolationCode


@pytest.fixture
def normalizer(canonical_vocabulary, sim_mapping_path) -> EventNormalizer:
    spec = load_mapping(sim_mapping_path, canonical_vocabulary)
    return EventNormalizer(spec, canonical_vocabulary)


def _rejection(result) -> Rejection:
    assert isinstance(result, Rejection), result
    return result


def test_maps_source_event_to_canonical(normalizer, make_source_event) -> None:
    result = normalizer.normalize(make_source_event())
    assert isinstance(result, EventEnvelope)
    assert result.event_id == "sim:raw-0001"
    assert result.event_type == "task.delayed"
    assert result.entity_type == "task"
    assert result.actor == "system"
    assert result.correlation_id == "case-0001"
    assert result.attributes == {"due_at": "2026-01-04T17:00:00Z"}


def test_provenance_preserved(normalizer, make_source_event) -> None:
    source = make_source_event()
    provenance = normalizer.normalize(source).provenance
    assert (provenance.source_system, provenance.source_event_type) == ("sim", "tsk.late")
    assert provenance.source_event_id == "raw-0001"
    assert (provenance.mapping_id, provenance.mapping_version) == ("sim-generic", 1)
    assert provenance.canonical_version == 1
    assert provenance.raw_sha256 == source.content_sha256()


def test_normalization_is_deterministic(normalizer, make_source_event) -> None:
    assert normalizer.normalize(make_source_event()) == normalizer.normalize(make_source_event())


def test_raw_hash_tracks_content(make_source_event) -> None:
    changed = make_source_event(attributes={"due": "2026-01-04T18:00:00Z"})
    assert make_source_event().content_sha256() != changed.content_sha256()


def test_causation_id_translated_to_canonical_id(normalizer, make_source_event) -> None:
    result = normalizer.normalize(make_source_event(causation_id="raw-0000"))
    assert result.causation_id == "sim:raw-0000"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"source_type": "tsk.unknown"}, RejectionCode.UNMAPPED),
        ({"source_system": "other"}, RejectionCode.WRONG_SOURCE),
        ({"actor": "robot"}, RejectionCode.ACTOR_NOT_MAPPED),
        ({"source_type": "sim.tick"}, RejectionCode.EXPLICIT_REJECT),
        (
            {"source_type": "doc.in", "attributes": {"kind": "form", "channel": "unknown"}},
            RejectionCode.EXPLICIT_REJECT,
        ),
        ({"source_type": "doc.in", "attributes": {"kind": "form"}}, RejectionCode.UNMAPPED),
        ({"attributes": {}}, RejectionCode.VOCABULARY_VIOLATION),
        ({"actor": "ops"}, RejectionCode.VOCABULARY_VIOLATION),
        (
            {"recorded_at": datetime(2026, 1, 5, 8, 0, tzinfo=UTC)},
            RejectionCode.INVALID_ENVELOPE,
        ),
    ],
)
def test_rejections(normalizer, make_source_event, overrides, code) -> None:
    assert _rejection(normalizer.normalize(make_source_event(**overrides))).code == code


def test_where_condition_selects_rule(normalizer, make_source_event) -> None:
    source = make_source_event(
        source_type="doc.in",
        entity_id="doc-0001",
        actor="req",
        attributes={"kind": "form", "channel": "upload"},
    )
    result = normalizer.normalize(source)
    assert isinstance(result, EventEnvelope)
    assert result.event_type == "document.received"
    assert result.attributes == {"document_type": "form"}


def test_vocabulary_violation_carries_codes(normalizer, make_source_event) -> None:
    rejection = _rejection(normalizer.normalize(make_source_event(attributes={})))
    assert {v.code for v in rejection.violations} == {ViolationCode.MISSING_ATTRIBUTE}


def test_rejection_is_traceable(normalizer, make_source_event) -> None:
    source = make_source_event(source_type="tsk.unknown")
    rejection = _rejection(normalizer.normalize(source))
    assert (rejection.mapping_id, rejection.mapping_version) == ("sim-generic", 1)
    assert rejection.source_event_id == "raw-0001"
    assert rejection.raw_sha256 == source.content_sha256()


def test_batch_splits_and_preserves_order(normalizer, make_source_event) -> None:
    events = [
        make_source_event(source_event_id="raw-1"),
        make_source_event(source_event_id="raw-2", source_type="tsk.unknown"),
        make_source_event(source_event_id="raw-3"),
    ]
    result = normalizer.normalize_batch(events)
    assert [e.event_id for e in result.accepted] == ["sim:raw-1", "sim:raw-3"]
    assert [r.source_event_id for r in result.rejected] == ["raw-2"]


def test_runtime_ambiguity_guard(canonical_vocabulary, sim_mapping_path, make_source_event) -> None:
    spec = load_mapping(sim_mapping_path, canonical_vocabulary)
    late_rule = next(r for r in spec.rules if r.match.source_type == "tsk.late")
    ambiguous = spec.model_copy(update={"rules": (*spec.rules, late_rule)})  # bypasses load checks
    normalizer = EventNormalizer(ambiguous, canonical_vocabulary)
    assert _rejection(normalizer.normalize(make_source_event())).code == RejectionCode.AMBIGUOUS


def test_second_source_yields_same_canonical_semantics(
    normalizer, canonical_vocabulary, fixtures_dir, make_source_event
) -> None:
    alt_spec = load_mapping(fixtures_dir / "mappings" / "alt.v1.yaml", canonical_vocabulary)
    alt = EventNormalizer(alt_spec, canonical_vocabulary)
    sim_event = normalizer.normalize(make_source_event())
    alt_event = alt.normalize(
        make_source_event(
            source_system="alt",
            source_type="WorkItemOverdue",
            actor="AUTOMATION",
            attributes={"deadline": "2026-01-04T17:00:00Z"},
        )
    )

    def semantics(event: EventEnvelope) -> dict:
        return event.model_dump(exclude={"event_id", "provenance"})

    assert semantics(sim_event) == semantics(alt_event)
    assert alt_event.provenance.source_system == "alt"


def test_same_type_name_from_other_source_is_not_assumed(
    canonical_vocabulary, fixtures_dir, make_source_event
) -> None:
    alt_spec = load_mapping(fixtures_dir / "mappings" / "alt.v1.yaml", canonical_vocabulary)
    alt = EventNormalizer(alt_spec, canonical_vocabulary)
    result = alt.normalize(make_source_event(source_system="alt", actor="AUTOMATION"))
    assert _rejection(result).code == RejectionCode.UNMAPPED
