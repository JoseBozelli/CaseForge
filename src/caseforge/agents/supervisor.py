"""Supervisor: plans worker delegation and synthesizes worker results into one decision.

A supervisor never raises. Schema-invalid output or a model error is FAILED; a
well-formed decision that breaks a rule (action not allowed, no clarification rounds
left, evidence not found by any worker) is INVALID.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue

from caseforge.agents.contracts import SupervisorPlan, Synthesis
from caseforge.common.hashing import canonical_json_bytes
from caseforge.reasoning.models import CallContext, LlmCallRecord
from caseforge.reasoning.ports import ReasonerCallError
from caseforge.reasoning.structured import StructuredCaller


class SupervisorStatus(StrEnum):
    OK = "ok"
    INVALID = "invalid"
    FAILED = "failed"


class SupervisorResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: SupervisorStatus
    output: dict[str, JsonValue] | None = None
    error: str | None = None
    llm_call: LlmCallRecord | None = None


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def cited_sources(worker_results: Sequence[Mapping[str, Any]]) -> set[str]:
    """Every source id cited in any worker's findings."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_ids" and isinstance(item, list):
                    found.update(s for s in item if isinstance(s, str))
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for result in worker_results:
        walk(result.get("findings"))
    return found


class Supervisor:
    def __init__(
        self,
        *,
        caller: StructuredCaller,
        plan_version: int,
        synthesis_version: int,
        allowed_actions: frozenset[str],
        max_clarification_rounds: int,
    ) -> None:
        self._caller = caller
        self._plan_version = plan_version
        self._synthesis_version = synthesis_version
        self._allowed = frozenset(allowed_actions)
        self._max_rounds = max_clarification_rounds

    def plan(
        self, *, run_id: str, case_id: str, case_summary: Mapping[str, Any]
    ) -> SupervisorResult:
        return self._call(
            "supervisor_plan",
            self._plan_version,
            {"case_id": case_id, "case_summary": _json(dict(case_summary))},
            SupervisorPlan,
            CallContext(run_id=run_id, case_id=case_id, node="supervisor_plan", step=0),
            check=None,
        )

    def synthesize(
        self,
        *,
        run_id: str,
        case_id: str,
        case_summary: Mapping[str, Any],
        worker_results: Sequence[Mapping[str, Any]],
        round_index: int,
    ) -> SupervisorResult:
        remaining = max(self._max_rounds - round_index, 0)
        cited = cited_sources(worker_results)

        def check(synthesis: Synthesis) -> str | None:
            not_allowed = sorted(set(synthesis.candidate_actions) - self._allowed)
            if not_allowed:
                return f"actions not allowed {not_allowed}"
            if synthesis.decision == "clarify" and remaining == 0:
                return "no clarification rounds remain"
            if synthesis.proposal is not None:
                unseen = sorted(set(synthesis.proposal.evidence_refs) - cited)
                if unseen:
                    return f"evidence refs not found by any worker {unseen}"
            return None

        variables = {
            "case_id": case_id,
            "case_summary": _json(dict(case_summary)),
            "worker_results": _json([dict(r) for r in worker_results]),
            "allowed_actions": ", ".join(sorted(self._allowed)),
            "clarifications_remaining": str(remaining),
        }
        context = CallContext(
            run_id=run_id, case_id=case_id, node="supervisor_synthesis", step=round_index
        )
        return self._call(
            "supervisor_synthesis", self._synthesis_version, variables, Synthesis, context, check
        )

    def _call(
        self,
        template_id: str,
        version: int,
        variables: Mapping[str, str],
        model: type[SupervisorPlan] | type[Synthesis],
        context: CallContext,
        check: Callable[[Any], str | None] | None,
    ) -> SupervisorResult:
        try:
            try:
                result = self._caller.call(template_id, variables, model, context, version=version)
            except ReasonerCallError as exc:
                return SupervisorResult(
                    status=SupervisorStatus.FAILED,
                    error=f"{exc.record.status}: {exc.record.error}",
                    llm_call=exc.record,
                )
            output = result.output.model_dump(mode="json")
            problem = check(result.output) if check is not None else None
            if problem is not None:
                return SupervisorResult(
                    status=SupervisorStatus.INVALID,
                    output=output,
                    error=problem,
                    llm_call=result.record,
                )
            return SupervisorResult(
                status=SupervisorStatus.OK, output=output, llm_call=result.record
            )
        except Exception as exc:  # the supervisor never raises
            return SupervisorResult(status=SupervisorStatus.FAILED, error=type(exc).__name__)
