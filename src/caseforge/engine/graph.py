"""Case graph: intake -> triage -> act -> observe.

Graph state holds only JSON-compatible values so checkpoints stay portable and
replayable. Dependencies are bound by closure, never stored in state.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from caseforge.engine.ports import ActionExecutor, CaseSource, OutcomeSource
from caseforge.engine.triage import TriagePolicy
from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import EventNormalizer, Rejection
from caseforge.persistence.ports import RecordStore


class CaseRunState(TypedDict, total=False):
    run_id: str
    tenant_id: str
    case_id: str
    as_of: str
    intake: dict[str, Any]
    triage: dict[str, Any]
    action: dict[str, Any]
    outcome: dict[str, Any]
    trace: Annotated[list[dict[str, Any]], operator.add]


@dataclass(frozen=True)
class EngineDeps:
    store: RecordStore
    normalizers: Mapping[str, EventNormalizer]
    triage: TriagePolicy
    case_source: CaseSource
    executor: ActionExecutor
    outcomes: OutcomeSource


def _as_of(state: CaseRunState) -> datetime:
    return datetime.fromisoformat(state["as_of"])


def build_case_graph(deps: EngineDeps) -> StateGraph:
    """Return the uncompiled case graph; the caller compiles it with a checkpointer."""

    def intake(state: CaseRunState) -> CaseRunState:
        accepted: list[EventEnvelope] = []
        rejected: list[Rejection] = []
        for event in deps.case_source.source_events(
            state["tenant_id"], state["case_id"], _as_of(state)
        ):
            normalizer = deps.normalizers.get(event.source_system)
            if normalizer is None:
                raise ValueError(f"no mapping configured for source {event.source_system!r}")
            result = normalizer.normalize(event)
            if isinstance(result, Rejection):
                rejected.append(result)
            else:
                accepted.append(result)
        intake_result = deps.store.append_events(accepted)
        deps.store.save_rejections(rejected)
        summary = {
            "inserted": len(intake_result.inserted),
            "duplicates": len(intake_result.duplicates),
            "conflicts": len(intake_result.conflicts),
            "rejected": len(rejected),
        }
        return {"intake": summary, "trace": [{"node": "intake", **summary}]}

    def triage(state: CaseRunState) -> CaseRunState:
        as_of = _as_of(state)
        events = deps.store.events_for_case(state["tenant_id"], state["case_id"])
        visible = sorted({e.event_type for e in events if e.recorded_at <= as_of})
        decision = deps.triage.decide(visible)
        record = {
            "rule_id": decision.rule_id,
            "action_type": decision.action_type,
            "event_types": visible,
        }
        trace = {"node": "triage", "rule_id": decision.rule_id, "action": decision.action_type}
        return {"triage": record, "trace": [trace]}

    def act(state: CaseRunState) -> CaseRunState:
        action_type = state["triage"]["action_type"]
        action_id = f"{state['run_id']}:{action_type}"
        applied = deps.executor.execute(
            tenant_id=state["tenant_id"],
            case_id=state["case_id"],
            action_id=action_id,
            action_type=action_type,
            at=_as_of(state),
        )
        record = {
            "action_id": action_id,
            "action_type": action_type,
            "acted_at": state["as_of"],
            "applied": applied,
        }
        trace = {"node": "act", "action_id": action_id, "applied": applied}
        return {"action": record, "trace": [trace]}

    def observe(state: CaseRunState) -> CaseRunState:
        observation = deps.outcomes.observe(
            tenant_id=state["tenant_id"],
            case_id=state["case_id"],
            action_id=state["action"]["action_id"],
            as_of=_as_of(state),
        )
        trace = {"node": "observe", "status": str(observation.status)}
        return {"outcome": observation.model_dump(mode="json"), "trace": [trace]}

    builder = StateGraph(CaseRunState)
    builder.add_node("intake", intake)
    builder.add_node("triage", triage)
    builder.add_node("act", act)
    builder.add_node("observe", observe)
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "triage")
    builder.add_edge("triage", "act")
    builder.add_edge("act", "observe")
    builder.add_edge("observe", END)
    return builder
