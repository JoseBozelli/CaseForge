"""Tests for strict YAML loading."""

from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.common.yaml_io import load_yaml_mapping


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_mapping(tmp_path: Path) -> None:
    path = _write(tmp_path, "a: 1\nb: [x, y]\n")
    assert load_yaml_mapping(path) == {"a": 1, "b": ["x", "y"]}


def test_rejects_top_level_duplicate_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate key 'a'"):
        load_yaml_mapping(_write(tmp_path, "a: 1\na: 2\n"))


def test_rejects_nested_duplicate_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate key 'k'"):
        load_yaml_mapping(_write(tmp_path, "outer:\n  k: 1\n  k: 2\n"))


def test_rejects_non_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="mapping"):
        load_yaml_mapping(_write(tmp_path, "- a\n- b\n"))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_yaml_mapping(tmp_path / "absent.yaml")
