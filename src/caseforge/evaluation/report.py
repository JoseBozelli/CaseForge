"""Evaluation results: per-case run status and scores, summaries, and written reports."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

RunStatus = Literal["completed", "awaiting_approval", "halted", "failed"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CaseResult(_Model):
    key: str
    family: str
    seed: int
    condition: str
    condition_exercised: bool
    run_status: RunStatus
    error: str | None = None
    route: str | None = None
    decision_source: str | None = None
    action_type: str | None = None
    ledger_status: str | None = None
    outcome_status: str | None = None
    blocker: str
    effective_actions: list[str]
    executed_actions: list[str]
    route_ok: bool | None  # None: not applicable in rules-only mode
    decision_correct: bool
    decision_acceptable: bool
    resolved: bool
    forbidden_executed: list[str]
    unauthorized_executed: list[str]
    duplicate_execution: bool
    llm_calls: int
    total_tokens: int
    cost_usd: float
    tool_calls: int
    within_budget: bool
    duration_ms: int


class Summary(_Model):
    cases: int
    run_status: dict[str, int]
    route_accuracy: float | None
    decision_accuracy: float | None
    acceptable_rate: float | None
    resolution_rate: float | None
    unauthorized_actions: int
    forbidden_actions: int
    duplicate_executions: int
    conditions_not_exercised: list[str]
    within_budget_rate: float
    total_cost_usd: float
    cost_per_resolved_usd: float | None
    by_family: dict[str, dict[str, float | int | None]]


class EvaluationReport(_Model):
    report_version: Literal["evaluation-report.v1"] = "evaluation-report.v1"
    label: str
    mode: str
    benchmark_id: str
    benchmark_version: int
    benchmark_sha256: str
    config_sha256: str
    git_commit: str | None
    git_dirty: bool | None = None
    created_at: str
    cases: list[CaseResult]
    summary: Summary


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarize(results: Sequence[CaseResult]) -> Summary:
    completed = [r for r in results if r.run_status == "completed"]
    decided = [r for r in completed if r.action_type is not None]
    routed = [r for r in results if r.route_ok is not None]
    resolved = sum(r.resolved for r in completed)
    total_cost = round(sum(r.cost_usd for r in results), 6)
    by_family: dict[str, dict[str, float | int | None]] = {}
    groups: dict[str, list[CaseResult]] = defaultdict(list)
    for result in results:
        groups[result.family].append(result)
    for family, items in sorted(groups.items()):
        family_completed = [r for r in items if r.run_status == "completed"]
        family_decided = [r for r in family_completed if r.action_type is not None]
        by_family[family] = {
            "cases": len(items),
            "completed": len(family_completed),
            "decision_accuracy": _rate(
                sum(r.decision_correct for r in family_decided), len(family_decided)
            ),
            "resolution_rate": _rate(
                sum(r.resolved for r in family_completed), len(family_completed)
            ),
            "llm_calls": sum(r.llm_calls for r in items),
        }
    return Summary(
        cases=len(results),
        run_status=dict(sorted(Counter(r.run_status for r in results).items())),
        route_accuracy=_rate(sum(bool(r.route_ok) for r in routed), len(routed)),
        decision_accuracy=_rate(sum(r.decision_correct for r in decided), len(decided)),
        acceptable_rate=_rate(sum(r.decision_acceptable for r in decided), len(decided)),
        resolution_rate=_rate(resolved, len(completed)),
        unauthorized_actions=sum(len(r.unauthorized_executed) for r in results),
        forbidden_actions=sum(len(r.forbidden_executed) for r in results),
        duplicate_executions=sum(r.duplicate_execution for r in results),
        conditions_not_exercised=sorted(r.key for r in results if not r.condition_exercised),
        within_budget_rate=_rate(sum(r.within_budget for r in results), len(results)) or 0.0,
        total_cost_usd=total_cost,
        cost_per_resolved_usd=round(total_cost / resolved, 6) if resolved else None,
        by_family=by_family,
    )


def write_report(report: EvaluationReport, results_dir: Path) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / f"{report.label}.json"
    md_path = results_dir / f"{report.label}.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    return json_path, md_path


def _fmt(value: float | int | None) -> str:
    return "n/a" if value is None else str(value)


def render_markdown(report: EvaluationReport) -> str:
    s = report.summary
    lines = [
        f"# Evaluation: {report.label}",
        "",
        f"- Mode: `{report.mode}`",
        f"- Benchmark: `{report.benchmark_id}` v{report.benchmark_version} "
        f"(sha256 `{report.benchmark_sha256[:12]}`)",
        f"- Configuration sha256: `{report.config_sha256[:12]}`",
        f"- Git commit: `{(report.git_commit or 'unknown')[:12]}`"
        + (" (uncommitted changes present)" if report.git_dirty else ""),
        "- Outcomes are synthetic: they measure decisions inside the simulator, "
        "not real-world effects.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases | {s.cases} |",
        f"| Run status | {', '.join(f'{k}: {v}' for k, v in s.run_status.items())} |",
        f"| Route accuracy | {_fmt(s.route_accuracy)} |",
        f"| Decision accuracy | {_fmt(s.decision_accuracy)} |",
        f"| Acceptable decisions | {_fmt(s.acceptable_rate)} |",
        f"| Resolution rate | {_fmt(s.resolution_rate)} |",
        f"| Unauthorized actions | {s.unauthorized_actions} |",
        f"| Forbidden actions | {s.forbidden_actions} |",
        f"| Duplicate executions | {s.duplicate_executions} |",
        f"| Conditions not exercised | {len(s.conditions_not_exercised)} |",
        f"| Within budget | {_fmt(s.within_budget_rate)} |",
        f"| Total cost (USD) | {_fmt(s.total_cost_usd)} |",
        f"| Cost per resolved case (USD) | {_fmt(s.cost_per_resolved_usd)} |",
        "",
        "## By family",
        "",
        "| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |",
        "|---|---|---|---|---|---|",
    ]
    for family, row in s.by_family.items():
        lines.append(
            f"| {family} | {row['cases']} | {row['completed']} | "
            f"{_fmt(row['decision_accuracy'])} | {_fmt(row['resolution_rate'])} | "
            f"{row['llm_calls']} |"
        )
    notable = [
        r
        for r in report.cases
        if r.run_status == "failed"
        or r.route_ok is False
        or r.forbidden_executed
        or r.unauthorized_executed
        or r.duplicate_execution
        or not r.within_budget
    ]
    lines += ["", "## Notable cases", ""]
    if not notable:
        lines.append("None.")
    for r in notable:
        lines.append(
            f"- `{r.key}`: status {r.run_status}, route {r.route}, action {r.action_type}, "
            f"forbidden {r.forbidden_executed}, unauthorized {r.unauthorized_executed}, "
            f"duplicate {r.duplicate_execution}, within budget {r.within_budget}"
        )
    lines += ["", "## Conditions not exercised", ""]
    lines += [f"- `{key}`" for key in s.conditions_not_exercised] or ["None."]
    return "\n".join(lines) + "\n"
