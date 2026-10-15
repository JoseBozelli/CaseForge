"""Shared test fixtures."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from caseforge.events.envelope import EventEnvelope
from caseforge.events.source import SourceEvent
from caseforge.events.vocabulary import CanonicalVocabulary, load_vocabulary

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_VOCABULARY_PATH = ROOT / "config" / "vocabulary" / "canonical.v1.yaml"
SIM_MAPPING_PATH = ROOT / "config" / "vocabulary" / "mappings" / "sim.v1.yaml"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
CONFIG_DIR = ROOT / "config"
SHIPPED_SETTINGS_PATH = CONFIG_DIR / "caseforge.yaml"


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


def _base_source_fields() -> dict[str, Any]:
    return {
        "source_system": "sim",
        "source_event_id": "raw-0001",
        "source_type": "tsk.late",
        "tenant_id": "tenant-a",
        "entity_id": "task-0001",
        "case_id": "case-0001",
        "actor": "sys",
        "occurred_at": datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        "recorded_at": datetime(2026, 1, 5, 9, 1, tzinfo=UTC),
        "attributes": {"due": "2026-01-04T17:00:00Z", "internal_note": "not mapped"},
    }


@pytest.fixture
def canonical_vocabulary_path() -> Path:
    return CANONICAL_VOCABULARY_PATH


@pytest.fixture
def canonical_vocabulary() -> CanonicalVocabulary:
    return load_vocabulary(CANONICAL_VOCABULARY_PATH)


@pytest.fixture
def sim_mapping_path() -> Path:
    return SIM_MAPPING_PATH


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


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


@pytest.fixture
def make_source_event() -> Callable[..., SourceEvent]:
    def _make(**overrides: Any) -> SourceEvent:
        fields = _base_source_fields()
        fields.update(overrides)
        return SourceEvent.model_validate(fields)

    return _make


@pytest.fixture
def shipped_settings_path() -> Path:
    return SHIPPED_SETTINGS_PATH


@pytest.fixture
def config_copy(tmp_path: Path) -> Path:
    """Writable copy of the shipped config tree; returns the copied settings file."""
    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target)
    return target / "caseforge.yaml"
