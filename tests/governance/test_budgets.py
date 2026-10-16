"""Per-run budgets: durable atomic counters, refusals, safe escalation and spend reporting."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from caseforge.composition import build_container
from caseforge.governance.budgets import LlmBudget
from caseforge.governance.control_plane import ControlPlane
from caseforge.governance.guards import GovernedTools
from caseforge.governance.permissions import APPROVE_ACTION
from caseforge.governance.store import GovernanceStore
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.models import CallContext, ModelSpec, TokenUsage
from caseforge.reasoning.ports import ReasonerCallError
from caseforge.reasoning.prompts import PromptRegistry
from caseforge.reasoning.structured import StructuredCaller
from caseforge.settings.models import BudgetSettings, GovernanceSettings, ModelPricing
from caseforge.tools.models import ToolCall, ToolContext, ToolErrorCode

ROOT = Path(__file__).resolve().parents[2]
FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
LIMITS = BudgetSettings(max_llm_calls=2, max_total_tokens=1000, max_cost_usd=0.5, max_tool_calls=1)


def _plane(path: Path, pricing: ModelPricing | None = None) -> tuple[GovernanceStore, ControlPlane]:
    settings = GovernanceSettings.model_validate(
        {
            "roles": {"approver": [APPROVE_ACTION]},
            "operators": {"approver-1": ["approver"]},
            "budgets": LIMITS.model_dump(),
        }
    )
    store = GovernanceStore(path)
    return store, ControlPlane(store, settings, clock=lambda: FIXED, pricing=pricing)


def test_model_calls_are_counted_durably_and_refused_at_the_limit(tmp_path: Path) -> None:
    path = tmp_path / "governance.db"
    store, plane = _plane(path)
    assert plane.reserve_llm_call("run-1").allowed
    store.close()
    store, plane = _plane(path)  # a restart cannot reset the count
    assert plane.reserve_llm_call("run-1").allowed
    refused = plane.reserve_llm_call("run-1")
    audit = plane.audit_entries(action="budget.exhausted")
    store.close()
    assert refused.allowed is False
    assert "model call limit" in refused.reason
    assert refused.usage.llm_calls == 2
    assert [(e.target, e.detail["kind"]) for e in audit] == [("run-1", "model")]


def test_token_and_cost_limits_use_recorded_usage(tmp_path: Path) -> None:
    pricing = ModelPricing(input_usd_per_million=1000, output_usd_per_million=1000)
    store, plane = _plane(tmp_path / "governance.db", pricing)
    plane.reserve_llm_call("tokens")
    plane.record_llm_usage("tokens", TokenUsage(input_tokens=600, output_tokens=500))
    assert "token limit" in plane.reserve_llm_call("tokens").reason
    plane.reserve_llm_call("cost")
    usage = plane.record_llm_usage("cost", TokenUsage(input_tokens=300, output_tokens=300))
    assert usage.cost_usd == pytest.approx(0.6)
    assert "cost limit" in plane.reserve_llm_call("cost").reason
    store.close()


def test_exhausted_budget_stops_the_model_call_before_it_is_made(tmp_path: Path) -> None:
    store, plane = _plane(tmp_path / "governance.db")
    for _ in range(2):
        plane.reserve_llm_call("run-1")
    reasoner = FakeReasoner({"evidence": []})
    caller = StructuredCaller(
        reasoner,
        PromptRegistry.from_directory(ROOT / "config" / "prompts"),
        ModelSpec(provider="fake", model="m"),
        clock=lambda: FIXED,
        budget=LlmBudget(plane),
    )
    from caseforge.agents.contracts import EvidenceStep

    variables = {
        "case_id": "c",
        "question": "q",
        "steps_remaining": "1",
        "tools": "[]",
        "transcript": "[]",
    }
    with pytest.raises(ReasonerCallError) as info:
        caller.call(
            "evidence",
            variables,
            EvidenceStep,
            CallContext(run_id="run-1", node="evidence", step=0),
        )
    store.close()
    assert info.value.record.status == "error"
    assert "model call limit" in info.value.record.error
    assert reasoner.requests == []


def test_tool_budget_returns_a_typed_refusal(tmp_path: Path) -> None:
    store, plane = _plane(tmp_path / "governance.db")

    class Registry:
        invoked = 0

        def describe(self, agent):
            return []

        def invoke(self, call, context):
            Registry.invoked += 1
            return "ok"

        def refuse(self, call, context, code, detail):
            return (code, detail)

    tools = GovernedTools(Registry(), lambda boundary: None, budget=plane)
    context = ToolContext(
        run_id="run-1", tenant_id="t", case_id="c", as_of=FIXED, agent="evidence", step=0
    )
    assert tools.invoke(ToolCall(tool="get_case"), context) == "ok"
    code, detail = tools.invoke(ToolCall(tool="get_case"), context)
    store.close()
    assert code == ToolErrorCode.BUDGET_EXHAUSTED
    assert "tool call limit" in detail
    assert Registry.invoked == 1


SCRIPT = {
    "supervisor_plan": [
        {"objective": "Decide the request.", "workers": [], "rationale": "Summary suffices."}
    ],
    "supervisor_synthesis": [
        {
            "decision": "escalate",
            "rationale": "A person decides.",
            "escalation_reason": "Needs review.",
        }
    ],
}


def test_a_spent_budget_ends_in_safe_escalation(config_copy) -> None:
    environ = {"CASEFORGE__GOVERNANCE__BUDGETS__MAX_LLM_CALLS": "1"}
    with build_container(
        config_copy, environ=environ, clock=lambda: FIXED, reasoner=FakeReasoner(SCRIPT)
    ) as container:
        world = container.open_simulated_case("policy-question", 1)
        final = container.run_case("run-0001", world.case_id)
        usage = container.run_usage("run-0001")
        refusals = container.control_plane.audit_entries(action="budget.exhausted")
    assert final["decision"]["source"] == "escalation"
    assert "model call limit" in final["decision"]["reason"]
    assert [a.action_type for a in world.ground_truth().actions] == ["escalate_case"]
    assert usage.llm_calls == 1
    assert len(refusals) == 1


def test_run_usage_reports_spend_for_a_normal_run(config_copy) -> None:
    with build_container(
        config_copy, environ={}, clock=lambda: FIXED, reasoner=FakeReasoner(SCRIPT)
    ) as container:
        world = container.open_simulated_case("policy-question", 1)
        container.run_case("run-0001", world.case_id)
        usage = container.run_usage("run-0001")
    assert (usage.llm_calls, usage.tool_calls) == (2, 1)
    assert usage.total_tokens > 0
    assert usage.cost_usd == 0.0
