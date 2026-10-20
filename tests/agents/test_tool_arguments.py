"""Tool arguments travel as a JSON string for structured outputs and arrive as a dict."""

import pytest
from anthropic import transform_schema
from pydantic import ValidationError

from caseforge.agents.contracts import (
    EvidenceStep,
    PolicyStep,
    SingleAgentStep,
    SupervisorPlan,
    Synthesis,
    ToolRequest,
)


def test_arguments_given_as_a_json_string_are_decoded() -> None:
    request = ToolRequest(tool="search_policies", arguments='{"query": "late task"}')
    assert request.arguments == {"query": "late task"}
    assert ToolRequest(tool="get_case", arguments="").arguments == {}
    assert ToolRequest(tool="get_case").arguments == {}


@pytest.mark.parametrize("bad", ["[1, 2]", "not json", '"text"'])
def test_arguments_must_decode_to_an_object(bad: str) -> None:
    with pytest.raises(ValidationError, match="JSON object"):
        ToolRequest(tool="get_case", arguments=bad)


@pytest.mark.parametrize(
    "model", [SupervisorPlan, Synthesis, EvidenceStep, PolicyStep, SingleAgentStep]
)
def test_every_agent_contract_is_accepted_by_structured_outputs(model) -> None:
    transform_schema(model.model_json_schema())  # raises if the schema is not expressible


def test_escalation_reason_allows_a_thorough_explanation() -> None:
    reason = "x" * 1200
    synthesis = Synthesis(
        decision="escalate", rationale="Needs a person.", escalation_reason=reason
    )
    assert len(synthesis.escalation_reason) == 1200
    with pytest.raises(ValidationError):
        Synthesis(decision="escalate", rationale="Too long.", escalation_reason="x" * 1501)
