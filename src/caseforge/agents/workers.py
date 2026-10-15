"""Bounded, tool-using worker loops that return typed, source-grounded findings.

A worker never raises: model errors, invalid output and unexpected exceptions become
a FAILED result; tool errors are returned to the model as observations.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from caseforge.agents.contracts import EvidenceStep, PolicyStep
from caseforge.common.hashing import canonical_json_bytes
from caseforge.reasoning.models import CallContext, LlmCallRecord
from caseforge.reasoning.ports import ReasonerCallError
from caseforge.reasoning.structured import StructuredCaller
from caseforge.tools.models import ToolCall, ToolContext, ToolInvocationRecord
from caseforge.tools.registry import ToolOutcome


class ToolInvoker(Protocol):
    def describe(self, agent: str) -> list[dict[str, Any]]: ...

    def invoke(self, call: ToolCall, context: ToolContext) -> ToolOutcome: ...


class WorkerStatus(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    UNGROUNDED = "ungrounded"
    FAILED = "failed"


class WorkerResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    worker: str
    status: WorkerStatus
    findings: dict[str, JsonValue] | None = None
    steps_used: int
    error: str | None = None
    llm_calls: tuple[LlmCallRecord, ...] = ()
    tool_calls: tuple[ToolInvocationRecord, ...] = ()


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _collect(value: Any, key: str, found: set[str]) -> None:
    """Gather every string stored under `key` anywhere in a JSON structure."""
    if isinstance(value, dict):
        for name, item in value.items():
            if name == key and isinstance(item, str):
                found.add(item)
            else:
                _collect(item, key, found)
    elif isinstance(value, list):
        for item in value:
            _collect(item, key, found)


class Worker:
    """Runs one specialist: at most max_steps model decisions, one tool call per step."""

    def __init__(
        self,
        *,
        name: str,
        step_model: type[EvidenceStep] | type[PolicyStep],
        source_key: str,
        template_id: str,
        template_version: int,
        max_steps: int,
        caller: StructuredCaller,
        tools: ToolInvoker,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.name = name
        self._step_model = step_model
        self._source_key = source_key
        self._template_id = template_id
        self._template_version = template_version
        self._max_steps = max_steps
        self._caller = caller
        self._tools = tools

    def run(
        self, *, run_id: str, tenant_id: str, case_id: str, as_of: datetime, question: str
    ) -> WorkerResult:
        llm_calls: list[LlmCallRecord] = []
        tool_calls: list[ToolInvocationRecord] = []
        transcript: list[dict[str, Any]] = []
        observed: set[str] = set()
        steps_used = 0

        def result(status: WorkerStatus, **extra: Any) -> WorkerResult:
            return WorkerResult(
                worker=self.name,
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
                    "question": question,
                    "steps_remaining": str(self._max_steps - step),
                    "tools": _json(self._tools.describe(self.name)),
                    "transcript": _json(transcript),
                }
                context = CallContext(run_id=run_id, case_id=case_id, node=self.name, step=step)
                try:
                    call = self._caller.call(
                        self._template_id,
                        variables,
                        self._step_model,
                        context,
                        version=self._template_version,
                    )
                except ReasonerCallError as exc:
                    llm_calls.append(exc.record)
                    return result(
                        WorkerStatus.FAILED, error=f"{exc.record.status}: {exc.record.error}"
                    )
                llm_calls.append(call.record)
                decision = call.output

                if decision.action == "finish":
                    findings = decision.findings
                    data = findings.model_dump(mode="json")
                    unseen = sorted(findings.cited_sources() - observed)
                    if unseen:
                        return result(
                            WorkerStatus.UNGROUNDED,
                            findings=data,
                            error=f"cites unobserved sources {unseen}",
                        )
                    return result(WorkerStatus.COMPLETED, findings=data)

                request = decision.tool
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
                    _collect(outcome.result.output, self._source_key, observed)
                transcript.append(
                    {
                        "step": step,
                        "tool": request.tool,
                        "arguments": request.arguments,
                        "result": outcome.result.model_dump(mode="json"),
                    }
                )
            return result(WorkerStatus.INCOMPLETE, error="step budget exhausted")
        except Exception as exc:  # a worker never raises
            return result(WorkerStatus.FAILED, error=type(exc).__name__)


def evidence_worker(
    *, caller: StructuredCaller, tools: ToolInvoker, template_version: int, max_steps: int
) -> Worker:
    return Worker(
        name="evidence",
        step_model=EvidenceStep,
        source_key="event_id",
        template_id="evidence",
        template_version=template_version,
        max_steps=max_steps,
        caller=caller,
        tools=tools,
    )


def policy_worker(
    *, caller: StructuredCaller, tools: ToolInvoker, template_version: int, max_steps: int
) -> Worker:
    return Worker(
        name="policy",
        step_model=PolicyStep,
        source_key="chunk_id",
        template_id="policy",
        template_version=template_version,
        max_steps=max_steps,
        caller=caller,
        tools=tools,
    )


__all__: Iterable[str] = (
    "Worker",
    "WorkerResult",
    "WorkerStatus",
    "evidence_worker",
    "policy_worker",
)
