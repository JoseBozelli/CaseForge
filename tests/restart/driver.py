"""Test driver: runs CaseForge in its own process so tests can kill it at fault points.

Exit code 86 means the process stopped itself abruptly at the requested fault point
via os._exit: no cleanup and no graceful shutdown; only committed data survives.
On a normal finish, the last stdout line is a JSON summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from caseforge.composition import build_container
from caseforge.reasoning.fake import FakeReasoner

KILLED_EXIT_CODE = 86
FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def _killer(target: str) -> Callable[[str], None]:
    def fault(point: str) -> None:
        if point == target:
            sys.stdout.flush()
            os._exit(KILLED_EXIT_CODE)

    return fault


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "resume", "approve"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--kill-at")
    parser.add_argument("--script", help="JSON file of scripted reasoner outputs")
    args = parser.parse_args(argv)

    reasoner = None
    if args.script:
        reasoner = FakeReasoner(json.loads(Path(args.script).read_text(encoding="utf-8")))
    fault = _killer(args.kill_at) if args.kill_at else None

    with build_container(
        args.config, environ={}, clock=lambda: FIXED, reasoner=reasoner, fault_injector=fault
    ) as container:
        world = container.open_simulated_case(args.family, args.seed)
        if args.command == "run":
            final = container.run_case(args.run_id, world.case_id)
        elif args.command == "resume":
            final = container.resume(args.run_id)
        else:
            final = container.approve(args.run_id, actor="approver-1")
        action = final.get("action") or {}
        entry = container.store.get_action(action["action_id"]) if "action_id" in action else None
        summary = {
            "action": action,
            "pending_approval": container.pending_approval(args.run_id),
            "ledger": None
            if entry is None
            else {"status": str(entry.status), "attempts": entry.attempts},
            "world_actions": [a.action_id for a in world.ground_truth().actions],
        }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
