"""Typed, versioned engine settings.

Paths are POSIX-style and relative to the settings file, so the effective
configuration (and its hash) is identical on every operating system.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from caseforge.engine.triage import TriagePolicy
from caseforge.events.envelope import UtcDatetime
from caseforge.events.vocabulary import Identifier

RelativePath = Annotated[str, Field(min_length=1, pattern=r"^[^/\\:][^\\:]*$")]


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunSettings(_Section):
    seed: int = Field(ge=0)
    tenant_id: Identifier


class VocabularySettings(_Section):
    canonical: RelativePath
    mappings: tuple[RelativePath, ...] = Field(min_length=1)


class ProvenanceSettings(_Section):
    snapshot_mode: Literal["full", "redacted", "off"] = "redacted"


class StorageSettings(_Section):
    records_path: RelativePath
    checkpoints_path: RelativePath


class SimulationSettings(_Section):
    families_dir: RelativePath
    start_at: UtcDatetime
    investigate_after_minutes: int = Field(ge=0)


class Settings(_Section):
    """Root settings document. Secrets never belong here."""

    settings_version: Literal[1]
    run: RunSettings
    vocabulary: VocabularySettings
    provenance: ProvenanceSettings = Field(default_factory=ProvenanceSettings)
    storage: StorageSettings
    simulation: SimulationSettings
    triage: TriagePolicy
