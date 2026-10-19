"""Versioned benchmark: cases (family x seed x injected condition) with fixed expectations.

Expectations are written before any evaluation runs. The correct action for each case is
deliberately absent: evaluation reads it from the simulator's ground truth.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from caseforge.common.errors import ConfigError
from caseforge.common.hashing import file_sha256
from caseforge.common.yaml_io import load_yaml_mapping
from caseforge.events.envelope import NonEmptyStr
from caseforge.events.vocabulary import Identifier, Name
from caseforge.simulation.spec import ScenarioFamily

Condition = Literal[
    "none",
    "tool_failure",
    "executor_failure",
    "executor_outage",
    "duplicate_trigger",
    "approval_rejected",
    "emergency_stop",
]
CONDITIONS: Final = frozenset(Condition.__args__)  # type: ignore[attr-defined]
Route = Literal["fast_path", "supervisor", "any"]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GroupCases(_Strict):
    seeds: tuple[int, ...] = Field(min_length=1)
    condition: Condition


class CaseGroup(_Strict):
    family: Identifier
    expected_route: Route
    escalation_acceptable: bool
    forbidden_actions: frozenset[Name] = frozenset()
    max_llm_calls: int = Field(default=20, ge=0)
    max_cost_usd: float = Field(default=0.25, ge=0)
    cases: tuple[GroupCases, ...] = Field(min_length=1)


class BenchmarkFile(_Strict):
    benchmark_id: Identifier
    version: int = Field(ge=1)
    description: NonEmptyStr
    groups: tuple[CaseGroup, ...] = Field(min_length=1)


@dataclass(frozen=True)
class BenchmarkCase:
    key: str
    family: str
    seed: int
    condition: str
    expected_route: str
    escalation_acceptable: bool
    forbidden_actions: frozenset[str]
    max_llm_calls: int
    max_cost_usd: float


@dataclass(frozen=True)
class Benchmark:
    benchmark_id: str
    version: int
    sha256: str
    cases: tuple[BenchmarkCase, ...]


def _expand(groups: Iterable[CaseGroup]) -> tuple[BenchmarkCase, ...]:
    return tuple(
        BenchmarkCase(
            key=f"{group.family}/{seed:03d}/{entry.condition}",
            family=group.family,
            seed=seed,
            condition=entry.condition,
            expected_route=group.expected_route,
            escalation_acceptable=group.escalation_acceptable,
            forbidden_actions=group.forbidden_actions,
            max_llm_calls=group.max_llm_calls,
            max_cost_usd=group.max_cost_usd,
        )
        for group in groups
        for entry in group.cases
        for seed in entry.seeds
    )


def load_benchmark(
    path: str | Path,
    *,
    families: Iterable[ScenarioFamily],
    allowed_actions: frozenset[str],
    approval_required: frozenset[str],
) -> Benchmark:
    """Load, expand and validate a benchmark against the configured families and actions."""
    path = Path(path)
    try:
        spec = BenchmarkFile.model_validate(load_yaml_mapping(path))
    except ValidationError as exc:
        raise ConfigError(f"invalid benchmark in {path}:\n{exc}") from exc
    by_id: Mapping[str, ScenarioFamily] = {f.family_id: f for f in families}
    cases = _expand(spec.groups)

    problems: list[str] = []
    for group in spec.groups:
        family = by_id.get(group.family)
        if family is None:
            problems.append(f"unknown family {group.family!r}")
            continue
        not_allowed = sorted(group.forbidden_actions - allowed_actions)
        if not_allowed:
            problems.append(
                f"{group.family}: forbidden actions not in allowed actions {not_allowed}"
            )
        possible = set(family.dynamics.actions) if family.dynamics else set()
        if any(c.condition == "approval_rejected" for c in group.cases) and not (
            possible & approval_required
        ):
            problems.append(
                f"{group.family}: approval_rejected needs a possible action that requires approval"
            )
    duplicates = sorted(k for k, n in Counter(c.key for c in cases).items() if n > 1)
    if duplicates:
        problems.append(f"duplicate benchmark cases {duplicates}")
    if problems:
        raise ConfigError(f"benchmark {path.name} is inconsistent: " + "; ".join(problems))

    return Benchmark(
        benchmark_id=spec.benchmark_id,
        version=spec.version,
        sha256=file_sha256(path),
        cases=cases,
    )
