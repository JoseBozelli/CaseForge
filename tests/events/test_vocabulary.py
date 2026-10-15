"""Tests for the canonical vocabulary loader and event checks."""

from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.events.vocabulary import (
    ViolationCode,
    VocabularyViolationError,
    load_vocabulary,
)

MINIMAL_VOCABULARY = """\
vocabulary_id: test
version: 1
description: Test vocabulary.
actors: [system]
entity_types: [case]
event_types:
  case.created:
    description: Opened.
    entity_types: [case]
    allowed_actors: [system]
"""


@pytest.fixture
def vocabulary(canonical_vocabulary_path):
    return load_vocabulary(canonical_vocabulary_path)


def _codes(vocabulary, event) -> set[ViolationCode]:
    return {violation.code for violation in vocabulary.check(event)}


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "vocabulary.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_vocabulary_loads(vocabulary) -> None:
    assert vocabulary.version == 1
    assert len(vocabulary.event_types) == 8
    assert "task.delayed" in vocabulary.event_types


def test_valid_event_has_no_violations(vocabulary, make_event) -> None:
    event = make_event()
    assert vocabulary.check(event) == ()
    vocabulary.validate_event(event)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"event_type": "task.vanished"}, ViolationCode.UNKNOWN_EVENT_TYPE),
        ({"actor": "requester"}, ViolationCode.ACTOR_NOT_ALLOWED),
        ({"entity_type": "case"}, ViolationCode.ENTITY_TYPE_NOT_ALLOWED),
        ({"case_id": None}, ViolationCode.MISSING_CASE_ID),
        ({"attributes": {}}, ViolationCode.MISSING_ATTRIBUTE),
        ({"attributes": {"due_at": None}}, ViolationCode.MISSING_ATTRIBUTE),
    ],
)
def test_violation_detected(vocabulary, make_event, overrides, expected) -> None:
    assert expected in _codes(vocabulary, make_event(**overrides))


def test_canonical_version_mismatch(vocabulary, make_event, event_fields) -> None:
    provenance = dict(event_fields["provenance"], canonical_version=2)
    event = make_event(provenance=provenance)
    assert ViolationCode.CANONICAL_VERSION_MISMATCH in _codes(vocabulary, event)


def test_validate_event_reports_all_violations(vocabulary, make_event) -> None:
    event = make_event(actor="requester", attributes={})
    with pytest.raises(VocabularyViolationError) as info:
        vocabulary.validate_event(event)
    assert {v.code for v in info.value.violations} == {
        ViolationCode.ACTOR_NOT_ALLOWED,
        ViolationCode.MISSING_ATTRIBUTE,
    }


def test_minimal_vocabulary_loads(tmp_path: Path) -> None:
    assert load_vocabulary(_write(tmp_path, MINIMAL_VOCABULARY)).version == 1


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("allowed_actors: [system]", "allowed_actors: [robot]", "undeclared actors"),
        ("    entity_types: [case]", "    entity_types: [ledger]", "undeclared entity types"),
        ("  case.created:", "  CaseCreated:", "event_types"),
        ("version: 1", "version: 0", "version"),
    ],
)
def test_invalid_vocabulary_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert old in MINIMAL_VOCABULARY
    text = MINIMAL_VOCABULARY.replace(old, new, 1)
    with pytest.raises(ConfigError, match=message):
        load_vocabulary(_write(tmp_path, text))
