"""Typed contracts for worker decisions and findings.

Rationales are short decision summaries for the record, not hidden reasoning.
Every finding cites the source ids (event ids or knowledge chunk ids) it relies on.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from caseforge.events.envelope import NonEmptyStr
from caseforge.events.vocabulary import Name

WorkerName = Literal["evidence", "policy"]


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourcedFact(_Strict):
    statement: str = Field(min_length=1, max_length=500)
    source_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)


class EvidenceFindings(_Strict):
    summary: str = Field(min_length=1, max_length=1000)
    facts: tuple[SourcedFact, ...] = ()
    uncertainties: tuple[str, ...] = ()
    missing_context: tuple[str, ...] = ()

    def cited_sources(self) -> set[str]:
        return {source for fact in self.facts for source in fact.source_ids}


class PolicyFindings(_Strict):
    summary: str = Field(min_length=1, max_length=1000)
    requirements: tuple[SourcedFact, ...] = ()
    exceptions: tuple[SourcedFact, ...] = ()
    conflicts: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()

    def cited_sources(self) -> set[str]:
        return {s for fact in (*self.requirements, *self.exceptions) for s in fact.source_ids}


ToolArguments = Annotated[
    dict[str, JsonValue],
    WithJsonSchema(
        {
            "type": "string",
            "description": (
                'Tool arguments as a JSON object encoded in a string, e.g. "{\\"query\\": '
                '\\"late task\\"}". Use "{}" when the tool takes no arguments.'
            ),
        }
    ),
]


class ToolRequest(_Strict):
    """The model sends arguments as a JSON string (structured outputs cannot express a
    free-form object); they are decoded here, so everything downstream sees a dict."""

    tool: NonEmptyStr
    arguments: ToolArguments = Field(default_factory=dict)

    @field_validator("arguments", mode="before")
    @classmethod
    def _decode(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                value = json.loads(value) if value.strip() else {}
            except json.JSONDecodeError as exc:
                raise ValueError("arguments must be a JSON object") from exc
            if not isinstance(value, dict):
                raise ValueError("arguments must be a JSON object")
        return value


class _Step(_Strict):
    """One worker decision: call exactly one tool, or finish with findings."""

    action: Literal["call_tool", "finish"]
    rationale: str = Field(min_length=1, max_length=300)
    tool: ToolRequest | None = None

    @model_validator(mode="after")
    def _consistent(self) -> _Step:
        findings = getattr(self, "findings", None)
        if self.action == "call_tool" and (self.tool is None or findings is not None):
            raise ValueError("call_tool requires a tool request and no findings")
        if self.action == "finish" and (findings is None or self.tool is not None):
            raise ValueError("finish requires findings and no tool request")
        return self


class EvidenceStep(_Step):
    findings: EvidenceFindings | None = None


class PolicyStep(_Step):
    findings: PolicyFindings | None = None


class SupervisorPlan(_Strict):
    """Which workers a case needs, with one focused question per selected worker."""

    objective: str = Field(min_length=1, max_length=500)
    workers: tuple[WorkerName, ...] = ()
    evidence_question: str | None = Field(default=None, min_length=1, max_length=500)
    policy_question: str | None = Field(default=None, min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _consistent(self) -> SupervisorPlan:
        if len(set(self.workers)) != len(self.workers):
            raise ValueError("workers must be unique")
        for worker in ("evidence", "policy"):
            question = getattr(self, f"{worker}_question")
            if (worker in self.workers) != (question is not None):
                raise ValueError(
                    f"{worker}_question must be given exactly when {worker} is selected"
                )
        return self

    def question_for(self, worker: str) -> str | None:
        return getattr(self, f"{worker}_question", None)


class ActionProposal(_Strict):
    action_type: Name
    evidence_refs: tuple[NonEmptyStr, ...] = ()


class Clarification(_Strict):
    worker: WorkerName
    question: str = Field(min_length=1, max_length=500)


class Synthesis(_Strict):
    """Exactly one decision: propose an action, escalate, or ask one worker to clarify."""

    decision: Literal["propose_action", "escalate", "clarify"]
    rationale: str = Field(min_length=1, max_length=300)
    candidate_actions: tuple[Name, ...] = ()
    proposal: ActionProposal | None = None
    escalation_reason: str | None = Field(default=None, min_length=1, max_length=1500)
    clarification: Clarification | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Synthesis:
        payloads = {
            "propose_action": self.proposal,
            "escalate": self.escalation_reason,
            "clarify": self.clarification,
        }
        for decision, payload in payloads.items():
            if (decision == self.decision) != (payload is not None):
                raise ValueError(f"{decision} must carry exactly its own payload")
        if self.proposal and self.proposal.action_type not in self.candidate_actions:
            raise ValueError("the proposed action must be among candidate_actions")
        return self


class SingleAgentStep(_Strict):
    """One single-agent decision: call exactly one tool, or decide the case."""

    action: Literal["call_tool", "decide"]
    rationale: str = Field(min_length=1, max_length=300)
    tool: ToolRequest | None = None
    decision: Synthesis | None = None

    @model_validator(mode="after")
    def _consistent(self) -> SingleAgentStep:
        if self.action == "call_tool" and (self.tool is None or self.decision is not None):
            raise ValueError("call_tool requires a tool request and no decision")
        if self.action == "decide" and (self.decision is None or self.tool is not None):
            raise ValueError("decide requires a decision and no tool request")
        if self.decision is not None and self.decision.decision == "clarify":
            raise ValueError("a single agent cannot ask for clarification")
        return self
