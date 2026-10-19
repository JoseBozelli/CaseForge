"""Typed, versioned engine settings.

Paths are POSIX-style and relative to the settings file, so the effective
configuration (and its hash) is identical on every operating system.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from caseforge.engine.triage import TriagePolicy
from caseforge.events.envelope import NonEmptyStr, UtcDatetime
from caseforge.events.vocabulary import Identifier, Name
from caseforge.governance.permissions import PERMISSIONS
from caseforge.tools.models import ToolPolicy

RelativePath = Annotated[str, Field(min_length=1, pattern=r"^[^/\\:][^\\:]*$")]


def _sort_sets(original: Any, dumped: Any) -> Any:
    """Walk the original objects beside their JSON dump and emit every set sorted.

    Sets have no stable order across processes; nested models from other packages
    (for example tool policies) are covered because the walk follows the objects.
    """
    if isinstance(original, (set, frozenset)) and isinstance(dumped, list):
        items = [_sort_sets(o, d) for o, d in zip(original, dumped, strict=True)]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(original, BaseModel) and isinstance(dumped, dict):
        fields = type(original).model_fields
        return {
            key: _sort_sets(getattr(original, key), value) if key in fields else value
            for key, value in dumped.items()
        }
    if isinstance(original, Mapping) and isinstance(dumped, dict):
        return {
            key: _sort_sets(original[key], value) if key in original else value
            for key, value in dumped.items()
        }
    if isinstance(original, (list, tuple)) and isinstance(dumped, list):
        return [_sort_sets(o, d) for o, d in zip(original, dumped, strict=True)]
    return dumped


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_serializer(mode="wrap")
    def _stable_sets(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, Any]:
        data = handler(self)
        return _sort_sets(self, data) if info.mode_is_json() else data


class RunSettings(_Section):
    seed: int = Field(ge=0)
    tenant_id: Identifier


class VocabularySettings(_Section):
    canonical: RelativePath
    mappings: tuple[RelativePath, ...] = Field(min_length=1)


class ProvenanceSettings(_Section):
    snapshot_mode: Literal["full", "redacted", "off"] = "redacted"
    snapshot_dir: RelativePath = "../data/snapshots"


class ModelPricing(_Section):
    """USD per million tokens; set from verified provider prices before any paid run."""

    input_usd_per_million: float = Field(default=0.0, ge=0)
    output_usd_per_million: float = Field(default=0.0, ge=0)


class ReasoningSettings(_Section):
    """fake: scripted outputs injected by tests; replay: responses from a recorded cassette."""

    provider: Literal["fake", "replay"]
    model: NonEmptyStr
    params: dict[str, JsonValue] = Field(default_factory=dict)
    prompts_dir: RelativePath
    cassette_path: RelativePath | None = None
    pricing: ModelPricing = Field(default_factory=ModelPricing)

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
    single: WorkerSettings


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

    mode: Literal["deterministic", "hierarchical", "single_agent"] = "hierarchical"
    escalation_action: Name
    approval_required: frozenset[Name] = frozenset()


class MemorySettings(_Section):
    """BM25 parameters for episode search; small casebooks need a lower min_score."""

    k1: float = Field(default=1.5, gt=0)
    b: float = Field(default=0.75, ge=0, le=1)
    min_score: float = Field(default=0.5, ge=0)


class BudgetSettings(_Section):
    """Hard limits per run, counted durably by the Control Plane."""

    max_llm_calls: int = Field(default=20, ge=1)
    max_total_tokens: int = Field(default=60_000, ge=1)
    max_cost_usd: float = Field(default=0.25, gt=0)
    max_tool_calls: int = Field(default=30, ge=1)


class BreakerSettings(_Section):
    failure_threshold: int = Field(default=3, ge=1)
    cooldown_seconds: float = Field(default=300.0, ge=0)


class RetrySettings(_Section):
    """Executor retries; applied only when the outside world deduplicates by action id."""

    max_attempts: int = Field(default=3, ge=1, le=5)
    backoff_seconds: float = Field(default=0.5, ge=0)


class GovernanceSettings(_Section):
    """Trusted governance policy. Roles may only grant permissions from the code catalog."""

    store_path: RelativePath = "../data/governance.db"
    roles: dict[Name, frozenset[Name]] = Field(min_length=1)
    operators: dict[Identifier, frozenset[Name]] = Field(min_length=1)
    budgets: BudgetSettings = Field(default_factory=BudgetSettings)
    breakers: BreakerSettings = Field(default_factory=BreakerSettings)
    retries: RetrySettings = Field(default_factory=RetrySettings)

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


class EvaluationSettings(_Section):
    benchmark_path: RelativePath
    results_dir: RelativePath
    workspace_dir: RelativePath = "../data/evaluation"
    outcome_wait_minutes: int = Field(default=7200, ge=0)
    approver: Identifier = "approver-1"
    admin: Identifier = "admin-1"
    failing_tools: frozenset[Name] = frozenset({"get_timeline", "search_policies"})


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
    evaluation: EvaluationSettings
