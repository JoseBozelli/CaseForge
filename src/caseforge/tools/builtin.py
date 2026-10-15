"""Read-only investigation tools bound to the context's tenant, case and as_of time."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from caseforge.events.envelope import EventEnvelope
from caseforge.knowledge.ports import KnowledgeProvider, Passage
from caseforge.memory.ports import EpisodeProvider, EpisodeSummary
from caseforge.persistence.ports import RecordStore
from caseforge.tools.models import ToolContext, ToolPolicy
from caseforge.tools.registry import ToolSpec


class _Args(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GetCaseArgs(_Args):
    """No arguments: the case is fixed by the execution context."""


class CaseSummary(_Result):
    case_id: str
    as_of: str
    event_count: int
    event_types: dict[str, int]
    entities: list[str]
    first_recorded_at: str | None
    last_recorded_at: str | None


class GetTimelineArgs(_Args):
    entity_id: str | None = Field(default=None, min_length=1)
    event_types: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=200)


class TimelineEntry(_Result):
    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    actor: str
    occurred_at: str
    recorded_at: str
    attributes: dict[str, JsonValue]


class Timeline(_Result):
    entries: list[TimelineEntry]
    truncated: bool


class SearchArgs(_Args):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=20)


class PolicySearchResult(_Result):
    passages: list[Passage]


class EpisodeSearchResult(_Result):
    episodes: list[EpisodeSummary]


_TIMELINE_FIELDS = tuple(TimelineEntry.model_fields)


def _visible(store: RecordStore, context: ToolContext) -> list[EventEnvelope]:
    events = store.events_for_case(context.tenant_id, context.case_id)
    return [event for event in events if event.recorded_at <= context.as_of]


def read_tools(
    store: RecordStore, knowledge: KnowledgeProvider, episodes: EpisodeProvider
) -> tuple[ToolSpec, ...]:
    """Build the read-only tool set over the given stores and providers."""

    def get_case(args: GetCaseArgs, context: ToolContext, policy: ToolPolicy) -> CaseSummary:
        events = [event.model_dump(mode="json") for event in _visible(store, context)]
        return CaseSummary(
            case_id=context.case_id,
            as_of=context.model_dump(mode="json")["as_of"],
            event_count=len(events),
            event_types=dict(sorted(Counter(e["event_type"] for e in events).items())),
            entities=sorted({e["entity_id"] for e in events}),
            first_recorded_at=events[0]["recorded_at"] if events else None,
            last_recorded_at=events[-1]["recorded_at"] if events else None,
        )

    def get_timeline(args: GetTimelineArgs, context: ToolContext, policy: ToolPolicy) -> Timeline:
        matching = [
            event
            for event in _visible(store, context)
            if (args.entity_id is None or event.entity_id == args.entity_id)
            and (args.event_types is None or event.event_type in args.event_types)
        ]
        limit = min(args.limit, policy.max_results)
        entries = [
            TimelineEntry(**{field: data[field] for field in _TIMELINE_FIELDS})
            for data in (event.model_dump(mode="json") for event in matching[-limit:])
        ]
        return Timeline(entries=entries, truncated=len(matching) > limit)

    def search_policies(
        args: SearchArgs, context: ToolContext, policy: ToolPolicy
    ) -> PolicySearchResult:
        top_k = min(args.top_k, policy.max_results)
        return PolicySearchResult(passages=list(knowledge.search(args.query, top_k)))

    def search_prior_episodes(
        args: SearchArgs, context: ToolContext, policy: ToolPolicy
    ) -> EpisodeSearchResult:
        top_k = min(args.top_k, policy.max_results)
        found = episodes.search(
            context.tenant_id, args.query, top_k, exclude_case_id=context.case_id
        )
        return EpisodeSearchResult(episodes=list(found))

    return (
        ToolSpec(
            "get_case",
            "Summarize the current case: event counts by type, entities and time span.",
            "read",
            GetCaseArgs,
            CaseSummary,
            get_case,
        ),
        ToolSpec(
            "get_timeline",
            "List the most recent case events in time order, optionally filtered.",
            "read",
            GetTimelineArgs,
            Timeline,
            get_timeline,
        ),
        ToolSpec(
            "search_policies",
            "Search procedural documentation for passages relevant to a question.",
            "read",
            SearchArgs,
            PolicySearchResult,
            search_policies,
        ),
        ToolSpec(
            "search_prior_episodes",
            "Search earlier cases for similar situations and their outcomes.",
            "read",
            SearchArgs,
            EpisodeSearchResult,
            search_prior_episodes,
        ),
    )
