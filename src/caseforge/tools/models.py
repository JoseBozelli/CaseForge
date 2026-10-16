"""Tool contracts: execution context, calls, results, policies and invocation records."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from caseforge.events.envelope import NonEmptyStr, Sha256Hex, UtcDatetime
from caseforge.events.vocabulary import Name


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolContext(_Frozen):
    """Set by the engine, never by the model: tools cannot reach other cases or the future."""

    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    case_id: NonEmptyStr
    as_of: UtcDatetime
    agent: Name
    step: int = Field(ge=0)


class ToolCall(_Frozen):
    tool: NonEmptyStr
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ToolPolicy(_Frozen):
    """Configured permission for one tool. Tools without a policy are denied."""

    enabled: bool = True
    allowed_agents: frozenset[Name] = Field(min_length=1)
    max_results: int = Field(default=10, ge=1)


class ToolErrorCode(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    NOT_PERMITTED = "not_permitted"
    INVALID_ARGUMENTS = "invalid_arguments"
    TOOL_ERROR = "tool_error"
    BUDGET_EXHAUSTED = "budget_exhausted"


class ToolResult(_Frozen):
    """What the agent observes: an output on success, a typed error otherwise."""

    tool: NonEmptyStr
    ok: bool
    output: dict[str, JsonValue] | None = None
    error_code: ToolErrorCode | None = None
    error: str | None = None


class ToolInvocationRecord(_Frozen):
    invocation_id: NonEmptyStr
    run_id: NonEmptyStr
    case_id: NonEmptyStr
    agent: NonEmptyStr
    step: int
    tool: NonEmptyStr
    arguments: dict[str, JsonValue] | None
    arguments_sha256: Sha256Hex
    ok: bool
    error_code: ToolErrorCode | None
    result_sha256: Sha256Hex | None
    started_at: UtcDatetime
    finished_at: UtcDatetime
