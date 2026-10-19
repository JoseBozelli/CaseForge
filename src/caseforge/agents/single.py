"""Single-agent baseline: one bounded loop with all read tools that ends in one decision.

Uses the supervisor's decision contract and checks, so its decisions are directly
comparable. Never raises: model errors, invalid output, exhausted steps and unexpected
exceptions become FAILED; a well-formed decision that breaks a rule is INVALID.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue

from caseforge.agents.contracts import SingleAgentStep
from caseforge.agents.supervisor import SupervisorStatus
from caseforge.agents.workers import ToolInvoker
from caseforge.common.hashing import canonical_json_bytes
from caseforge.reasoning.models import CallContext, LlmCallRecord
from caseforge.reasoning.ports import ReasonerCallError
from caseforge.reasoning.structured import StructuredCaller
from caseforge.tools.models import ToolCall, ToolContext, ToolInvocationRecord

SOURCE_KEYS = ("event_id", "chunk_id")


class SingleAgentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: SupervisorStatus
    output: dict[str, JsonValue] | None = None
    error: str | None = None
    steps_used: int
    llm_calls: tuple[LlmCallRecord, ...] = ()
    tool_calls: tuple[ToolInvocationRecord, ...] = ()


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _collect_sources(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SOURCE_KEYS and isinstance(item, str):
                found.add(item)
            else:
                _collect_sources(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_sources(item, found)


class SingleAgent:
    name = "single"

    def __init__(
        self,
        *,
        caller: StructuredCaller,
        tools: ToolInvoker,
        template_version: int,
        max_steps: int,
        allowed_actions: frozenset[str],
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self._caller = caller
        self._tools = tools
        self._template_version = template_version
        self._max_steps = max_steps
        self._allowed = frozenset(allowed_actions)

    def _task(self) -> str:
        return (
            "Investigate this case with the available tools, then decide: propose exactly one "
            f"action from [{', '.join(sorted(self._allowed))}] or escalate to a person. "
            "List the actions you considered in candidate_actions. Evidence refs must be "
            "event_id or chunk_id values returned by your own tool calls."
        )

    def run(
        self, *, run_id: str, tenant_id: str, case_id: str, as_of: datetime
    ) -> SingleAgentResult:
        llm_calls: list[LlmCallRecord] = []
        tool_calls: list[ToolInvocationRecord] = []
        transcript: list[dict[str, Any]] = []
        observed: set[str] = set()
        steps_used = 0

        def result(status: SupervisorStatus, **extra: Any) -> SingleAgentResult:
            return SingleAgentResult(
                status=status,
                steps_used=steps_used,
                llm_calls=tuple(llm_calls),
                tool_calls=tuple(tool_calls),
                **extra,
            )

        try:
            for step in range(self._max_steps):
                steps_used = step + 1
                variables = {
                    "case_id": case_id,
                    "question": self._task(),
                    "steps_remaining": str(self._max_steps - step),
                    "tools": _json(self._tools.describe(self.name)),
                    "transcript": _json(transcript),
                }
                context = CallContext(
                    run_id=run_id, case_id=case_id, node="single_agent", step=step
                )
                try:
                    call = self._caller.call(
                        "single_agent",
                        variables,
                        SingleAgentStep,
                        context,
                        version=self._template_version,
                    )
                except ReasonerCallError as exc:
                    llm_calls.append(exc.record)
                    return result(
                        SupervisorStatus.FAILED, error=f"{exc.record.status}: {exc.record.error}"
                    )
                llm_calls.append(call.record)
                step_output = call.output

                if step_output.action == "decide":
                    decision = step_output.decision
                    output = decision.model_dump(mode="json")
                    not_allowed = sorted(set(decision.candidate_actions) - self._allowed)
                    if not_allowed:
                        return result(
                            SupervisorStatus.INVALID,
                            output=output,
                            error=f"actions not allowed {not_allowed}",
                        )
                    if decision.proposal is not None:
                        unseen = sorted(set(decision.proposal.evidence_refs) - observed)
                        if unseen:
                            return result(
                                SupervisorStatus.INVALID,
                                output=output,
                                error=f"evidence refs not observed {unseen}",
                            )
                    return result(SupervisorStatus.OK, output=output)

                request = step_output.tool
                outcome = self._tools.invoke(
                    ToolCall(tool=request.tool, arguments=request.arguments),
                    ToolContext(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        case_id=case_id,
                        as_of=as_of,
                        agent=self.name,
                        step=step,
                    ),
                )
                tool_calls.append(outcome.record)
                if outcome.result.output is not None:
                    _collect_sources(outcome.result.output, observed)
                transcript.append(
                    {
                        "step": step,
                        "tool": request.tool,
                        "arguments": request.arguments,
                        "result": outcome.result.model_dump(mode="json"),
                    }
                )
            return result(SupervisorStatus.FAILED, error="step budget exhausted")
        except Exception as exc:  # the single agent never raises
            return result(SupervisorStatus.FAILED, error=type(exc).__name__)
