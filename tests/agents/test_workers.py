"""Worker loop tests driven by scripted fake-reasoner trajectories."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from caseforge.agents.contracts import EvidenceStep, PolicyStep
from caseforge.agents.workers import WorkerStatus, evidence_worker, policy_worker
from caseforge.knowledge.bm25 import Bm25KnowledgeProvider
from caseforge.knowledge.corpus import load_corpus
from caseforge.memory.empty import EmptyEpisodeProvider
from caseforge.persistence.memory import InMemoryRecordStore
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.models import ModelSpec
from caseforge.reasoning.prompts import PromptRegistry
from caseforge.reasoning.structured import StructuredCaller
from caseforge.tools.builtin import read_tools
from caseforge.tools.models import ToolErrorCode, ToolPolicy
from caseforge.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
AS_OF = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
MODEL = ModelSpec(provider="fake", model="fake-model")
POLICIES = {
    "get_case": ToolPolicy(allowed_agents={"evidence"}),
    "get_timeline": ToolPolicy(allowed_agents={"evidence"}),
    "search_policies": ToolPolicy(allowed_agents={"policy"}, max_results=3),
}
TIMELINE = {
    "action": "call_tool",
    "rationale": "Read the case timeline.",
    "tool": {"tool": "get_timeline", "arguments": {}},
}


def _finish_evidence(*source_ids: str) -> dict:
    facts = [{"statement": "The task passed its due time.", "source_ids": list(source_ids)}]
    return {
        "action": "finish",
        "rationale": "The facts are sufficient.",
        "findings": {"summary": "The task is overdue.", "facts": facts if source_ids else []},
    }


@pytest.fixture(scope="module")
def prompts() -> PromptRegistry:
    return PromptRegistry.from_directory(ROOT / "config" / "prompts")


@pytest.fixture
def tools(make_event) -> ToolRegistry:
    store = InMemoryRecordStore()
    store.append_events([make_event()])
    chunks = load_corpus(ROOT / "config" / "knowledge" / "policies").chunks
    knowledge = Bm25KnowledgeProvider(chunks, k1=1.5, b=0.75, min_score=1.0)
    specs = read_tools(store, knowledge, EmptyEpisodeProvider())
    return ToolRegistry(specs, POLICIES, clock=lambda: AS_OF)


def _caller(prompts, template_id: str, outputs: list[dict]):
    reasoner = FakeReasoner({template_id: outputs})
    return StructuredCaller(reasoner, prompts, MODEL, clock=lambda: AS_OF), reasoner


def _run(worker):
    return worker.run(
        run_id="run-0001",
        tenant_id="tenant-a",
        case_id="case-0001",
        as_of=AS_OF,
        question="Why is the case stalled?",
    )


def _evidence(prompts, tools, outputs, max_steps: int = 4):
    caller, reasoner = _caller(prompts, "evidence", outputs)
    worker = evidence_worker(caller=caller, tools=tools, template_version=1, max_steps=max_steps)
    return worker, reasoner


def test_evidence_worker_completes_with_grounded_findings(prompts, tools) -> None:
    worker, _ = _evidence(prompts, tools, [TIMELINE, _finish_evidence("evt-0001")])
    result = _run(worker)
    assert result.status == WorkerStatus.COMPLETED
    assert result.steps_used == 2
    assert result.findings["facts"][0]["source_ids"] == ["evt-0001"]
    assert (len(result.llm_calls), len(result.tool_calls)) == (2, 1)


def test_records_are_linked_to_run_worker_and_step(prompts, tools) -> None:
    worker, _ = _evidence(prompts, tools, [TIMELINE, _finish_evidence("evt-0001")])
    result = _run(worker)
    assert [r.call_id for r in result.llm_calls] == ["run-0001:evidence:0", "run-0001:evidence:1"]
    assert result.tool_calls[0].invocation_id == "run-0001:evidence:0:get_timeline"
    assert result.tool_calls[0].ok is True


def test_citing_an_unobserved_source_is_ungrounded(prompts, tools) -> None:
    worker, _ = _evidence(prompts, tools, [_finish_evidence("evt-9999")])
    result = _run(worker)
    assert result.status == WorkerStatus.UNGROUNDED
    assert "evt-9999" in (result.error or "")
    assert result.steps_used == 1


def test_step_budget_exhaustion_is_incomplete(prompts, tools) -> None:
    worker, _ = _evidence(prompts, tools, [TIMELINE, TIMELINE], max_steps=2)
    result = _run(worker)
    assert result.status == WorkerStatus.INCOMPLETE
    assert result.error == "step budget exhausted"
    assert (result.steps_used, len(result.tool_calls)) == (2, 2)


def test_tool_error_becomes_an_observation(prompts, tools) -> None:
    forbidden = {
        "action": "call_tool",
        "rationale": "Look up the procedure.",
        "tool": {"tool": "search_policies", "arguments": {"query": "overdue"}},
    }
    worker, reasoner = _evidence(prompts, tools, [forbidden, _finish_evidence()])
    result = _run(worker)
    assert result.status == WorkerStatus.COMPLETED
    assert result.tool_calls[0].error_code == ToolErrorCode.NOT_PERMITTED
    assert "not_permitted" in reasoner.requests[1].prompt


def test_invalid_model_output_fails_without_raising(prompts, tools) -> None:
    worker, _ = _evidence(prompts, tools, [{"action": "finish", "rationale": "Done."}])
    result = _run(worker)
    assert result.status == WorkerStatus.FAILED
    assert result.llm_calls[0].status == "invalid_output"


def test_reasoner_error_fails_without_raising(prompts, tools) -> None:
    worker, _ = _evidence(prompts, tools, [])
    result = _run(worker)
    assert result.status == WorkerStatus.FAILED
    assert result.llm_calls[0].status == "error"


def test_unexpected_exception_fails_without_raising(prompts) -> None:
    class BrokenTools:
        def describe(self, agent):
            return []

        def invoke(self, call, context):
            raise RuntimeError("internal detail")

    worker, _ = _evidence(prompts, BrokenTools(), [TIMELINE])
    result = _run(worker)
    assert result.status == WorkerStatus.FAILED
    assert result.error == "RuntimeError"


def test_policy_worker_completes_with_cited_passage(prompts, tools) -> None:
    chunk = "document-requests#wrong-document-received"
    outputs = [
        {
            "action": "call_tool",
            "rationale": "Search the procedures.",
            "tool": {
                "tool": "search_policies",
                "arguments": {"query": "wrong document type uploaded"},
            },
        },
        {
            "action": "finish",
            "rationale": "The applicable requirement was found.",
            "findings": {
                "summary": "A wrong document must be requested again.",
                "requirements": [
                    {"statement": "Request the correct document type.", "source_ids": [chunk]}
                ],
            },
        },
    ]
    caller, _ = _caller(prompts, "policy", outputs)
    worker = policy_worker(caller=caller, tools=tools, template_version=1, max_steps=3)
    result = _run(worker)
    assert result.status == WorkerStatus.COMPLETED
    assert result.findings["requirements"][0]["source_ids"] == [chunk]


@pytest.mark.parametrize(
    "decision",
    [
        {"action": "call_tool", "rationale": "x"},
        {
            "action": "finish",
            "rationale": "x",
            "tool": {"tool": "get_case"},
            "findings": {"summary": "s"},
        },
    ],
)
def test_step_contract_rejects_inconsistent_decisions(decision) -> None:
    with pytest.raises(ValidationError):
        EvidenceStep.model_validate(decision)


def test_shipped_prompts_match_worker_contracts(prompts) -> None:
    expected = {"case_id", "question", "steps_remaining", "tools", "transcript"}
    for template_id, model in (("evidence", EvidenceStep), ("policy", PolicyStep)):
        template = prompts.get(template_id, 1)
        assert template.output_schema == model.__name__
        assert template.variables() == expected
