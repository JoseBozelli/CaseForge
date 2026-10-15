"""Smoke tests for package installation and version consistency."""

import tomllib
from pathlib import Path

import caseforge

ROOT = Path(__file__).resolve().parents[1]


def test_package_imports() -> None:
    assert caseforge.__doc__


def test_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert caseforge.__version__ == pyproject["project"]["version"]
