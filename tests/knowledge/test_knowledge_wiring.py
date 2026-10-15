"""Knowledge wiring through settings and the composition root."""

from datetime import UTC, datetime

import pytest

from caseforge.common.errors import ConfigError
from caseforge.composition import build_container
from caseforge.tools.models import ToolCall, ToolContext


def test_policy_tool_searches_configured_corpus(config_copy) -> None:
    context = ToolContext(
        run_id="run-0001",
        tenant_id="tenant-demo",
        case_id="case-0001",
        as_of=datetime(2026, 1, 6, tzinfo=UTC),
        agent="policy",
        step=0,
    )
    call = ToolCall(tool="search_policies", arguments={"query": "wrong document type uploaded"})
    with build_container(config_copy, environ={}) as container:
        result = container.tools.invoke(call, context).result
    assert result.ok is True
    assert result.output["passages"][0]["chunk_id"] == "document-requests#wrong-document-received"


def test_missing_corpus_fails_at_startup(config_copy) -> None:
    text = config_copy.read_text(encoding="utf-8")
    config_copy.write_text(
        text.replace("corpus_dir: knowledge/policies", "corpus_dir: knowledge/absent", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="no knowledge documents"):
        build_container(config_copy, environ={})
