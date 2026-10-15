"""Tests for seeded world generation, observation noise and the observable/truth split."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from caseforge.events.mapping import EventNormalizer, load_mapping
from caseforge.simulation.provider import TemplateSimulationProvider
from caseforge.simulation.spec import ScenarioFamily, load_families

FAMILIES_DIR = Path(__file__).resolve().parents[2] / "config" / "simulation" / "families"
START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
END = START + timedelta(days=30)
S1, S2 = "routine-stalled-task", "missing-document"


@pytest.fixture(scope="module")
def provider() -> TemplateSimulationProvider:
    return TemplateSimulationProvider(load_families(FAMILIES_DIR))


def _create(provider, family_id: str, seed: int):
    return provider.create(family_id, seed, tenant_id="tenant-demo", start_at=START)


def test_same_seed_same_world(provider) -> None:
    first, second = _create(provider, S1, 7), _create(provider, S1, 7)
    assert first.observable_view(END) == second.observable_view(END)
    assert first.ground_truth() == second.ground_truth()


def test_seeds_produce_variation(provider) -> None:
    signatures = {
        tuple(e.occurred_at for e in _create(provider, S1, seed).observable_view(END).events)
        for seed in range(20)
    }
    assert len(signatures) > 1


def test_world_independent_of_creation_order(provider) -> None:
    _create(provider, S2, 3)
    later = _create(provider, S2, 5)
    fresh = TemplateSimulationProvider(load_families(FAMILIES_DIR))
    assert _create(fresh, S2, 5).observable_view(END) == later.observable_view(END)


def test_identifiers_are_deterministic(provider) -> None:
    view = _create(provider, S1, 7).observable_view(END)
    assert view.case_id == "rst-0007"
    assert all(e.source_event_id.startswith("rst-0007-") for e in view.events)
    assert {e.entity_id for e in view.events} >= {"rst-0007", "rst-0007-t1"}


def test_blocker_frequencies_follow_weights(provider) -> None:
    blockers = [_create(provider, S1, seed).ground_truth().blocker for seed in range(400)]
    share = blockers.count("owner_overloaded") / len(blockers)
    assert 0.18 <= share <= 0.32


def test_blocker_cue_only_for_its_blocker(provider) -> None:
    seen_cue = False
    for seed in range(100):
        truth = _create(provider, S1, seed).ground_truth()
        has_cue = f"{truth.case_id}-task_side_late" in truth.occurred_event_ids
        if truth.blocker == "reminder_needed":
            assert not has_cue
        seen_cue = seen_cue or has_cue
    assert seen_cue


def test_shared_variable_keeps_owner_consistent(provider) -> None:
    for seed in range(20):
        owners = {
            e.attributes["owner"]
            for e in _create(provider, S1, seed).observable_view(END).events
            if e.source_type == "tsk.req"
        }
        assert len(owners) == 1


def test_events_until_filters_by_recorded_time(provider) -> None:
    view = _create(provider, S1, 1).observable_view(END)
    as_of = START + timedelta(hours=2)
    early = view.events_until(as_of)
    assert early
    assert all(e.recorded_at <= as_of for e in early)
    assert all(e.source_type != "tsk.late" for e in early)
    assert view.events_until(START + timedelta(days=30)) == view.events


def test_recording_delay_within_bounds(provider) -> None:
    for seed in range(50):
        for event in _create(provider, S2, seed).observable_view(END).events:
            assert timedelta(0) <= event.recorded_at - event.occurred_at <= timedelta(minutes=10)


@pytest.mark.parametrize(("drop_probability", "observed"), [(1.0, False), (0.0, True)])
def test_dropped_events_hidden_but_recorded_in_truth(drop_probability, observed) -> None:
    family = ScenarioFamily.model_validate(
        {
            "family_id": "test-family",
            "spec_version": 1,
            "case_prefix": "tf",
            "description": "Test family.",
            "source_system": "sim",
            "blockers": {"only": {"description": "Only.", "weight": 1, "effective_actions": ["x"]}},
            "templates": [
                {
                    "id": "open",
                    "source_type": "case.open",
                    "actor": "req",
                    "offset_minutes": [0, 0],
                    "drop_probability": drop_probability,
                }
            ],
        }
    )
    world = TemplateSimulationProvider([family]).create(
        "test-family", 1, tenant_id="tenant-demo", start_at=START
    )
    event_id = "tf-0001-open"
    visible_ids = {e.source_event_id for e in world.observable_view(END).events}
    assert (event_id in visible_ids) is observed
    assert event_id in world.ground_truth().occurred_event_ids
    assert (event_id in world.ground_truth().dropped_event_ids) is not observed


def test_unknown_family_rejected(provider) -> None:
    with pytest.raises(ValueError, match="unknown scenario family"):
        _create(provider, "ghost", 1)


def test_observable_view_exposes_no_ground_truth(provider) -> None:
    view = _create(provider, S1, 1).observable_view(END)
    for name in ("blocker", "effective_actions", "ground_truth", "dropped_event_ids", "variables"):
        assert not hasattr(view, name)


@pytest.mark.parametrize("family_id", [S1, S2])
def test_all_observed_events_normalize(
    provider, family_id, canonical_vocabulary, sim_mapping_path
) -> None:
    spec = load_mapping(sim_mapping_path, canonical_vocabulary)
    normalizer = EventNormalizer(spec, canonical_vocabulary)
    for seed in range(30):
        events = _create(provider, family_id, seed).observable_view(END).events
        result = normalizer.normalize_batch(events)
        assert result.rejected == (), result.rejected
        assert result.accepted


def test_view_hides_events_not_yet_recorded(provider) -> None:
    world = _create(provider, S1, 1)
    as_of = START + timedelta(hours=2)
    view = world.observable_view(as_of)
    assert view.as_of == as_of
    assert all(e.recorded_at <= as_of for e in view.events)
    assert len(view.events) < len(world.observable_view(END).events)
