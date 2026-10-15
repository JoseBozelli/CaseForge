"""Typed contracts for worker decisions and findings.

Rationales are short decision summaries for the record, not hidden reasoning.
Every finding cites the source ids (event ids or knowledge chunk ids) it relies on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from caseforge.events.envelope import NonEmptyStr


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


class ToolRequest(_Strict):
    tool: NonEmptyStr
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


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
