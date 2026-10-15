"""Tests for deterministic triage rules."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from caseforge.common.errors import ConfigError
from caseforge.engine.triage import TriageDecision, TriagePolicy
from caseforge.settings.loader import load_settings


def _policy() -> TriagePolicy:
    return TriagePolicy.model_validate(
        {
            "default_action": "escalate_case",
            "rules": [
                {
                    "id": "first",
                    "when_all": ["task.delayed"],
                    "unless_any": ["policy.exception"],
                    "action": "send_reminder",
                },
                {"id": "second", "when_all": ["task.delayed"], "action": "reassign_task"},
            ],
        }
    )


def test_first_matching_rule_wins() -> None:
    assert _policy().decide(["task.delayed"]) == TriageDecision("first", "send_reminder")


def test_unless_condition_falls_through_to_next_rule() -> None:
    decision = _policy().decide(["task.delayed", "policy.exception"])
    assert decision == TriageDecision("second", "reassign_task")


def test_default_action_when_no_rule_matches() -> None:
    assert _policy().decide(["case.created"]) == TriageDecision(None, "escalate_case")


def test_duplicate_rule_ids_rejected() -> None:
    rule = {"id": "same", "when_all": ["task.delayed"], "action": "send_reminder"}
    with pytest.raises(ValidationError, match="duplicate triage rule ids"):
        TriagePolicy.model_validate({"default_action": "escalate_case", "rules": [rule, rule]})


def test_loader_rejects_unknown_triage_event_type(config_copy: Path) -> None:
    text = config_copy.read_text(encoding="utf-8")
    config_copy.write_text(
        text.replace("when_all: [task.delayed]", "when_all: [task.vanished]", 1), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="triage rules reference unknown event types"):
        load_settings(config_copy, environ={})
