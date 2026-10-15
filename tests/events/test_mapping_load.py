"""Tests for loading and validating mapping files."""

from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.events.mapping import load_mapping

MINIMAL_MAPPING = """\
mapping_id: test-map
mapping_version: 1
canonical_version: 1
source_system: src
actor_map: {bot: system}
rules:
  - match: {source_type: late}
    canonical_type: task.delayed
    entity_type: task
    attribute_map: {due: due_at}
"""

EXTRA_RULE = """\
  - match: {{source_type: late, where: {{kind: {kind}}}}}
    canonical_type: task.delayed
    entity_type: task
    attribute_map: {{due: due_at}}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "mapping.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_sim_mapping_loads(canonical_vocabulary, sim_mapping_path) -> None:
    spec = load_mapping(sim_mapping_path, canonical_vocabulary)
    assert spec.mapping_id == "sim-generic"
    assert len(spec.rules) == 8


def test_minimal_mapping_loads(tmp_path: Path, canonical_vocabulary) -> None:
    spec = load_mapping(_write(tmp_path, MINIMAL_MAPPING), canonical_vocabulary)
    assert spec.source_system == "src"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("canonical_type: task.delayed", "canonical_type: task.vanished", "unknown canonical"),
        ("entity_type: task", "entity_type: case", "entity type"),
        ("attribute_map: {due: due_at}", "attribute_map: {due: deadline}", "required attributes"),
        ("actor_map: {bot: system}", "actor_map: {bot: robot}", "undeclared actors"),
        ("canonical_version: 1", "canonical_version: 2", "canonical_version"),
        (
            "attribute_map: {due: due_at}",
            "attribute_map: {due: due_at, eta: due_at}",
            "duplicate attribute targets",
        ),
    ],
)
def test_invalid_mapping_rejected(
    tmp_path: Path, canonical_vocabulary, old: str, new: str, message: str
) -> None:
    assert old in MINIMAL_MAPPING
    text = MINIMAL_MAPPING.replace(old, new, 1)
    with pytest.raises(ConfigError, match=message):
        load_mapping(_write(tmp_path, text), canonical_vocabulary)


def test_overlapping_rules_rejected(tmp_path: Path, canonical_vocabulary) -> None:
    text = MINIMAL_MAPPING + EXTRA_RULE.format(kind="x")
    with pytest.raises(ConfigError, match="overlap"):
        load_mapping(_write(tmp_path, text), canonical_vocabulary)


def test_rules_with_conflicting_conditions_do_not_overlap(
    tmp_path: Path, canonical_vocabulary
) -> None:
    base = MINIMAL_MAPPING.replace(
        "{source_type: late}", "{source_type: late, where: {kind: y}}", 1
    )
    spec = load_mapping(_write(tmp_path, base + EXTRA_RULE.format(kind="x")), canonical_vocabulary)
    assert len(spec.rules) == 2
