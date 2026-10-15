"""Composition root: builds the configured store, checkpointer, environment and case graph."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from caseforge.adapters.simulation import SimulatedEnvironment
from caseforge.common.hashing import sha256_hex
from caseforge.engine.graph import EngineDeps, build_case_graph
from caseforge.events.mapping import EventNormalizer
from caseforge.knowledge.empty import EmptyKnowledgeProvider
from caseforge.memory.empty import EmptyEpisodeProvider
from caseforge.persistence.ports import RecordConflictError
from caseforge.persistence.sqlite import SqliteRecordStore
from caseforge.provenance.manifest import build_run_manifest
from caseforge.settings.loader import LoadedSettings, load_settings
from caseforge.simulation.provider import TemplateSimulationProvider
from caseforge.simulation.world import SimulatedWorld
from caseforge.tools.builtin import read_tools
from caseforge.tools.registry import ToolRegistry

Clock = Callable[[], datetime]


def _system_clock() -> datetime:
    return datetime.now(UTC)


class Container:
    """Wired application objects for one process. Close it to release storage handles."""

    def __init__(self, loaded: LoadedSettings, *, project_root: Path, clock: Clock) -> None:
        settings = loaded.settings
        base = loaded.settings_path.parent
        self.loaded = loaded
        self._project_root = project_root
        self._clock = clock
        self.store = SqliteRecordStore(base / settings.storage.records_path)
        try:
            self.tools = ToolRegistry(
                read_tools(self.store, EmptyKnowledgeProvider(), EmptyEpisodeProvider()),
                settings.tools,
                clock=clock,
            )
            checkpoints = (base / settings.storage.checkpoints_path).resolve()
            checkpoints.parent.mkdir(parents=True, exist_ok=True)
            self._checkpoint_conn = sqlite3.connect(checkpoints, check_same_thread=False)
        except BaseException:
            self.store.close()
            raise
        self.environment = SimulatedEnvironment()
        self.provider = TemplateSimulationProvider(loaded.families)
        deps = EngineDeps(
            store=self.store,
            normalizers={
                spec.source_system: EventNormalizer(spec, loaded.vocabulary)
                for spec in loaded.mappings
            },
            triage=settings.triage,
            case_source=self.environment,
            executor=self.environment,
            outcomes=self.environment,
        )
        self.graph = build_case_graph(deps).compile(checkpointer=SqliteSaver(self._checkpoint_conn))

    def __enter__(self) -> Container:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._checkpoint_conn.close()
        self.store.close()

    def open_simulated_case(self, family_id: str, seed: int) -> SimulatedWorld:
        """Create and register a simulated case.

        Returns the world handle so evaluation code can read its ground truth; the
        engine only ever sees the environment's ports.
        """
        settings = self.loaded.settings
        world = self.provider.create(
            family_id,
            seed,
            tenant_id=settings.run.tenant_id,
            start_at=settings.simulation.start_at,
        )
        self.environment.register(world)
        return world

    def default_as_of(self) -> datetime:
        simulation = self.loaded.settings.simulation
        return simulation.start_at + timedelta(minutes=simulation.investigate_after_minutes)

    def run_case(self, run_id: str, case_id: str, as_of: datetime | None = None) -> dict[str, Any]:
        """Run the case graph under thread_id=run_id; re-running a run_id is idempotent."""
        self._record_manifest(run_id)
        moment = (as_of or self.default_as_of()).astimezone(UTC)
        state = {
            "run_id": run_id,
            "tenant_id": self.loaded.settings.run.tenant_id,
            "case_id": case_id,
            "as_of": moment.isoformat(),
            "trace": [],
        }
        return self.graph.invoke(state, {"configurable": {"thread_id": run_id}})

    def _record_manifest(self, run_id: str) -> None:
        existing = self.store.get_manifest(run_id)
        if existing is None:
            lockfile = self._project_root / "uv.lock"
            manifest = build_run_manifest(
                self.loaded,
                run_id=run_id,
                created_at=self._clock(),
                project_root=self._project_root,
                extra_files=(lockfile,) if lockfile.exists() else (),
            )
            self.store.save_manifest(manifest)
            return
        current = sha256_hex(self.loaded.settings.model_dump(mode="json"))
        if existing.effective_config_sha256 != current:
            raise RecordConflictError(f"run {run_id!r} was recorded with a different configuration")


def build_container(
    settings_path: str | Path = "config/caseforge.yaml",
    *,
    environ: dict[str, str] | None = None,
    project_root: str | Path | None = None,
    clock: Clock = _system_clock,
) -> Container:
    loaded = load_settings(settings_path, environ=environ)
    root = Path(project_root) if project_root else loaded.settings_path.parent.parent
    return Container(loaded, project_root=root, clock=clock)
