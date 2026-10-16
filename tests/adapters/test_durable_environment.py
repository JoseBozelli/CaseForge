"""Durable simulated outside world: deterministic rebuild and cross-process recovery."""

import sqlite3
from datetime import UTC, datetime

import pytest

from caseforge.adapters.simulation_log import SimulationLogError, SqliteSimulationLog
from caseforge.composition import build_container
from caseforge.persistence.records import LedgerStatus

FIXED = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
S1 = "routine-stalled-task"
KEY = "run-0001:send_reminder"


class SimulatedCrash(RuntimeError):
    pass


def _container(config_copy, **kwargs):
    return build_container(
        config_copy, environ=kwargs.pop("environ", {}), clock=lambda: FIXED, **kwargs
    )


def test_restored_world_keeps_applied_actions(config_copy) -> None:
    with _container(config_copy) as first:
        first.run_case("run-0001", first.open_simulated_case(S1, 7).case_id)
    with _container(config_copy) as second:
        world = second.open_simulated_case(S1, 7)
    assert [a.action_id for a in world.ground_truth().actions] == [KEY]


def test_restored_world_is_identical_to_the_original(config_copy) -> None:
    with _container(config_copy) as first:
        original = first.open_simulated_case(S1, 7)
        first.run_case("run-0001", original.case_id)
        as_of = first.default_as_of()
        truth, view = original.ground_truth(), original.observable_view(as_of)
    with _container(config_copy) as second:
        restored = second.open_simulated_case(S1, 7)
        assert restored.ground_truth() == truth
        assert restored.observable_view(as_of) == view


def test_reopening_a_case_with_different_parameters_is_refused(config_copy) -> None:
    with _container(config_copy) as first:
        first.open_simulated_case(S1, 7)
    moved = {"CASEFORGE__SIMULATION__START_AT": "2026-03-01T09:00:00Z"}
    with (
        _container(config_copy, environ=moved) as second,
        pytest.raises(SimulationLogError, match="different parameters"),
    ):
        second.open_simulated_case(S1, 7)


def test_repeated_execution_is_logged_once(config_copy) -> None:
    with _container(config_copy) as container:
        world = container.open_simulated_case(S1, 7)
        at = container.default_as_of()
        for _ in range(2):
            container.environment.execute(
                tenant_id="tenant-demo",
                case_id=world.case_id,
                action_id=KEY,
                action_type="send_reminder",
                at=at,
            )
        logged = container._simulation_log.actions("tenant-demo", world.case_id)
    assert [a.action_id for a in logged] == [KEY]


def test_unknown_simulation_schema_is_refused(tmp_path) -> None:
    path = tmp_path / "simulation.db"
    SqliteSimulationLog(path).close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_info SET value = 'simulation.v0' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    with pytest.raises(SimulationLogError, match="unsupported simulation schema"):
        SqliteSimulationLog(path)


def test_crash_after_execution_recovers_in_a_new_container(config_copy) -> None:
    def crash(point: str) -> None:
        if point == "act.after_execute":
            raise SimulatedCrash(point)

    with _container(config_copy, fault_injector=crash) as first:
        world = first.open_simulated_case(S1, 7)
        with pytest.raises(SimulatedCrash):
            first.run_case("run-0001", world.case_id)
        assert first.store.get_action(KEY).status == LedgerStatus.DISPATCHED

    with _container(config_copy) as second:
        final = second.resume("run-0001")
        restored = second.open_simulated_case(S1, 7)
        entry = second.store.get_action(KEY)
    assert entry.status == LedgerStatus.SUCCEEDED
    assert final["action"]["applied"] is False
    assert [a.action_id for a in restored.ground_truth().actions] == [KEY]
