"""Command line: run the benchmark and write a report to the results directory.

CASEFORGE__* variables from the environment are honored; flags override them.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from caseforge.evaluation.runner import run_benchmark


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/caseforge.yaml")
    parser.add_argument("--label", required=True, help="report name, e.g. rules-baseline")
    parser.add_argument("--mode", choices=["deterministic", "hierarchical", "single_agent"])
    parser.add_argument("--provider", choices=["fake", "replay", "anthropic"])
    parser.add_argument("--source", choices=["live", "replay"])
    parser.add_argument("--model", help="model id, e.g. claude-sonnet-5-5")
    parser.add_argument("--cassette", help="cassette path relative to the config directory")
    parser.add_argument("--cases", help="comma-separated benchmark case keys")
    parser.add_argument("--limit", type=int, help="run only the first N cases")
    parser.add_argument("--spend-cap", type=float, help="stop starting cases at this USD total")
    args = parser.parse_args(argv)

    environ = {k: v for k, v in os.environ.items() if k.startswith("CASEFORGE__")}
    overrides = {
        "CASEFORGE__ENGINE__MODE": args.mode,
        "CASEFORGE__REASONING__PROVIDER": args.provider,
        "CASEFORGE__REASONING__SOURCE": args.source,
        "CASEFORGE__REASONING__MODEL": args.model,
        "CASEFORGE__REASONING__CASSETTE_PATH": args.cassette,
    }
    environ.update({k: v for k, v in overrides.items() if v is not None})
    case_keys = [key.strip() for key in args.cases.split(",")] if args.cases else None

    report = run_benchmark(
        args.config,
        label=args.label,
        environ=environ,
        limit=args.limit,
        case_keys=case_keys,
        spend_cap_usd=args.spend_cap,
    )
    s = report.summary
    print(
        f"{report.label}: {s.cases} cases, statuses {s.run_status}, "
        f"decision accuracy {s.decision_accuracy}, resolution rate {s.resolution_rate}, "
        f"unauthorized {s.unauthorized_actions}, duplicates {s.duplicate_executions}, "
        f"cost ${s.total_cost_usd}"
        + (" (stopped early at spend cap)" if report.stopped_early else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
