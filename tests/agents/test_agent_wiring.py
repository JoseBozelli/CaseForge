"""Agent and reasoner wiring through settings and the composition root."""

import pytest

from caseforge.agents.supervisor import SupervisorStatus
from caseforge.common.errors import ConfigError
from caseforge.composition import build_container
from caseforge.reasoning.fake import FakeReasoner

PLAN = {
    "objective": "Get the stalled task completed.",
    "workers": [],
    "rationale": "The case summary is sufficient.",
}


def _edit(path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_container_builds_supervisor_and_workers(config_copy) -> None:
    with build_container(config_copy, environ={}) as container:
        assert set(container.workers) == {"evidence", "policy"}
        names = {path.name for path in container.loaded.config_files}
    assert {"supervisor_plan.v1.md", "evidence.v1.md"} <= names


def test_unscripted_fake_reasoner_fails_gracefully(config_copy) -> None:
    with build_container(config_copy, environ={}) as container:
        result = container.supervisor.plan(run_id="r", case_id="c", case_summary={})
    assert result.status == SupervisorStatus.FAILED


def test_injected_reasoner_is_used(config_copy) -> None:
    reasoner = FakeReasoner({"supervisor_plan": [PLAN]})
    with build_container(config_copy, environ={}, reasoner=reasoner) as container:
        result = container.supervisor.plan(run_id="r", case_id="c", case_summary={})
    assert result.status == SupervisorStatus.OK


def test_missing_prompt_version_fails_at_startup(config_copy) -> None:
    _edit(config_copy, "plan_version: 1", "plan_version: 9")
    with pytest.raises(ConfigError, match="missing prompt template supervisor_plan v9"):
        build_container(config_copy, environ={})


def test_triage_action_must_be_allowed(config_copy) -> None:
    _edit(config_copy, "allowed_actions: [send_reminder, ", "allowed_actions: [")
    with pytest.raises(ConfigError, match="triage actions not in"):
        build_container(config_copy, environ={})
