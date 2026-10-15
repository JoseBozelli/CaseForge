"""Tool wiring through the composition root."""

import pytest

from caseforge.common.errors import ConfigError
from caseforge.composition import build_container


def test_container_exposes_configured_tools(config_copy) -> None:
    with build_container(config_copy, environ={}) as container:
        evidence = [spec.name for spec in container.tools.available("evidence")]
        policy = [spec.name for spec in container.tools.available("policy")]
    assert evidence == ["get_case", "get_timeline", "search_prior_episodes"]
    assert policy == ["search_policies"]


def test_policy_for_unknown_tool_fails_at_startup(config_copy) -> None:
    text = config_copy.read_text(encoding="utf-8")
    config_copy.write_text(
        text.rstrip("\n") + "\n  delete_everything: {allowed_agents: [evidence]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown tools"):
        build_container(config_copy, environ={})
