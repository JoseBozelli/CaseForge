"""Tests for simulated action effects, follow-up events and outcome observation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from caseforge.events.mapping import EventNormalizer, load_mapping
from caseforge.outcomes.models import OutcomeStatus
from caseforge.simulation.provider import TemplateSimulationProvider
from caseforge.simulation.spec import ScenarioFamily, load_families

FAMILIES_DIR = Path(__file__).resolve().parents[2] / "config" / "simulation" / "families"
START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
END = START + timedelta(days=30)
ACT_AT = START + timedelta(hours=25)
S1, S2 = "routine-stalled-task", "missing-document"


@pytest.fixture(scope="module")
def provider() -> TemplateSimulationProvider:
    return TemplateSimulationProvider(load_families(FAMILIES_DIR))


def _world(provider, family_id: str, seed: int):
    return provider.create(family_id, seed, tenant_id="tenant-demo", start_at=START)


def _custom_family(**dynamics_overrides) -> ScenarioFamily:
    dynamics = {
        "horizon_minutes": 600,
        "unobservable_probability": 0.0,
        "resolution_delay_minutes": [30, 30],
        "actions": {"fix": {"only": 1.0}},
    }
    dynamics.update(dynamics_overrides)
    return ScenarioFamily.model_validate(
        {
            "family_id": "test-family",
            "spec_version": 1,
            "case_prefix": "tf",
            "description": "Test family.",
            "source_system": "sim",
            "blockers": {
                "only": {"description": "Only.", "weight": 1, "effective_actions": ["fix"]}
            },
            "templates": [
                {
                    "id": "open",
                    "source_type": "case.open",
                    "actor": "req",
                    "offset_minutes": [0, 0],
                    "attributes": {"cat": "general"},
                }
            ],
            "dynamics": dynamics,
        }
    )


def _custom_world(**dynamics_overrides):
    family = _custom_family(**dynamics_overrides)
    return TemplateSimulationProvider([family]).create(
        "test-family", 1, tenant_id="tenant-demo", start_at=START
    )


def test_resolution_rates_follow_configuration(provider) -> None:
    resolved: dict[str, list[bool]] = {"reminder_needed": [], "owner_overloaded": []}
    for seed in range(300):
        world = _world(provider, S1, seed)
        world.apply_action("act-1", "send_reminder", ACT_AT)
        truth = world.ground_truth()
        resolved[truth.blocker].append(truth.actions[0].resolved)

    def rate(values: list[bool]) -> float:
        return sum(values) / len(values)

    assert 0.77 <= rate(resolved["reminder_needed"]) <= 0.93
    assert 0.03 <= rate(resolved["owner_overloaded"]) <= 0.30


def test_actions_are_deterministic(provider) -> None:
    first, second = _world(provider, S2, 4), _world(provider, S2, 4)
    for world in (first, second):
        world.apply_action("act-1", "request_document", ACT_AT)
    assert first.ground_truth() == second.ground_truth()
    assert first.observable_view(END) == second.observable_view(END)


def test_same_action_id_is_idempotent() -> None:
    world = _custom_world()
    at = START + timedelta(hours=1)
    assert world.apply_action("act-1", "fix", at) is True
    assert world.apply_action("act-1", "fix", at) is False
    truth = world.ground_truth()
    assert len(truth.actions) == 1
    assert len(truth.occurred_event_ids) == len(set(truth.occurred_event_ids))


def test_action_id_reuse_with_different_content_rejected() -> None:
    world = _custom_world()
    world.apply_action("act-1", "fix", START + timedelta(hours=1))
    with pytest.raises(ValueError, match="reused"):
        world.apply_action("act-1", "other", START + timedelta(hours=1))


def test_resolution_emits_follow_up_events(provider) -> None:
    for seed in range(50):
        world = _world(provider, S1, seed)
        world.apply_action("act-1", "reassign_task", ACT_AT)
        action = world.ground_truth().actions[0]
        if action.resolved:
            break
    else:
        pytest.fail("no resolved action found in 50 seeds")
    done = [
        e
        for e in world.observable_view(END).events
        if e.source_event_id.endswith("-task_main_done")
    ]
    assert len(done) == 1
    assert done[0].occurred_at == action.resolution_at
    before = world.observable_view(action.resolution_at - timedelta(minutes=1))
    assert done[0] not in before.events


def test_later_actions_have_no_effect_after_resolution() -> None:
    world = _custom_world()
    world.apply_action("act-1", "fix", START + timedelta(hours=1))
    world.apply_action("act-2", "fix", START + timedelta(hours=2))
    truth = world.ground_truth()
    assert truth.resolved_by == "act-1"
    assert truth.actions[1].already_resolved is True
    assert truth.actions[1].resolved is False


def test_unlisted_action_has_no_effect() -> None:
    world = _custom_world()
    at = START + timedelta(hours=1)
    world.apply_action("act-1", "wave", at)
    action = world.ground_truth().actions[0]
    assert (action.resolve_probability, action.resolved) == (0.0, False)
    outcome = world.outcome_for("act-1", at + timedelta(minutes=600))
    assert outcome.status == OutcomeStatus.FAILURE


def test_successful_outcome_lifecycle() -> None:
    world = _custom_world()
    at = START + timedelta(hours=1)
    world.apply_action("act-1", "fix", at)
    assert world.outcome_for("act-1", at + timedelta(minutes=10)).status == OutcomeStatus.PENDING
    outcome = world.outcome_for("act-1", at + timedelta(minutes=30))
    assert outcome.status == OutcomeStatus.SUCCESS
    assert outcome.observed_at == at + timedelta(minutes=30)
    assert outcome.horizon_end == at + timedelta(minutes=600)


def test_failed_outcome_lifecycle() -> None:
    world = _custom_world(actions={"fix": {"only": 1.0}, "noop": {"only": 0.0}})
    at = START + timedelta(hours=1)
    world.apply_action("act-1", "noop", at)
    assert world.outcome_for("act-1", at + timedelta(minutes=599)).status == OutcomeStatus.PENDING
    outcome = world.outcome_for("act-1", at + timedelta(minutes=600))
    assert outcome.status == OutcomeStatus.FAILURE
    assert outcome.observed_at == outcome.horizon_end


def test_unobservable_outcome() -> None:
    world = _custom_world(unobservable_probability=1.0)
    at = START + timedelta(hours=1)
    world.apply_action("act-1", "fix", at)
    assert world.ground_truth().actions[0].resolved is True
    assert world.outcome_for("act-1", at + timedelta(minutes=30)).status == OutcomeStatus.PENDING
    outcome = world.outcome_for("act-1", at + timedelta(minutes=600))
    assert outcome.status == OutcomeStatus.UNOBSERVABLE


def test_invalid_timing_rejected() -> None:
    world = _custom_world()
    with pytest.raises(ValueError, match="precedes world start"):
        world.apply_action("act-0", "fix", START - timedelta(minutes=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        world.apply_action("act-0", "fix", datetime(2026, 1, 5, 10, 0))
    at = START + timedelta(hours=1)
    world.apply_action("act-1", "fix", at)
    with pytest.raises(ValueError, match="precedes the action"):
        world.outcome_for("act-1", at - timedelta(minutes=1))


def test_unknown_action_outcome_rejected() -> None:
    with pytest.raises(ValueError, match="unknown action"):
        _custom_world().outcome_for("ghost", END)


def test_family_without_dynamics_rejects_actions() -> None:
    family = _custom_family().model_copy(update={"dynamics": None})
    world = TemplateSimulationProvider([family]).create(
        "test-family", 1, tenant_id="tenant-demo", start_at=START
    )
    with pytest.raises(ValueError, match="no dynamics"):
        world.apply_action("act-1", "fix", START + timedelta(hours=1))


@pytest.mark.parametrize("family_id", [S1, S2])
def test_post_action_events_normalize(
    provider, family_id, canonical_vocabulary, sim_mapping_path
) -> None:
    spec = load_mapping(sim_mapping_path, canonical_vocabulary)
    normalizer = EventNormalizer(spec, canonical_vocabulary)
    for seed in range(30):
        world = _world(provider, family_id, seed)
        world.apply_action("act-1", world.ground_truth().effective_actions[0], ACT_AT)
        result = normalizer.normalize_batch(world.observable_view(END).events)
        assert result.rejected == (), result.rejected
