"""Tests for run manifests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.provenance.manifest import GitState, build_run_manifest, read_git_state
from caseforge.settings.loader import load_settings

CREATED_AT = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
GIT = GitState(commit="a" * 40, dirty=False)
ROOT = Path(__file__).resolve().parents[2]


def _manifest(settings_path: Path, environ=None, **kwargs):
    loaded = load_settings(settings_path, environ=environ or {})
    return build_run_manifest(
        loaded,
        run_id="run-0001",
        created_at=CREATED_AT,
        project_root=settings_path.parent.parent,
        git=GIT,
        **kwargs,
    )


def test_manifest_records_versions_and_files(config_copy) -> None:
    manifest = _manifest(config_copy)
    assert (manifest.seed, manifest.tenant_id) == (20261015, "tenant-demo")
    assert manifest.vocabulary == "caseforge-canonical@1"
    assert manifest.mappings == ("sim-generic@1",)
    assert manifest.git_commit == "a" * 40
    assert [f.path for f in manifest.files] == [
        "config/caseforge.yaml",
        "config/simulation/families/missing_document.v1.yaml",
        "config/simulation/families/routine_stalled_task.v1.yaml",
        "config/vocabulary/canonical.v1.yaml",
        "config/vocabulary/mappings/sim.v1.yaml",
    ]


def test_manifest_is_deterministic(config_copy) -> None:
    first, second = _manifest(config_copy), _manifest(config_copy)
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.sha256() == second.sha256()


def test_override_changes_effective_config_hash(config_copy) -> None:
    base = _manifest(config_copy)
    overridden = _manifest(config_copy, environ={"CASEFORGE__RUN__SEED": "7"})
    assert overridden.effective_config_sha256 != base.effective_config_sha256
    assert overridden.config_overrides == ("run.seed",)
    assert overridden.effective_config["run"]["seed"] == 7


def test_file_change_changes_only_its_fingerprint(config_copy) -> None:
    before = {f.path: f.sha256 for f in _manifest(config_copy).files}
    vocabulary = config_copy.parent / "vocabulary" / "canonical.v1.yaml"
    vocabulary.write_text(vocabulary.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    after = {f.path: f.sha256 for f in _manifest(config_copy).files}
    assert (
        before["config/vocabulary/canonical.v1.yaml"]
        != after["config/vocabulary/canonical.v1.yaml"]
    )
    assert before["config/caseforge.yaml"] == after["config/caseforge.yaml"]


def test_extra_files_recorded(config_copy) -> None:
    lockfile = config_copy.parent.parent / "uv.lock"
    lockfile.write_text("lock\n", encoding="utf-8")
    manifest = _manifest(config_copy, extra_files=(lockfile,))
    assert "uv.lock" in [f.path for f in manifest.files]


def test_file_outside_root_rejected(config_copy, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("elsewhere") / "x.txt"
    outside.write_text("x\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="outside"):
        _manifest(config_copy, extra_files=(outside,))


def test_manifest_contains_no_absolute_paths(config_copy) -> None:
    text = _manifest(config_copy).to_json_bytes().decode("utf-8")
    assert config_copy.parent.parent.name not in text


def test_git_state_inside_repository() -> None:
    state = read_git_state(ROOT)
    assert state.commit is None or len(state.commit) == 40


def test_git_state_outside_repository(tmp_path) -> None:
    assert read_git_state(tmp_path) == GitState(commit=None, dirty=None)
