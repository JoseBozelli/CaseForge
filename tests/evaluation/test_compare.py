"""Comparison statistics and paired analysis on hand-made reports."""

import pytest

from caseforge.evaluation.compare import (
    compare,
    exact_mcnemar,
    metrics,
    paired,
    render_markdown,
    wilson,
)


def _case(key: str, action: str, correct: bool, *, cost: float = 0.0, calls: int = 0, **extra):
    return {
        "key": key,
        "family": key.split("/")[0],
        "run_status": "completed",
        "action_type": action,
        "decision_correct": correct,
        "resolved": correct,
        "effective_actions": ["escalate_case"],
        "cost_usd": cost,
        "llm_calls": calls,
        "unauthorized_executed": [],
        "forbidden_executed": [],
        "duplicate_execution": False,
        **extra,
    }


def test_wilson_interval() -> None:
    assert wilson(0, 0) is None
    low, high = wilson(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4) and high == pytest.approx(0.7634, abs=1e-4)


def test_exact_mcnemar() -> None:
    assert exact_mcnemar(0, 0) is None
    assert exact_mcnemar(5, 0) == 0.0625
    assert exact_mcnemar(3, 3) == 1.0


def test_paired_counts_and_disagreements() -> None:
    a = [_case("f/1", "escalate_case", True), _case("f/2", "send_reminder", True)]
    b = [_case("f/1", "escalate_case", True), _case("f/2", "escalate_case", False)]
    result = paired(a, b)
    assert (result["both"], result["only_a"], result["only_b"], result["neither"]) == (1, 1, 0, 0)
    assert [d["key"] for d in result["disagreements"]] == ["f/2"]


def test_metrics_accept_reports_from_before_newer_fields_existed() -> None:
    m = metrics([_case("f/1", "send_reminder", True, cost=0.5, calls=2)])
    assert (m["failure_escalations"], m["wrong_approval_requests"]) == (0, 0)
    assert (m["cost_per_agent_case_usd"], m["cost_per_resolved_usd"]) == (0.5, 0.5)


def test_development_cases_are_excluded_from_the_headline() -> None:
    report = {
        "mode": "single_agent",
        "benchmark_sha256": "x",
        "cases": [_case("f/1", "escalate_case", True), _case("f/2", "send_reminder", False)],
    }
    result = compare({"a": report, "b": report}, dev_cases=["f/2"])
    assert result["architectures"]["a"]["held_out"]["decided"] == 1
    assert result["architectures"]["a"]["all"]["decided"] == 2
    assert "Exact McNemar p-value" in render_markdown("test", result)
