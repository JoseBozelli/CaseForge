"""Command line: run the benchmark and write a report to the results directory."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from caseforge.evaluation.runner import run_benchmark


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/caseforge.yaml")
    parser.add_argument("--label", required=True, help="report name, e.g. rules-baseline")
    parser.add_argument("--mode", choices=["deterministic", "hierarchical", "single_agent"])
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    args = parser.parse_args(argv)

    environ = {"CASEFORGE__ENGINE__MODE": args.mode} if args.mode else {}
    report = run_benchmark(args.config, label=args.label, environ=environ, limit=args.limit)
    s = report.summary
    print(
        f"{report.label}: {s.cases} cases, statuses {s.run_status}, "
        f"decision accuracy {s.decision_accuracy}, resolution rate {s.resolution_rate}, "
        f"unauthorized {s.unauthorized_actions}, duplicates {s.duplicate_executions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
