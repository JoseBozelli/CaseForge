"""Tests for settings loading, overrides and config-graph validation."""

from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.settings.loader import apply_env_overrides, load_settings


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_shipped_settings_load(shipped_settings_path) -> None:
    loaded = load_settings(shipped_settings_path, environ={})
    assert loaded.settings.settings_version == 1
    assert loaded.vocabulary.vocabulary_id == "caseforge-canonical"
    assert [m.mapping_id for m in loaded.mappings] == ["sim-generic"]
    assert loaded.overrides == ()


def test_env_overrides_applied_and_typed(config_copy) -> None:
    environ = {
        "CASEFORGE__RUN__SEED": "7",
        "CASEFORGE__PROVENANCE__SNAPSHOT_MODE": "off",
        "UNRELATED_VARIABLE": "x",
    }
    loaded = load_settings(config_copy, environ=environ)
    assert loaded.settings.run.seed == 7
    assert loaded.settings.provenance.snapshot_mode == "off"
    assert loaded.overrides == ("provenance.snapshot_mode", "run.seed")


def test_unknown_override_key_rejected(config_copy) -> None:
    with pytest.raises(ConfigError, match="colour"):
        load_settings(config_copy, environ={"CASEFORGE__RUN__COLOUR": "blue"})


def test_override_into_scalar_rejected(config_copy) -> None:
    with pytest.raises(ConfigError, match="is not a section"):
        load_settings(config_copy, environ={"CASEFORGE__RUN__SEED__X": "1"})


def test_malformed_override_rejected(config_copy) -> None:
    with pytest.raises(ConfigError, match="malformed"):
        load_settings(config_copy, environ={"CASEFORGE__RUN____SEED": "1"})


def test_overrides_do_not_mutate_input() -> None:
    raw = {"run": {"seed": 1}}
    data, applied = apply_env_overrides(raw, {"CASEFORGE__RUN__SEED": "2"})
    assert raw == {"run": {"seed": 1}}
    assert data["run"]["seed"] == 2
    assert applied == ("run.seed",)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("seed: 20261015", "seed: -1", "seed"),
        ("snapshot_mode: redacted", "snapshot_mode: verbose", "snapshot_mode"),
        ("settings_version: 1", "settings_version: 2", "settings_version"),
        ("tenant_id: tenant-demo", "tenant_id: Tenant Demo", "tenant_id"),
    ],
)
def test_invalid_settings_rejected(config_copy, old: str, new: str, message: str) -> None:
    _edit(config_copy, old, new)
    with pytest.raises(ConfigError, match=message):
        load_settings(config_copy, environ={})


def test_missing_referenced_file_rejected(config_copy) -> None:
    _edit(config_copy, "vocabulary/canonical.v1.yaml", "vocabulary/absent.yaml")
    with pytest.raises(ConfigError, match="not found"):
        load_settings(config_copy, environ={})


def test_incompatible_mapping_rejected(config_copy) -> None:
    mapping = config_copy.parent / "vocabulary" / "mappings" / "sim.v1.yaml"
    _edit(mapping, "canonical_version: 1", "canonical_version: 2")
    with pytest.raises(ConfigError, match="incompatible"):
        load_settings(config_copy, environ={})


def test_duplicate_source_system_rejected(config_copy) -> None:
    mappings_dir = config_copy.parent / "vocabulary" / "mappings"
    (mappings_dir / "sim_copy.v1.yaml").write_text(
        (mappings_dir / "sim.v1.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _edit(
        config_copy,
        "    - vocabulary/mappings/sim.v1.yaml",
        "    - vocabulary/mappings/sim.v1.yaml\n    - vocabulary/mappings/sim_copy.v1.yaml",
    )
    with pytest.raises(ConfigError, match="source_system"):
        load_settings(config_copy, environ={})
