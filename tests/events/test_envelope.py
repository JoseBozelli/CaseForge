"""Tests for the canonical event envelope."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError


def test_valid_event_builds(make_event) -> None:
    event = make_event()
    assert event.schema_version == "event.v1"
    assert event.provenance.mapping_id == "sim-generic"


def test_timestamps_normalized_to_utc(make_event) -> None:
    eastern = timezone(timedelta(hours=-4))
    event = make_event(
        occurred_at=datetime(2026, 1, 5, 5, 0, tzinfo=eastern),
        recorded_at=datetime(2026, 1, 5, 5, 1, tzinfo=eastern),
    )
    assert event.occurred_at == datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    assert event.occurred_at.utcoffset() == timedelta(0)


def test_naive_timestamp_rejected(make_event) -> None:
    with pytest.raises(ValidationError):
        make_event(occurred_at=datetime(2026, 1, 5, 9, 0))


def test_recorded_before_occurred_rejected(make_event) -> None:
    with pytest.raises(ValidationError, match="recorded_at must not precede"):
        make_event(recorded_at=datetime(2026, 1, 5, 8, 0, tzinfo=UTC))


def test_self_causation_rejected(make_event) -> None:
    with pytest.raises(ValidationError, match="causation_id"):
        make_event(causation_id="evt-0001")


def test_unknown_field_rejected(make_event) -> None:
    with pytest.raises(ValidationError):
        make_event(priority="high")


def test_event_is_immutable(make_event) -> None:
    event = make_event()
    with pytest.raises(ValidationError):
        event.event_id = "evt-9999"


def test_raw_hash_must_be_sha256_hex(make_event, event_fields) -> None:
    provenance = dict(event_fields["provenance"], raw_sha256="abc")
    with pytest.raises(ValidationError):
        make_event(provenance=provenance)


def test_attributes_must_be_json_compatible(make_event) -> None:
    with pytest.raises(ValidationError):
        make_event(attributes={"x": object()})


def test_empty_identifier_rejected(make_event) -> None:
    with pytest.raises(ValidationError):
        make_event(tenant_id="")


def test_schema_version_is_fixed(make_event) -> None:
    with pytest.raises(ValidationError):
        make_event(schema_version="event.v2")
