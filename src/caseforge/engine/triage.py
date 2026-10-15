"""Deterministic, configuration-driven triage over canonical event types."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseforge.events.vocabulary import EventTypeName, Identifier, Name


@dataclass(frozen=True)
class TriageDecision:
    rule_id: str | None
    action_type: str


class TriageRule(BaseModel):
    """Matches when all when_all types are present and none of unless_any are."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    when_all: frozenset[EventTypeName] = Field(min_length=1)
    unless_any: frozenset[EventTypeName] = frozenset()
    action: Name


class TriagePolicy(BaseModel):
    """Ordered rules; the first matching rule wins, otherwise default_action applies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_action: Name
    rules: tuple[TriageRule, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> TriagePolicy:
        ids = [rule.id for rule in self.rules]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate triage rule ids {duplicates}")
        return self

    def referenced_event_types(self) -> set[str]:
        return {t for rule in self.rules for t in rule.when_all | rule.unless_any}

    def decide(self, event_types: Iterable[str]) -> TriageDecision:
        present = set(event_types)
        for rule in self.rules:
            if rule.when_all <= present and not rule.unless_any & present:
                return TriageDecision(rule_id=rule.id, action_type=rule.action)
        return TriageDecision(rule_id=None, action_type=self.default_action)
