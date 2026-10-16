"""Typed, versioned engine settings.

Paths are POSIX-style and relative to the settings file, so the effective
configuration (and its hash) is identical on every operating system.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from caseforge.engine.triage import TriagePolicy
from caseforge.events.envelope import NonEmptyStr, UtcDatetime
from caseforge.events.vocabulary import Identifier, Name
from caseforge.governance.permissions import PERMISSIONS
from caseforge.tools.models import ToolPolicy

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
    snapshot_dir: RelativePath = "../data/snapshots"


class ReasoningSettings(_Section):
    """fake: scripted outputs injected by tests; replay: responses from a recorded cassette."""

    provider: Literal["fake", "replay"]
    model: NonEmptyStr
    params: dict[str, JsonValue] = Field(default_factory=dict)
    prompts_dir: RelativePath
    cassette_path: RelativePath | None = None

    @model_validator(mode="after")
    def _replay_needs_cassette(self) -> ReasoningSettings:
        if self.provider == "replay" and self.cassette_path is None:
            raise ValueError("the replay provider requires cassette_path")
        return self


class SupervisorSettings(_Section):
    plan_version: int = Field(ge=1)
    synthesis_version: int = Field(ge=1)
    max_clarification_rounds: int = Field(default=1, ge=0, le=3)
    allowed_actions: frozenset[Name] = Field(min_length=1)


class WorkerSettings(_Section):
    prompt_version: int = Field(ge=1)
    max_steps: int = Field(ge=1, le=10)


class AgentSettings(_Section):
    supervisor: SupervisorSettings
    evidence: WorkerSettings
    policy: WorkerSettings


class StorageSettings(_Section):
    records_path: RelativePath
    checkpoints_path: RelativePath


class SimulationSettings(_Section):
    families_dir: RelativePath
    store_path: RelativePath = "../data/simulation.db"
    start_at: UtcDatetime
    investigate_after_minutes: int = Field(ge=0)


class KnowledgeSettings(_Section):
    corpus_dir: RelativePath
    k1: float = Field(default=1.5, gt=0)
    b: float = Field(default=0.75, ge=0, le=1)
    min_score: float = Field(default=1.0, ge=0)


class EngineSettings(_Section):
    """deterministic: rules only (baseline). hierarchical: rule fast path, then agents."""

    mode: Literal["deterministic", "hierarchical"] = "hierarchical"
    escalation_action: Name
    approval_required: frozenset[Name] = frozenset()


class MemorySettings(_Section):
    """BM25 parameters for episode search; small casebooks need a lower min_score."""

    k1: float = Field(default=1.5, gt=0)
    b: float = Field(default=0.75, ge=0, le=1)
    min_score: float = Field(default=0.5, ge=0)


class GovernanceSettings(_Section):
    """Trusted governance policy. Roles may only grant permissions from the code catalog."""

    store_path: RelativePath = "../data/governance.db"
    roles: dict[Name, frozenset[Name]] = Field(min_length=1)
    operators: dict[Identifier, frozenset[Name]] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_references(self) -> GovernanceSettings:
        granted = {p for permissions in self.roles.values() for p in permissions}
        unknown_permissions = sorted(granted - PERMISSIONS)
        if unknown_permissions:
            raise ValueError(f"roles grant unknown permissions {unknown_permissions}")
        assigned = {r for roles in self.operators.values() for r in roles}
        undefined_roles = sorted(assigned - self.roles.keys())
        if undefined_roles:
            raise ValueError(f"operators reference undefined roles {undefined_roles}")
        return self


class Settings(_Section):
    """Root settings document. Secrets never belong here."""

    settings_version: Literal[1]
    run: RunSettings
    vocabulary: VocabularySettings
    provenance: ProvenanceSettings = Field(default_factory=ProvenanceSettings)
    storage: StorageSettings
    simulation: SimulationSettings
    triage: TriagePolicy
    tools: dict[Name, ToolPolicy] = Field(default_factory=dict)
    knowledge: KnowledgeSettings
    memory: MemorySettings = Field(default_factory=MemorySettings)
    reasoning: ReasoningSettings
    agents: AgentSettings
    engine: EngineSettings
    governance: GovernanceSettings
