"""Tests for the read-only investigation tools."""

from datetime import UTC, datetime, timedelta

import pytest

from caseforge.knowledge.ports import Passage
from caseforge.memory.ports import EpisodeSummary
from caseforge.persistence.memory import InMemoryRecordStore
from caseforge.tools.builtin import read_tools
from caseforge.tools.models import ToolCall, ToolContext, ToolErrorCode, ToolPolicy
from caseforge.tools.registry import ToolRegistry

BASE = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
AS_OF = BASE + timedelta(hours=2)
POLICIES = {
    "get_case": ToolPolicy(allowed_agents={"evidence"}),
    "get_timeline": ToolPolicy(allowed_agents={"evidence"}, max_results=2),
    "search_policies": ToolPolicy(allowed_agents={"evidence"}, max_results=2),
    "search_prior_episodes": ToolPolicy(allowed_agents={"evidence"}, max_results=2),
}
CONTEXT = ToolContext(
    run_id="run-0001",
    tenant_id="tenant-a",
    case_id="case-0001",
    as_of=AS_OF,
    agent="evidence",
    step=0,
)


class StaticKnowledge:
    def __init__(self, passages):
        self.passages = passages

    def search(self, query, top_k):
        return tuple(self.passages[:top_k])


class RecordingEpisodes:
    def __init__(self):
        self.calls = []

    def search(self, tenant_id, query, top_k, exclude_case_id=None):
        self.calls.append((tenant_id, query, top_k, exclude_case_id))
        return ()


def _passage(n: int) -> Passage:
    return Passage(
        doc_id=f"doc-{n}", doc_version=1, chunk_id=f"c{n}", title="T", text="Text.", score=1.0
    )


@pytest.fixture
def store(make_event):
    store = InMemoryRecordStore()
    store.append_events(
        [
            make_event(event_id="e1", recorded_at=BASE + timedelta(minutes=1)),
            make_event(event_id="e2", recorded_at=BASE + timedelta(minutes=30)),
            make_event(event_id="e3", recorded_at=BASE + timedelta(minutes=60), entity_id="t2"),
            make_event(event_id="e4", recorded_at=BASE + timedelta(hours=5)),
            make_event(event_id="x1", case_id="case-0002", correlation_id="case-0002"),
        ]
    )
    return store


@pytest.fixture
def episodes():
    return RecordingEpisodes()


@pytest.fixture
def registry(store, episodes):
    knowledge = StaticKnowledge([_passage(1), _passage(2), _passage(3)])
    return ToolRegistry(read_tools(store, knowledge, episodes), POLICIES, clock=lambda: AS_OF)


def _invoke(registry, tool, arguments=None):
    return registry.invoke(ToolCall(tool=tool, arguments=arguments or {}), CONTEXT).result


def test_get_case_sees_only_this_case_up_to_as_of(registry) -> None:
    output = _invoke(registry, "get_case").output
    assert output["event_count"] == 3
    assert output["event_types"] == {"task.delayed": 3}
    assert output["entities"] == ["t2", "task-0001"]
    assert output["last_recorded_at"].startswith("2026-01-05T10:00")


def test_get_case_rejects_arguments(registry) -> None:
    result = _invoke(registry, "get_case", {"case_id": "case-0002"})
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_timeline_returns_latest_entries_capped_by_policy(registry) -> None:
    output = _invoke(registry, "get_timeline", {"limit": 10}).output
    assert [entry["event_id"] for entry in output["entries"]] == ["e2", "e3"]
    assert output["truncated"] is True


def test_timeline_filters_by_entity(registry) -> None:
    output = _invoke(registry, "get_timeline", {"entity_id": "t2"}).output
    assert [entry["event_id"] for entry in output["entries"]] == ["e3"]
    assert output["truncated"] is False
    assert output["entries"][0]["attributes"] == {"due_at": "2026-01-04T17:00:00Z"}


def test_policy_search_capped_by_policy(registry) -> None:
    output = _invoke(registry, "search_policies", {"query": "late task", "top_k": 5}).output
    assert [p["doc_id"] for p in output["passages"]] == ["doc-1", "doc-2"]


def test_episode_search_excludes_current_case(registry, episodes) -> None:
    result = _invoke(registry, "search_prior_episodes", {"query": "late task"})
    assert result.ok is True
    assert episodes.calls == [("tenant-a", "late task", 2, "case-0001")]


def test_search_requires_a_query(registry) -> None:
    result = _invoke(registry, "search_policies", {"query": ""})
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_unused_episode_summary_model_is_importable() -> None:
    assert "outcome_status" in EpisodeSummary.model_fields
