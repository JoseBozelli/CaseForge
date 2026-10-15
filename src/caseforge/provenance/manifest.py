"""Run manifests: the versions, settings and file fingerprints behind one execution."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue

import caseforge
from caseforge.common.errors import ConfigError
from caseforge.common.hashing import canonical_json_bytes, file_sha256, sha256_hex
from caseforge.events.envelope import NonEmptyStr, Sha256Hex, UtcDatetime
from caseforge.settings.loader import LoadedSettings


@dataclass(frozen=True)
class GitState:
    commit: str | None
    dirty: bool | None


def read_git_state(root: Path) -> GitState:
    """Return the current commit and working-tree state, or unknowns outside Git."""

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True, timeout=10
        ).stdout

    try:
        commit = _git("rev-parse", "HEAD").strip()
        dirty = bool(_git("status", "--porcelain").strip())
    except (OSError, subprocess.SubprocessError):
        return GitState(commit=None, dirty=None)
    return GitState(commit=commit, dirty=dirty)


class FileFingerprint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: NonEmptyStr
    sha256: Sha256Hex


class RunManifest(BaseModel):
    """Everything required to explain or reproduce a run's configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: Literal["run-manifest.v1"] = "run-manifest.v1"
    serialization: Literal["canonical-json-v1"] = "canonical-json-v1"
    file_fingerprint: Literal["sha256-lf-v1"] = "sha256-lf-v1"
    run_id: NonEmptyStr
    created_at: UtcDatetime
    seed: int
    tenant_id: NonEmptyStr
    caseforge_version: NonEmptyStr
    python_version: NonEmptyStr
    git_commit: str | None
    git_dirty: bool | None
    settings_version: int
    effective_config: dict[str, JsonValue]
    effective_config_sha256: Sha256Hex
    config_overrides: tuple[str, ...]
    vocabulary: NonEmptyStr
    mappings: tuple[NonEmptyStr, ...]
    files: tuple[FileFingerprint, ...]

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    def sha256(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))


def _relative_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ConfigError(f"{path.name} is outside the project root") from exc


def build_run_manifest(
    loaded: LoadedSettings,
    *,
    run_id: str,
    created_at: datetime,
    project_root: str | Path,
    extra_files: Iterable[str | Path] = (),
    git: GitState | None = None,
) -> RunManifest:
    """Build a manifest; paths are recorded relative to project_root in POSIX form."""
    root = Path(project_root)
    git_state = read_git_state(root) if git is None else git
    paths = (*loaded.config_files, *(Path(item) for item in extra_files))
    files = sorted(
        (FileFingerprint(path=_relative_posix(p, root), sha256=file_sha256(p)) for p in paths),
        key=lambda fingerprint: fingerprint.path,
    )
    settings = loaded.settings
    effective = settings.model_dump(mode="json")
    vocabulary = loaded.vocabulary
    return RunManifest(
        run_id=run_id,
        created_at=created_at,
        seed=settings.run.seed,
        tenant_id=settings.run.tenant_id,
        caseforge_version=caseforge.__version__,
        python_version=platform.python_version(),
        git_commit=git_state.commit,
        git_dirty=git_state.dirty,
        settings_version=settings.settings_version,
        effective_config=effective,
        effective_config_sha256=sha256_hex(effective),
        config_overrides=loaded.overrides,
        vocabulary=f"{vocabulary.vocabulary_id}@{vocabulary.version}",
        mappings=tuple(f"{m.mapping_id}@{m.mapping_version}" for m in loaded.mappings),
        files=tuple(files),
    )
