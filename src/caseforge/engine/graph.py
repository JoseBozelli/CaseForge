"""Case graph with a deterministic fast path and a supervised, parallel worker path.

intake -> triage -> act (rule matched, or deterministic mode)
                 -> supervisor_plan -> run_worker x N (parallel via Send) -> synthesize
synthesize -> act (proposal) | escalate (escalation, invalid, failed)
           | run_worker (bounded clarification) -> synthesize
escalate -> act -> observe

State holds only JSON-compatible values; dependencies are bound by closure. Fields
with the _accumulate reducer are reset by passing None at the start of a run.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from caseforge.agents.supervisor import Supervisor, SupervisorStatus
from caseforge.agents.workers import Worker
from caseforge.engine.ports import ActionExecutor, CaseSource, OutcomeSource
from caseforge.engine.triage import TriagePolicy
from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import EventNormalizer, Rejection
from caseforge.persistence.ports import RecordStore
from caseforge.tools.models import ToolCall, ToolContext
from caseforge.tools.registry import ToolRegistry


def _accumulate(current: list[Any] | None, update: list[Any] | None) -> list[Any]:
    """Append updates; None resets the list (used at the start of each run)."""
    if update is None:
        return []
    return [*(current or []), *update]


class CaseRunState(TypedDict, total=False):
    run_id: str
    tenant_id: str
    case_id: str
    as_of: str
    intake: dict[str, Any]
    triage: dict[str, Any]
    case_summary: dict[str, Any] | None
    plan: dict[str, Any] | None
    synthesis: dict[str, Any] | None
    synthesis_round: int
    decision: dict[str, Any] | None
    action: dict[str, Any]
    outcome: dict[str, Any]
    worker_results: Annotated[list[dict[str, Any]], _accumulate]
    llm_calls: Annotated[list[dict[str, Any]], _accumulate]
    tool_calls: Annotated[list[dict[str, Any]], _accumulate]
    trace: Annotated[list[dict[str, Any]], operator.add]


class WorkerTask(TypedDict):
    run_id: str
    tenant_id: str
    case_id: str
    as_of: str
    worker: str
    question: str
    round: int


@dataclass(frozen=True)
class EngineDeps:
    store: RecordStore
    normalizers: Mapping[str, EventNormalizer]
    triage: TriagePolicy
    case_source: CaseSource
    executor: ActionExecutor
    outcomes: OutcomeSource
    tools: ToolRegistry
    supervisor: Supervisor
    workers: Mapping[str, Worker]
    mode: Literal["deterministic", "hierarchical"]
    escalation_action: str


def _as_of(state: Mapping[str, Any]) -> datetime:
    return datetime.fromisoformat(state["as_of"])


def _dump(records: Any) -> list[dict[str, Any]]:
    return [record.model_dump(mode="json") for record in records]


def _task(state: CaseRunState, worker: str, question: str, round_index: int) -> Send:
    payload: WorkerTask = {
        "run_id": state["run_id"],
        "tenant_id": state["tenant_id"],
        "case_id": state["case_id"],
        "as_of": state["as_of"],
        "worker": worker,
        "question": question,
        "round": round_index,
    }
    return Send("run_worker", payload)


def _escalation_reason(state: CaseRunState) -> str:
    synthesis = state.get("synthesis")
    if synthesis:
        output = synthesis.get("output") or {}
        if synthesis["status"] == SupervisorStatus.OK and output.get("decision") == "escalate":
            return str(output["escalation_reason"])
        return f"synthesis {synthesis['status']}: {synthesis.get('error')}"
    plan = state.get("plan") or {}
    return f"plan {plan.get('status')}: {plan.get('error')}"


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
        fast = decision.rule_id is not None or deps.mode == "deterministic"
        route = "fast_path" if fast else "supervisor"
        record = {
            "rule_id": decision.rule_id,
            "action_type": decision.action_type,
            "event_types": visible,
            "route": route,
        }
        update: CaseRunState = {
            "triage": record,
            "trace": [{"node": "triage", "rule_id": decision.rule_id, "route": route}],
        }
        if fast:
            update["decision"] = {
                "source": "triage",
                "action_type": decision.action_type,
                "rule_id": decision.rule_id,
            }
        return update

    def supervisor_plan(state: CaseRunState) -> CaseRunState:
        summary_call = deps.tools.invoke(
            ToolCall(tool="get_case"),
            ToolContext(
                run_id=state["run_id"],
                tenant_id=state["tenant_id"],
                case_id=state["case_id"],
                as_of=_as_of(state),
                agent="supervisor",
                step=0,
            ),
        )
        update: CaseRunState = {"tool_calls": _dump([summary_call.record])}
        if not summary_call.result.ok:
            error = f"case summary unavailable ({summary_call.result.error_code})"
            update["plan"] = {"status": SupervisorStatus.FAILED, "output": None, "error": error}
            update["trace"] = [{"node": "supervisor_plan", "status": "failed", "workers": []}]
            return update
        summary = summary_call.result.output or {}
        result = deps.supervisor.plan(
            run_id=state["run_id"], case_id=state["case_id"], case_summary=summary
        )
        ok = result.status == SupervisorStatus.OK and result.output is not None
        workers = list(result.output["workers"]) if ok else []
        update["case_summary"] = summary
        update["plan"] = {
            "status": str(result.status),
            "output": result.output,
            "error": result.error,
        }
        update["llm_calls"] = _dump([result.llm_call]) if result.llm_call else []
        update["trace"] = [
            {
                "node": "supervisor_plan",
                "status": str(result.status),
                "workers": workers,
                "skipped": sorted(set(deps.workers) - set(workers)),
            }
        ]
        return update

    def run_worker(task: WorkerTask) -> CaseRunState:
        result = deps.workers[task["worker"]].run(
            run_id=task["run_id"],
            tenant_id=task["tenant_id"],
            case_id=task["case_id"],
            as_of=_as_of(task),
            question=task["question"],
            round_index=task["round"],
        )
        summary = {
            "worker": result.worker,
            "round": task["round"],
            "question": task["question"],
            "status": str(result.status),
            "findings": result.findings,
            "error": result.error,
            "steps_used": result.steps_used,
        }
        trace = {
            "node": "run_worker",
            "worker": result.worker,
            "round": task["round"],
            "status": str(result.status),
        }
        return {
            "worker_results": [summary],
            "llm_calls": _dump(result.llm_calls),
            "tool_calls": _dump(result.tool_calls),
            "trace": [trace],
        }

    def synthesize(state: CaseRunState) -> CaseRunState:
        round_index = state.get("synthesis_round", 0)
        result = deps.supervisor.synthesize(
            run_id=state["run_id"],
            case_id=state["case_id"],
            case_summary=state.get("case_summary") or {},
            worker_results=state.get("worker_results") or [],
            round_index=round_index,
        )
        output = result.output
        decision = output.get("decision") if output else None
        update: CaseRunState = {
            "synthesis": {
                "status": str(result.status),
                "output": output,
                "error": result.error,
                "round": round_index,
            },
            "synthesis_round": round_index + 1,
            "llm_calls": _dump([result.llm_call]) if result.llm_call else [],
            "trace": [
                {
                    "node": "synthesize",
                    "round": round_index,
                    "status": str(result.status),
                    "decision": decision,
                }
            ],
        }
        if result.status == SupervisorStatus.OK and decision == "propose_action":
            proposal = output["proposal"]
            update["decision"] = {
                "source": "supervisor",
                "action_type": proposal["action_type"],
                "evidence_refs": proposal["evidence_refs"],
            }
        return update

    def escalate(state: CaseRunState) -> CaseRunState:
        reason = _escalation_reason(state)
        return {
            "decision": {
                "source": "escalation",
                "action_type": deps.escalation_action,
                "reason": reason,
            },
            "trace": [{"node": "escalate", "reason": reason}],
        }

    def act(state: CaseRunState) -> CaseRunState:
        decision = state["decision"] or {}
        action_type = decision["action_type"]
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
            "source": decision["source"],
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

    def route_after_triage(state: CaseRunState) -> str:
        return "act" if state["triage"]["route"] == "fast_path" else "supervisor_plan"

    def route_after_plan(state: CaseRunState) -> str | list[Send]:
        plan = state["plan"] or {}
        if plan.get("status") != SupervisorStatus.OK:
            return "escalate"
        output = plan["output"]
        if not output["workers"]:
            return "synthesize"
        return [_task(state, w, output[f"{w}_question"], 0) for w in output["workers"]]

    def route_after_synthesis(state: CaseRunState) -> str | list[Send]:
        synthesis = state["synthesis"] or {}
        if synthesis.get("status") != SupervisorStatus.OK:
            return "escalate"
        output = synthesis["output"]
        if output["decision"] == "propose_action":
            return "act"
        if output["decision"] == "clarify":
            clarification = output["clarification"]
            return [
                _task(
                    state,
                    clarification["worker"],
                    clarification["question"],
                    synthesis["round"] + 1,
                )
            ]
        return "escalate"

    builder = StateGraph(CaseRunState)
    builder.add_node("intake", intake)
    builder.add_node("triage", triage)
    builder.add_node("supervisor_plan", supervisor_plan)
    builder.add_node("run_worker", run_worker)
    builder.add_node("synthesize", synthesize)
    builder.add_node("escalate", escalate)
    builder.add_node("act", act)
    builder.add_node("observe", observe)
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "triage")
    builder.add_conditional_edges("triage", route_after_triage, ["act", "supervisor_plan"])
    builder.add_conditional_edges(
        "supervisor_plan", route_after_plan, ["escalate", "synthesize", "run_worker"]
    )
    builder.add_edge("run_worker", "synthesize")
    builder.add_conditional_edges(
        "synthesize", route_after_synthesis, ["act", "escalate", "run_worker"]
    )
    builder.add_edge("escalate", "act")
    builder.add_edge("act", "observe")
    builder.add_edge("observe", END)
    return builder
