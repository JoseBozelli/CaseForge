"""Tool registry: validation, permission checks and failure isolation for every call."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from caseforge.common.errors import ConfigError
from caseforge.common.hashing import sha256_hex
from caseforge.tools.models import (
    ToolCall,
    ToolContext,
    ToolErrorCode,
    ToolInvocationRecord,
    ToolPolicy,
    ToolResult,
)

Handler = Callable[[Any, ToolContext, ToolPolicy], BaseModel]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    side_effect: Literal["read", "mutate"]
    args_model: type[BaseModel]
    result_model: type[BaseModel]
    handler: Handler


@dataclass(frozen=True)
class ToolOutcome:
    result: ToolResult
    record: ToolInvocationRecord


def _summarize(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'arguments'}: {err['msg']}"
        for err in exc.errors()
    )


class ToolRegistry:
    """Dispatches tool calls. Mutating tools are refused until governed execution exists."""

    def __init__(
        self,
        specs: Iterable[ToolSpec],
        policies: Mapping[str, ToolPolicy],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self._specs:
                raise ConfigError(f"duplicate tool {spec.name!r}")
            self._specs[spec.name] = spec
        unknown = sorted(set(policies) - self._specs.keys())
        if unknown:
            raise ConfigError(f"tool policies reference unknown tools {unknown}")
        self._policies = dict(policies)
        self._clock = clock

    def names(self) -> tuple[str, ...]:
        """Every registered tool name, sorted."""
        return tuple(sorted(self._specs))

    def spec(self, name: str) -> ToolSpec:
        return self._specs[name]

    def available(self, agent: str) -> tuple[ToolSpec, ...]:
        """Tools this agent may call, sorted by name."""
        return tuple(
            spec
            for name, spec in sorted(self._specs.items())
            if spec.side_effect == "read" and self._permitted(name, agent)
        )

    def describe(self, agent: str) -> list[dict[str, Any]]:
        """Name, description and argument JSON schema of each tool available to agent."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.args_model.model_json_schema(),
            }
            for spec in self.available(agent)
        ]

    def invoke(self, call: ToolCall, context: ToolContext) -> ToolOutcome:
        started_at = self._clock()
        spec = self._specs.get(call.tool)
        if spec is None:
            return self._fail(call, context, started_at, ToolErrorCode.UNKNOWN_TOOL, call.tool)
        if spec.side_effect != "read":
            return self._fail(
                call,
                context,
                started_at,
                ToolErrorCode.NOT_PERMITTED,
                "requires governed execution",
            )
        if not self._permitted(call.tool, context.agent):
            return self._fail(call, context, started_at, ToolErrorCode.NOT_PERMITTED, call.tool)
        try:
            arguments = spec.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            return self._fail(
                call, context, started_at, ToolErrorCode.INVALID_ARGUMENTS, _summarize(exc)
            )
        try:
            output = spec.handler(arguments, context, self._policies[call.tool])
            if not isinstance(output, spec.result_model):
                raise TypeError(f"handler returned {type(output).__name__}")
        except Exception as exc:  # failure isolation: report the class only, never internals
            return self._fail(
                call, context, started_at, ToolErrorCode.TOOL_ERROR, type(exc).__name__
            )
        output_data = output.model_dump(mode="json")
        record = self._record(
            call,
            context,
            started_at,
            arguments=arguments.model_dump(mode="json"),
            ok=True,
            error_code=None,
            result_sha256=sha256_hex(output_data),
        )
        return ToolOutcome(ToolResult(tool=call.tool, ok=True, output=output_data), record)

    def refuse(
        self, call: ToolCall, context: ToolContext, code: ToolErrorCode, detail: str
    ) -> ToolOutcome:
        """Record and return a refusal decided outside the registry (for example by governance)."""
        return self._fail(call, context, self._clock(), code, detail)

    def _permitted(self, name: str, agent: str) -> bool:
        policy = self._policies.get(name)
        return policy is not None and policy.enabled and agent in policy.allowed_agents

    def _fail(
        self,
        call: ToolCall,
        context: ToolContext,
        started_at: datetime,
        code: ToolErrorCode,
        detail: str,
    ) -> ToolOutcome:
        record = self._record(
            call, context, started_at, arguments=None, ok=False, error_code=code, result_sha256=None
        )
        result = ToolResult(tool=call.tool, ok=False, error_code=code, error=detail)
        return ToolOutcome(result, record)

    def _record(
        self,
        call: ToolCall,
        context: ToolContext,
        started_at: datetime,
        *,
        arguments: dict[str, Any] | None,
        ok: bool,
        error_code: ToolErrorCode | None,
        result_sha256: str | None,
    ) -> ToolInvocationRecord:
        return ToolInvocationRecord(
            invocation_id=f"{context.run_id}:{context.agent}:{context.step}:{call.tool}",
            run_id=context.run_id,
            case_id=context.case_id,
            agent=context.agent,
            step=context.step,
            tool=call.tool,
            arguments=arguments,
            arguments_sha256=sha256_hex(call.arguments),
            ok=ok,
            error_code=error_code,
            result_sha256=result_sha256,
            started_at=started_at,
            finished_at=self._clock(),
        )
