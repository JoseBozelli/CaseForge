"""Tests for tool dispatch: validation, permissions and failure isolation."""

from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ConfigDict, Field

from caseforge.common.errors import ConfigError
from caseforge.common.hashing import sha256_hex
from caseforge.tools.models import ToolCall, ToolContext, ToolErrorCode, ToolPolicy
from caseforge.tools.registry import ToolRegistry, ToolSpec

FIXED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    times: int = Field(default=1, ge=1, le=3)


class EchoResult(BaseModel):
    text: str


def _echo(args, context, policy):
    return EchoResult(text=args.text * args.times)


def _boom(args, context, policy):
    raise RuntimeError("internal detail that must not leak")


SPECS = (
    ToolSpec("echo", "Repeat text.", "read", EchoArgs, EchoResult, _echo),
    ToolSpec("boom", "Always fails.", "read", EchoArgs, EchoResult, _boom),
    ToolSpec("change_thing", "Mutates state.", "mutate", EchoArgs, EchoResult, _echo),
    ToolSpec("hidden", "Has no policy.", "read", EchoArgs, EchoResult, _echo),
)
POLICIES = {
    "echo": ToolPolicy(allowed_agents={"evidence"}),
    "boom": ToolPolicy(allowed_agents={"evidence"}),
    "change_thing": ToolPolicy(allowed_agents={"evidence"}),
}
CONTEXT = ToolContext(
    run_id="run-0001",
    tenant_id="tenant-a",
    case_id="case-0001",
    as_of=FIXED,
    agent="evidence",
    step=2,
)


def _registry(policies=None) -> ToolRegistry:
    return ToolRegistry(SPECS, POLICIES if policies is None else policies, clock=lambda: FIXED)


def _invoke(tool, arguments, context=CONTEXT, registry=None):
    return (registry or _registry()).invoke(ToolCall(tool=tool, arguments=arguments), context)


def test_valid_call_returns_output_and_record() -> None:
    outcome = _invoke("echo", {"text": "hi", "times": 2})
    assert outcome.result.ok is True
    assert outcome.result.output == {"text": "hihi"}
    record = outcome.record
    assert record.invocation_id == "run-0001:evidence:2:echo"
    assert record.arguments == {"text": "hi", "times": 2}
    assert record.arguments_sha256 == sha256_hex({"text": "hi", "times": 2})
    assert record.result_sha256 == sha256_hex({"text": "hihi"})
    assert (record.started_at, record.finished_at) == (FIXED, FIXED)


def test_unknown_tool_reported() -> None:
    assert _invoke("ghost", {}).result.error_code == ToolErrorCode.UNKNOWN_TOOL


def test_agent_not_listed_is_denied() -> None:
    policy_agent = CONTEXT.model_copy(update={"agent": "policy"})
    outcome = _invoke("echo", {"text": "hi"}, context=policy_agent)
    assert outcome.result.error_code == ToolErrorCode.NOT_PERMITTED


def test_disabled_tool_is_denied() -> None:
    disabled = {**POLICIES, "echo": ToolPolicy(enabled=False, allowed_agents={"evidence"})}
    outcome = _invoke("echo", {"text": "hi"}, registry=_registry(disabled))
    assert outcome.result.error_code == ToolErrorCode.NOT_PERMITTED


def test_tool_without_policy_is_denied_by_default() -> None:
    assert _invoke("hidden", {"text": "hi"}).result.error_code == ToolErrorCode.NOT_PERMITTED


def test_invalid_arguments_reported() -> None:
    outcome = _invoke("echo", {"text": "hi", "times": 9, "extra": 1})
    assert outcome.result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert "times" in (outcome.result.error or "")
    assert outcome.record.arguments is None


def test_tool_failure_is_isolated_and_does_not_leak_details() -> None:
    outcome = _invoke("boom", {"text": "hi"})
    assert outcome.result.error_code == ToolErrorCode.TOOL_ERROR
    assert outcome.result.error == "RuntimeError"


def test_mutating_tool_refused_without_governed_execution() -> None:
    outcome = _invoke("change_thing", {"text": "hi"})
    assert outcome.result.error_code == ToolErrorCode.NOT_PERMITTED
    assert outcome.result.error == "requires governed execution"


def test_policy_for_unregistered_tool_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown tools"):
        _registry({**POLICIES, "ghost": ToolPolicy(allowed_agents={"evidence"})})


def test_describe_lists_only_permitted_read_tools() -> None:
    registry = _registry()
    described = registry.describe("evidence")
    assert [tool["name"] for tool in described] == ["boom", "echo"]
    assert described[1]["parameters"]["properties"]["text"]["type"] == "string"
    assert registry.describe("policy") == []
