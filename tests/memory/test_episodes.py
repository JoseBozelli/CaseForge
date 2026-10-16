"""Episode memory: shared BM25 index, tenant-scoped search, and end-to-end recording."""

from datetime import UTC, datetime

from caseforge.composition import build_container
from caseforge.knowledge.bm25 import Bm25Index
from caseforge.memory.store_provider import StoreEpisodeProvider
from caseforge.persistence.memory import InMemoryRecordStore
from caseforge.persistence.records import EpisodeRecord
from caseforge.tools.models import ToolCall, ToolContext

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1 = "routine-stalled-task"


def _episode(run_id: str, case_id: str, summary: str, tenant_id: str = "tenant-a"):
    return EpisodeRecord(
        run_id=run_id,
        tenant_id=tenant_id,
        case_id=case_id,
        event_types=("task.delayed",),
        decision_source="triage",
        action_type="send_reminder",
        ledger_status="succeeded",
        outcome_status="pending",
        summary=summary,
        recorded_at=FIXED,
    )


def test_index_ranks_by_score_and_breaks_ties_by_key() -> None:
    index = Bm25Index(
        [("b", "alpha beta"), ("a", "alpha beta"), ("c", "gamma")], k1=1.5, b=0.75, min_score=0
    )
    assert [position for _, position in index.search("alpha", 3)] == [1, 0]


def test_index_abstains_below_min_score() -> None:
    index = Bm25Index([("a", "alpha beta")], k1=1.5, b=0.75, min_score=100)
    assert index.search("alpha", 3) == []


def test_provider_excludes_current_case_and_other_tenants() -> None:
    store = InMemoryRecordStore()
    store.save_episode(_episode("run-1", "case-1", "Overdue task reminder sent."))
    store.save_episode(_episode("run-2", "case-2", "Overdue task reminder sent."))
    store.save_episode(_episode("run-3", "case-3", "Overdue task reminder sent.", "tenant-b"))
    provider = StoreEpisodeProvider(store, k1=1.5, b=0.75, min_score=0.1)
    found = provider.search("tenant-a", "overdue task reminder", 5, exclude_case_id="case-2")
    assert [e.case_id for e in found] == ["case-1"]


def test_provider_abstains_on_unrelated_query() -> None:
    store = InMemoryRecordStore()
    store.save_episode(_episode("run-1", "case-1", "Overdue task reminder sent."))
    provider = StoreEpisodeProvider(store, k1=1.5, b=0.75, min_score=0.1)
    assert provider.search("tenant-a", "quarterly marketing budget", 5) == ()


def test_completed_runs_become_episodes(config_copy) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED) as container:
        world = container.open_simulated_case(S1, 7)
        container.run_case("run-0001", world.case_id)
        episodes = container.store.episodes_for_tenant("tenant-demo")
    assert [(e.case_id, e.action_type, e.ledger_status) for e in episodes] == [
        (world.case_id, "send_reminder", "succeeded")
    ]
    assert "task.delayed" in episodes[0].summary


def test_prior_episode_search_finds_other_cases_only(config_copy) -> None:
    with build_container(config_copy, environ={}, clock=lambda: FIXED) as container:
        first = container.open_simulated_case(S1, 7)
        second = container.open_simulated_case(S1, 8)
        container.run_case("run-0001", first.case_id)
        container.run_case("run-0002", second.case_id)
        result = container.tools.invoke(
            ToolCall(tool="search_prior_episodes", arguments={"query": "task delayed reminder"}),
            ToolContext(
                run_id="run-0003",
                tenant_id="tenant-demo",
                case_id=second.case_id,
                as_of=container.default_as_of(),
                agent="evidence",
                step=0,
            ),
        ).result
    assert result.ok is True
    assert [e["case_id"] for e in result.output["episodes"]] == [first.case_id]
