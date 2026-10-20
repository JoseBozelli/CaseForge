"""Confirmatory statistics and the registered decision rule."""

from pathlib import Path

import pytest

from caseforge.evaluation.benchmark import load_benchmark
from caseforge.evaluation.compare import newcombe_paired, one_sided_mcnemar
from caseforge.evaluation.confirm import analyse
from caseforge.settings.loader import load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_one_sided_mcnemar() -> None:
    assert one_sided_mcnemar(0, 0) is None
    assert one_sided_mcnemar(5, 0) == 0.0312
    assert one_sided_mcnemar(3, 3) == pytest.approx(0.6562, abs=1e-4)


def test_newcombe_interval_properties() -> None:
    d, low, high = newcombe_paired(30, 8, 2, 10)
    assert low < d < high and d == pytest.approx(0.12)
    mirrored = newcombe_paired(30, 2, 8, 10)
    assert mirrored == pytest.approx((-d, -high, -low), abs=1e-4)
    d0, low0, high0 = newcombe_paired(40, 0, 0, 10)
    assert d0 == 0 and low0 < 0 < high0


def _report(label: str, correct: list[bool]) -> dict:
    return {
        "label": label,
        "cases": [
            {
                "key": f"f/{i}",
                "family": "f",
                "run_status": "completed",
                "action_type": "escalate_case",
                "decision_correct": ok,
                "resolved": ok,
                "effective_actions": ["escalate_case"],
                "cost_usd": 0.0,
                "llm_calls": 1,
                "unauthorized_executed": [],
                "forbidden_executed": [],
                "duplicate_execution": False,
            }
            for i, ok in enumerate(correct)
        ],
    }


def test_registered_decision_rule() -> None:
    rules = _report("rules", [True] * 60 + [False] * 40)
    cheap = _report("cheap", [True] * 60 + [True] * 12 + [False] * 28)
    strong = _report("strong", [True] * 60 + [True] * 14 + [False] * 26)
    result = analyse(rules, cheap, strong)
    assert result["h1"]["supported"] and result["h2"]["supported"]
    assert result["decision"].startswith("Recommend the cheap configuration")

    weak = _report("weak", [True] * 60 + [True] * 1 + [False] * 39)
    result = analyse(rules, weak, strong)
    assert not result["h1"]["supported"] and not result["h2"]["supported"]


def test_confirmatory_benchmark_has_120_new_unconditioned_cases() -> None:
    loaded = load_settings(ROOT / "config" / "caseforge.yaml", environ={})
    s = loaded.settings
    benchmark = load_benchmark(
        ROOT / "config" / "evaluation" / "benchmark.v2-confirm.yaml",
        families=loaded.families,
        allowed_actions=s.agents.supervisor.allowed_actions,
        approval_required=s.engine.approval_required,
    )
    assert len(benchmark.cases) == 120
    assert {c.condition for c in benchmark.cases} == {"none"}
    assert min(c.seed for c in benchmark.cases) == 10
