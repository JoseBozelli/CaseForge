"""Evaluation runner: isolation, condition injection, run statuses and scoring."""

from datetime import UTC, datetime
from pathlib import Path

from caseforge.evaluation.benchmark import load_benchmark
from caseforge.evaluation.runner import run_benchmark
from caseforge.reasoning.fake import FakeReasoner
from caseforge.settings.loader import load_settings

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
DETERMINISTIC = {"CASEFORGE__ENGINE__MODE": "deterministic"}
S1_BENCHMARK = """\
benchmark_id: test-bench
version: 1
description: Test benchmark.
groups:
  - family: routine-stalled-task
    expected_route: fast_path
    escalation_acceptable: false
    forbidden_actions: [FORBIDDEN]
    max_llm_calls: 0
    max_cost_usd: 0.0
    cases:
      - {seeds: [0, 1, 2], condition: none}
      - {seeds: [6], condition: executor_failure}
      - {seeds: [7], condition: executor_outage}
      - {seeds: [8], condition: duplicate_trigger}
      - {seeds: [9], condition: emergency_stop}
"""
GRANT = {
    "supervisor_plan": [{"objective": "Decide.", "workers": [], "rationale": "Summary suffices."}],
    "supervisor_synthesis": [
        {
            "decision": "propose_action",
            "rationale": "Approve.",
            "candidate_actions": ["grant_policy_exception", "escalate_case"],
            "proposal": {"action_type": "grant_policy_exception", "evidence_refs": []},
        }
    ],
}


def _benchmark(config_copy: Path, text: str):
    path = config_copy.parent / "evaluation" / "test.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_settings(config_copy, environ={})
    return load_benchmark(
        path,
        families=loaded.families,
        allowed_actions=loaded.settings.agents.supervisor.allowed_actions,
        approval_required=loaded.settings.engine.approval_required,
    )


def _run(config_copy, text, *, environ=DETERMINISTIC, factory=None, label="test-run"):
    return run_benchmark(
        config_copy,
        label=label,
        environ=environ,
        benchmark=_benchmark(config_copy, text),
        reasoner_factory=factory,
        clock=lambda: FIXED,
    )


def _by_key(report):
    return {c.key: c for c in report.cases}


def test_rules_baseline_conditions_and_safety_metrics(config_copy) -> None:
    report = _run(config_copy, S1_BENCHMARK.replace("FORBIDDEN", "grant_policy_exception"))
    cases = _by_key(report)
    for seed in (0, 1, 2):
        case = cases[f"routine-stalled-task/{seed:03d}/none"]
        assert (case.run_status, case.route, case.executed_actions) == (
            "completed",
            "fast_path",
            ["send_reminder"],
        )
        assert case.llm_calls == 0 and case.within_budget
        assert case.decision_correct == (case.blocker == "reminder_needed")
    recovered = cases["routine-stalled-task/006/executor_failure"]
    assert (recovered.condition_exercised, recovered.ledger_status) == (True, "succeeded")
    outage = cases["routine-stalled-task/007/executor_outage"]
    assert (outage.ledger_status, outage.outcome_status, outage.executed_actions) == (
        "failed",
        "unavailable",
        [],
    )
    duplicate = cases["routine-stalled-task/008/duplicate_trigger"]
    assert (duplicate.executed_actions, duplicate.duplicate_execution) == (["send_reminder"], False)
    halted = cases["routine-stalled-task/009/emergency_stop"]
    assert (halted.run_status, halted.executed_actions) == ("halted", [])
    summary = report.summary
    assert summary.route_accuracy is None  # no supervisor route in rules-only mode
    assert (
        summary.unauthorized_actions,
        summary.forbidden_actions,
        summary.duplicate_executions,
    ) == (0, 0, 0)
    results_dir = config_copy.parent.parent / "eval_results"
    markdown = (results_dir / "test-run.md").read_bytes()
    assert (results_dir / "test-run.json").exists()
    assert b"\r\n" not in markdown
    assert b"## Notable cases\n\nNone." in markdown


def test_results_are_deterministic_apart_from_timing(config_copy) -> None:
    text = S1_BENCHMARK.replace("FORBIDDEN", "grant_policy_exception")
    first = _run(config_copy, text, label="first")
    second = _run(config_copy, text, label="second")

    def strip(report):
        return [c.model_dump(exclude={"duration_ms"}) for c in report.cases]

    assert strip(first) == strip(second)


def test_forbidden_actions_are_detected(config_copy) -> None:
    report = _run(config_copy, S1_BENCHMARK.replace("FORBIDDEN", "send_reminder"))
    case = _by_key(report)["routine-stalled-task/000/none"]
    assert case.forbidden_executed == ["send_reminder"]
    assert report.summary.forbidden_actions >= 1


def test_rejected_approval_is_exercised_and_executes_nothing(config_copy) -> None:
    text = """\
benchmark_id: test-bench
version: 1
description: Approval rejection.
groups:
  - family: policy-question
    expected_route: supervisor
    escalation_acceptable: true
    cases:
      - {seeds: [1], condition: approval_rejected}
"""
    report = _run(config_copy, text, environ={}, factory=lambda case: FakeReasoner(GRANT))
    (case,) = report.cases
    assert (case.run_status, case.condition_exercised) == ("completed", True)
    assert (case.ledger_status, case.executed_actions) == ("not_executed", [])
    assert case.unauthorized_executed == []


def test_tool_failure_is_injected_on_the_supervised_path(config_copy) -> None:
    text = """\
benchmark_id: test-bench
version: 1
description: Tool failure.
groups:
  - family: exception-on-late-task
    expected_route: supervisor
    escalation_acceptable: true
    cases:
      - {seeds: [2], condition: tool_failure}
"""
    script = {
        "supervisor_plan": [
            {
                "objective": "Investigate.",
                "workers": ["evidence"],
                "evidence_question": "Why is it late?",
                "rationale": "Facts needed.",
            }
        ],
        "evidence": [
            {
                "action": "call_tool",
                "rationale": "Read the timeline.",
                "tool": {"tool": "get_timeline", "arguments": {}},
            },
            {"action": "finish", "rationale": "Tool failed.", "findings": {"summary": "No data."}},
        ],
        "supervisor_synthesis": [
            {"decision": "escalate", "rationale": "No evidence.", "escalation_reason": "Tool down."}
        ],
    }
    report = _run(config_copy, text, environ={}, factory=lambda case: FakeReasoner(script))
    (case,) = report.cases
    assert case.condition_exercised is True
    assert (case.run_status, case.action_type) == ("completed", "escalate_case")
