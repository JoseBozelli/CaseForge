"""Pre-registered confirmatory analysis (docs/preregistration-v2.md).

Applies the registered hypotheses and decision rule exactly as written. Reads saved
reports only. Constants below are part of the registration; changing them after the
runs would invalidate the study.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from caseforge.evaluation.compare import metrics, newcombe_paired, one_sided_mcnemar, paired

ALPHA = 0.025  # per hypothesis (Bonferroni over two primary hypotheses, one-sided)
MARGIN = 0.10  # non-inferiority margin in accuracy (10 percentage points)


def analyse(rules: dict[str, Any], cheap: dict[str, Any], strong: dict[str, Any]) -> dict[str, Any]:
    vs_rules = paired(cheap["cases"], rules["cases"])  # a = cheap, b = rules
    h1_p = one_sided_mcnemar(vs_rules["only_a"], vs_rules["only_b"])
    h1 = h1_p is not None and h1_p < ALPHA

    vs_strong = paired(cheap["cases"], strong["cases"])  # a = cheap, b = strong
    interval = newcombe_paired(
        vs_strong["both"], vs_strong["only_a"], vs_strong["only_b"], vs_strong["neither"]
    )
    h2 = interval is not None and interval[1] > -MARGIN

    if h1 and h2:
        decision = (
            "Recommend the cheap configuration as the cost-optimized default: it beats rules and "
            f"loses less than {MARGIN:.0%} accuracy against the strong configuration."
        )
    elif h1:
        decision = (
            "The cheap configuration beats rules, but non-inferiority to the strong configuration "
            "is not shown; recommend the strong configuration where decisions matter."
        )
    elif h2:
        decision = (
            "Non-inferiority to the strong configuration is shown, but an advantage over rules is "
            "not; neither hypothesis supports a cheap-agent default on its own."
        )
    else:
        decision = "Neither hypothesis is supported; the strong configuration remains recommended."
    return {
        "alpha_per_hypothesis": ALPHA,
        "margin": MARGIN,
        "labels": {"rules": rules["label"], "cheap": cheap["label"], "strong": strong["label"]},
        "metrics": {
            "rules": metrics(rules["cases"]),
            "cheap": metrics(cheap["cases"]),
            "strong": metrics(strong["cases"]),
        },
        "h1": {"discordant": vs_rules, "p_one_sided": h1_p, "supported": h1},
        "h2": {"discordant": vs_strong, "difference_ci95": interval, "supported": h2},
        "decision": decision,
    }


def render(result: dict[str, Any]) -> str:
    labels, m = result["labels"], result["metrics"]
    h1, h2 = result["h1"], result["h2"]
    d = h2["difference_ci95"]
    rows = "\n".join(
        f"| {role} | `{labels[role]}` | {m[role]['decided']} | {m[role]['decision_accuracy']} | "
        f"{m[role]['accuracy_ci95']} | {m[role]['cost_per_agent_case_usd']} | "
        f"{m[role]['unauthorized']} / {m[role]['forbidden']} / {m[role]['duplicates']} |"
        for role in ("rules", "cheap", "strong")
    )
    return f"""# Confirmatory study v2

Registered in `docs/preregistration-v2.md` before any run. Analysis applied mechanically by
`caseforge.evaluation.confirm`. Outcomes are synthetic.

| Role | Report | Decided | Accuracy | 95% CI | USD per agent case | Unauth / forbid / dup |
|---|---|---|---|---|---|---|
{rows}

**H1: the cheap configuration beats rules.** Discordant cases: cheap only
{h1["discordant"]["only_a"]}, rules only {h1["discordant"]["only_b"]}. Exact one-sided McNemar
p = {h1["p_one_sided"]} (threshold {result["alpha_per_hypothesis"]}).
**{"Supported" if h1["supported"] else "Not supported"}.**

**H2: the cheap configuration is non-inferior to the strong one (margin {result["margin"]:.0%}).**
Discordant cases: cheap only {h2["discordant"]["only_a"]}, strong only
{h2["discordant"]["only_b"]}. Accuracy difference (cheap minus strong) {d[0] if d else "n/a"},
95% Newcombe interval [{d[1] if d else "n/a"}, {d[2] if d else "n/a"}]; non-inferior if the lower
bound exceeds -{result["margin"]}. **{"Supported" if h2["supported"] else "Not supported"}.**

## Registered decision

{result["decision"]}
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default="eval_results")
    parser.add_argument("--name", default="confirmation-v2")
    parser.add_argument("--rules", required=True)
    parser.add_argument("--cheap", required=True)
    parser.add_argument("--strong", required=True)
    args = parser.parse_args(argv)
    results = Path(args.results_dir)

    def load(label: str) -> dict[str, Any]:
        return json.loads((results / f"{label}.json").read_text(encoding="utf-8"))

    result = analyse(load(args.rules), load(args.cheap), load(args.strong))
    (results / f"{args.name}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    (results / f"{args.name}.md").write_text(render(result), encoding="utf-8", newline="\n")
    print(result["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
