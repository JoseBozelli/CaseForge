"""Plain-language episode summaries built deterministically from a finished run."""

from __future__ import annotations

from collections.abc import Sequence


def describe_episode(
    *,
    event_types: Sequence[str],
    source: str,
    action_type: str,
    reason: str | None,
    ledger_status: str,
    outcome_status: str,
) -> str:
    parts = [
        f"Case events: {', '.join(event_types) or 'none'}.",
        f"Decision by {source}: {action_type}.",
    ]
    if reason:
        parts.append(f"Reason: {reason}")
    parts.append(f"Execution: {ledger_status}. Outcome: {outcome_status}.")
    return " ".join(parts)
