"""Compare saved evaluation reports: accuracy with intervals, paired tests, families, cost.

Reads report JSON files only; nothing is re-run. Development cases (used to shape prompts)
are excluded from the headline and reported alongside.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _wilson_bounds(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion; suited to small samples."""
    if n == 0:
        return None
    low, high = _wilson_bounds(successes, n, z)
    return (round(low, 4), round(high, 4))


def exact_mcnemar(only_a: int, only_b: int) -> float | None:
    """Two-sided exact McNemar p-value from the discordant pairs."""
    n = only_a + only_b
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2**n
    return round(min(1.0, 2 * tail), 4)


def one_sided_mcnemar(favouring: int, against: int) -> float | None:
    """Exact one-sided p-value that the first configuration is better (discordant pairs)."""
    n = favouring + against
    if n == 0:
        return None
    return round(sum(math.comb(n, i) for i in range(favouring, n + 1)) / 2**n, 4)


def newcombe_paired(
    both: int, only_a: int, only_b: int, neither: int, z: float = 1.96
) -> tuple[float, float, float] | None:
    """Accuracy difference (A minus B) on paired cases with its 95% interval.

    Newcombe (1998), method 10: built from Wilson intervals with a correlation correction.
    """
    n = both + only_a + only_b + neither
    if n == 0:
        return None
    p1, p2 = (both + only_a) / n, (both + only_b) / n
    l1, u1 = _wilson_bounds(both + only_a, n, z)
    l2, u2 = _wilson_bounds(both + only_b, n, z)
    product = (both + only_a) * (only_b + neither) * (both + only_b) * (only_a + neither)
    phi = 0.0 if product == 0 else (both * neither - only_a * only_b) / math.sqrt(product)
    delta = math.sqrt(max((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2, 0.0))
    eps = math.sqrt(max((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2, 0.0))
    difference = p1 - p2
    return (round(difference, 4), round(difference - delta, 4), round(difference + eps, 4))


def format_p(value: float | None) -> str:
    """p-values are rounded to 4 decimals; anything that rounds below that shows as < 0.0001."""
    if value is None:
        return "n/a"
    return "< 0.0001" if value < 0.0001 else str(value)


def _decided(case: dict[str, Any]) -> bool:
    return case["run_status"] == "completed" and case.get("action_type") is not None


def metrics(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    completed = [c for c in cases if c["run_status"] == "completed"]
    decided = [c for c in completed if _decided(c)]
    correct = sum(bool(c["decision_correct"]) for c in decided)
    resolved = sum(bool(c["resolved"]) for c in completed)
    cost = round(sum(c["cost_usd"] for c in cases), 6)
    agent_path = [c for c in cases if c.get("llm_calls", 0) > 0]
    return {
        "cases": len(cases),
        "decided": len(decided),
        "decision_accuracy": _rate(correct, len(decided)),
        "accuracy_ci95": wilson(correct, len(decided)),
        "resolution_rate": _rate(resolved, len(completed)),
        "failure_escalations": sum(bool(c.get("failure_escalation")) for c in cases),
        "approval_requests": sum(bool(c.get("approval_requested")) for c in cases),
        "wrong_approval_requests": sum(bool(c.get("wrong_approval_request")) for c in cases),
        "unauthorized": sum(len(c["unauthorized_executed"]) for c in cases),
        "forbidden": sum(len(c["forbidden_executed"]) for c in cases),
        "duplicates": sum(bool(c["duplicate_execution"]) for c in cases),
        "llm_calls": sum(c.get("llm_calls", 0) for c in cases),
        "agent_path_cases": len(agent_path),
        "total_cost_usd": cost,
        "cost_per_agent_case_usd": round(cost / len(agent_path), 4) if agent_path else None,
        "cost_per_resolved_usd": round(cost / resolved, 4) if resolved else None,
    }


def paired(a_cases: Sequence[dict[str, Any]], b_cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    a = {c["key"]: c for c in a_cases if _decided(c)}
    b = {c["key"]: c for c in b_cases if _decided(c)}
    keys = sorted(a.keys() & b.keys())
    counts = {"both": 0, "only_a": 0, "only_b": 0, "neither": 0}
    for key in keys:
        ra, rb = bool(a[key]["decision_correct"]), bool(b[key]["decision_correct"])
        counts["both" if ra and rb else "only_a" if ra else "only_b" if rb else "neither"] += 1
    disagreements = [
        {
            "key": key,
            "a_action": a[key]["action_type"],
            "b_action": b[key]["action_type"],
            "effective": a[key]["effective_actions"],
            "a_correct": bool(a[key]["decision_correct"]),
            "b_correct": bool(b[key]["decision_correct"]),
        }
        for key in keys
        if a[key]["action_type"] != b[key]["action_type"]
    ]
    return {
        "cases": len(keys),
        **counts,
        "p_value": exact_mcnemar(counts["only_a"], counts["only_b"]),
        "disagreements": disagreements,
    }


def compare(reports: dict[str, dict[str, Any]], dev_cases: Sequence[str]) -> dict[str, Any]:
    dev = set(dev_cases)
    result: dict[str, Any] = {"dev_cases": sorted(dev), "architectures": {}, "pairs": []}
    held_out: dict[str, list[dict[str, Any]]] = {}
    for label, report in reports.items():
        cases = report["cases"]
        held_out[label] = [c for c in cases if c["key"] not in dev]
        families = sorted({c["family"] for c in cases})
        result["architectures"][label] = {
            "mode": report["mode"],
            "reasoner": report.get("reasoner", ""),
            "benchmark_sha256": report["benchmark_sha256"],
            "git_commit": report.get("git_commit"),
            "held_out": metrics(held_out[label]),
            "all": metrics(cases),
            "by_family": {
                f: metrics([c for c in held_out[label] if c["family"] == f]) for f in families
            },
        }
    for a, b in itertools.combinations(reports, 2):
        result["pairs"].append({"a": a, "b": b, **paired(held_out[a], held_out[b])})
    return result


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (list, tuple)):
        return f"[{value[0]}, {value[1]}]"
    return str(value)


def render_markdown(name: str, result: dict[str, Any]) -> str:
    archs = result["architectures"]
    labels = list(archs)
    rows = [
        ("Decided cases", "decided"),
        ("Decision accuracy", "decision_accuracy"),
        ("95% interval", "accuracy_ci95"),
        ("Resolution rate", "resolution_rate"),
        ("Failure escalations", "failure_escalations"),
        ("Wrong / total approval requests", None),
        ("Unauthorized / forbidden / duplicate", None),
        ("Model calls", "llm_calls"),
        ("Total cost (USD)", "total_cost_usd"),
        ("Cost per agent-path case (USD)", "cost_per_agent_case_usd"),
        ("Cost per resolved case (USD)", "cost_per_resolved_usd"),
    ]

    def cell(m: dict[str, Any], title: str, key: str | None) -> str:
        if title.startswith("Wrong"):
            return f"{m['wrong_approval_requests']} / {m['approval_requests']}"
        if title.startswith("Unauthorized"):
            return f"{m['unauthorized']} / {m['forbidden']} / {m['duplicates']}"
        return _fmt(m[key])

    lines = [
        f"# Comparison: {name}",
        "",
        "Outcomes are synthetic; results measure decisions inside the simulator. The evaluation "
        "approver approves every request. Intervals are 95% Wilson intervals; paired tests are "
        "exact McNemar tests on cases both architectures decided.",
        "",
        "Cases excluded from the held-out results (development cases, plus any post-hoc "
        f"exclusions explained with this report): {', '.join(result['dev_cases']) or 'none'}",
        "",
        "## Held-out cases",
        "",
        "| Metric | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for title, key in rows:
        lines.append(
            f"| {title} | "
            + " | ".join(cell(archs[label]["held_out"], title, key) for label in labels)
            + " |"
        )
    lines += [
        "",
        "## All cases (including development cases)",
        "",
        "| Metric | " + " | ".join(labels) + " |",
        "|---|" + "---|" * len(labels),
    ]
    for title, key in rows[:4]:
        lines.append(
            f"| {title} | "
            + " | ".join(cell(archs[label]["all"], title, key) for label in labels)
            + " |"
        )
    lines += ["", "## Paired comparisons (held-out cases)", ""]
    for pair in result["pairs"]:
        lines += [
            f"### {pair['a']} vs {pair['b']}",
            "",
            f"- Cases decided by both: {pair['cases']}",
            f"- Both correct {pair['both']}, only {pair['a']} {pair['only_a']}, "
            f"only {pair['b']} {pair['only_b']}, neither {pair['neither']}",
            f"- Exact McNemar p-value: {format_p(pair['p_value'])}",
            "",
        ]
        if pair["disagreements"]:
            lines += [
                "| Case | " + f"{pair['a']} | {pair['b']} | Effective |",
                "|---|---|---|---|",
            ]
            for d in pair["disagreements"]:
                mark_a = "✓" if d["a_correct"] else "✗"
                mark_b = "✓" if d["b_correct"] else "✗"
                lines.append(
                    f"| `{d['key']}` | {d['a_action']} {mark_a} | {d['b_action']} {mark_b} | "
                    f"{', '.join(d['effective'])} |"
                )
            lines.append("")
    lines += ["## By family (held-out cases)", ""]
    families = sorted({f for label in labels for f in archs[label]["by_family"]})
    lines += [
        "| Family | "
        + " | ".join(f"{label} accuracy / resolution / cost" for label in labels)
        + " |",
        "|---|" + "---|" * len(labels),
    ]
    for family in families:
        cells = []
        for label in labels:
            m = archs[label]["by_family"].get(family)
            cells.append(
                "n/a"
                if m is None
                else f"{_fmt(m['decision_accuracy'])} / {_fmt(m['resolution_rate'])} / "
                f"${m['total_cost_usd']}"
            )
        lines.append(f"| {family} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default="eval_results")
    parser.add_argument("--name", required=True)
    parser.add_argument("--reports", nargs="+", required=True, help="report labels to compare")
    parser.add_argument("--dev-cases", default="", help="comma-separated development case keys")
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    reports = {
        label: json.loads((results_dir / f"{label}.json").read_text(encoding="utf-8"))
        for label in args.reports
    }
    dev = [key.strip() for key in args.dev_cases.split(",") if key.strip()]
    result = compare(reports, dev)
    (results_dir / f"{args.name}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (results_dir / f"{args.name}.md").write_text(
        render_markdown(args.name, result), encoding="utf-8", newline="\n"
    )
    for pair in result["pairs"]:
        print(
            f"{pair['a']} vs {pair['b']}: only-a {pair['only_a']}, only-b {pair['only_b']}, "
            f"p={format_p(pair['p_value'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
