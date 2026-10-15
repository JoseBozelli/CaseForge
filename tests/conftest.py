"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from caseforge.events.envelope import EventEnvelope

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_VOCABULARY_PATH = ROOT / "config" / "vocabulary" / "canonical.v1.yaml"


def _base_event_fields() -> dict[str, Any]:
    return {
        "event_id": "evt-0001",
        "event_type": "task.delayed",
        "tenant_id": "tenant-a",
        "entity_type": "task",
        "entity_id": "task-0001",
        "case_id": "case-0001",
        "actor": "system",
        "correlation_id": "case-0001",
        "occurred_at": datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        "recorded_at": datetime(2026, 1, 5, 9, 1, tzinfo=UTC),
        "attributes": {"due_at": "2026-01-04T17:00:00Z"},
        "provenance": {
            "source_system": "sim",
            "source_event_type": "tsk.late",
            "source_event_id": "raw-0001",
            "mapping_id": "sim-generic",
            "mapping_version": 1,
            "canonical_version": 1,
            "raw_sha256": "0" * 64,
        },
    }


@pytest.fixture
def canonical_vocabulary_path() -> Path:
    return CANONICAL_VOCABULARY_PATH


@pytest.fixture
def event_fields() -> dict[str, Any]:
    return _base_event_fields()


@pytest.fixture
def make_event() -> Callable[..., EventEnvelope]:
    def _make(**overrides: Any) -> EventEnvelope:
        fields = _base_event_fields()
        fields.update(overrides)
        return EventEnvelope.model_validate(fields)

    return _make
