"""Circuit breakers and bounded executor retries."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from caseforge.governance.control_plane import ControlPlane, PermissionDenied
from caseforge.governance.guards import GovernedExecutor, GovernedReasoner, GovernedTools
from caseforge.governance.permissions import MANAGE_BREAKERS
from caseforge.governance.store import GovernanceStore
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.ports import CircuitOpen, ReasonerError
from caseforge.settings.models import GovernanceSettings
from caseforge.tools.models import ToolCall, ToolContext, ToolErrorCode, ToolPolicy
from caseforge.tools.registry import ToolRegistry, ToolSpec

T0 = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
SETTINGS = GovernanceSettings.model_validate(
    {
        "roles": {"viewer": [], "admin": [MANAGE_BREAKERS]},
        "operators": {"viewer-1": ["viewer"], "admin-1": ["admin"]},
        "breakers": {"failure_threshold": 2, "cooldown_seconds": 60},
    }
)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def setup(tmp_path: Path):
    clock = Clock()
    store = GovernanceStore(tmp_path / "governance.db")
    yield ControlPlane(store, SETTINGS, clock=clock), clock
    store.close()


def test_repeated_failures_open_the_breaker_and_are_audited(setup) -> None:
    plane, _ = setup
    plane.breaker_failure("executor")
    assert plane.breaker_allows("executor") is True
    plane.breaker_failure("executor")
    assert plane.breaker("executor").state == "open"
    assert plane.breaker_allows("executor") is False
    assert [e.action for e in plane.audit_entries(target="breaker:executor")] == ["breaker.open"]


def test_cooldown_allows_one_trial_then_closes_or_reopens(setup) -> None:
    plane, clock = setup
    for _ in range(2):
        plane.breaker_failure("reasoner")
    clock.now = T0 + timedelta(seconds=61)
    assert plane.breaker_allows("reasoner") is True
    assert plane.breaker("reasoner").state == "half_open"
    plane.breaker_failure("reasoner")  # a failed trial reopens immediately
    assert plane.breaker("reasoner").state == "open"
    clock.now = T0 + timedelta(seconds=200)
    assert plane.breaker_allows("reasoner") is True
    plane.breaker_success("reasoner")
    assert plane.breaker("reasoner").state == "closed"


def test_reset_requires_permission_and_is_audited(setup) -> None:
    plane, _ = setup
    for _ in range(2):
        plane.breaker_failure("executor")
    with pytest.raises(PermissionDenied):
        plane.reset_breaker("viewer-1", "executor")
    assert plane.reset_breaker("admin-1", "executor").state == "closed"
    actions = [e.action for e in plane.audit_entries(target="breaker:executor")]
    assert actions[-2:] == [MANAGE_BREAKERS, "breaker.reset"]


def test_open_reasoner_breaker_stops_model_calls(setup) -> None:
    plane, _ = setup
    inner = FakeReasoner({})  # every call fails: nothing scripted
    reasoner = GovernedReasoner(inner, lambda boundary: None, breakers=plane)
    for _ in range(2):
        with pytest.raises(ReasonerError):
            reasoner.complete(_request())
    with pytest.raises(CircuitOpen):
        reasoner.complete(_request())
    assert len(inner.requests) == 2  # the third call never reached the provider


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def _boom(args, context, policy):
    raise RuntimeError("tool is broken")


def test_tool_breaker_counts_tool_errors_but_not_caller_mistakes(setup) -> None:
    plane, _ = setup
    registry = ToolRegistry(
        [ToolSpec("boom", "Fails.", "read", EchoArgs, EchoArgs, _boom)],
        {"boom": ToolPolicy(allowed_agents={"evidence"})},
        clock=lambda: T0,
    )
    tools = GovernedTools(registry, lambda boundary: None, breakers=plane)
    context = ToolContext(
        run_id="r", tenant_id="t", case_id="c", as_of=T0, agent="evidence", step=0
    )
    bad_args = ToolCall(tool="boom", arguments={"wrong": 1})
    for _ in range(3):
        assert tools.invoke(bad_args, context).result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert plane.breaker("tool:boom").state == "closed"
    good_args = ToolCall(tool="boom", arguments={"text": "x"})
    for _ in range(2):
        assert tools.invoke(good_args, context).result.error_code == ToolErrorCode.TOOL_ERROR
    assert tools.invoke(good_args, context).result.error_code == ToolErrorCode.CIRCUIT_OPEN


class FlakyExecutor:
    def __init__(self, failures: int, idempotent: bool) -> None:
        self.failures = failures
        self.calls = 0
        self.supports_idempotency_keys = idempotent

    def execute(self, **kwargs) -> bool:
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError("no answer")
        return True


def _execute(executor) -> bool:
    return executor.execute(
        tenant_id="t", case_id="c", action_id="r:send_reminder", action_type="send_reminder", at=T0
    )


def test_idempotent_executor_is_retried_with_backoff(setup) -> None:
    plane, _ = setup
    inner, sleeps = FlakyExecutor(failures=1, idempotent=True), []
    executor = GovernedExecutor(
        inner, plane, max_attempts=3, backoff_seconds=0.5, sleep=sleeps.append
    )
    assert _execute(executor) is True
    assert (inner.calls, sleeps) == (2, [0.5])
    assert plane.breaker("executor").state == "closed"


def test_non_idempotent_executor_is_never_retried(setup) -> None:
    plane, _ = setup
    inner, sleeps = FlakyExecutor(failures=1, idempotent=False), []
    executor = GovernedExecutor(
        inner, plane, max_attempts=3, backoff_seconds=0.5, sleep=sleeps.append
    )
    with pytest.raises(TimeoutError):
        _execute(executor)
    assert (inner.calls, sleeps) == (1, [])


def _request():
    from caseforge.reasoning.models import ModelSpec, ReasonerRequest

    return ReasonerRequest(
        model=ModelSpec(provider="fake", model="m"),
        template_id="evidence",
        template_version=1,
        template_sha256="a" * 64,
        prompt="p",
        output_schema_name="EvidenceStep",
        output_schema={},
    )
