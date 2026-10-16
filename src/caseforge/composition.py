"""Composition root: builds the configured store, checkpointer, environment and case graph."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from caseforge.adapters.simulation import SimulatedEnvironment
from caseforge.adapters.simulation_log import SqliteSimulationLog
from caseforge.agents.supervisor import Supervisor
from caseforge.agents.workers import Worker, evidence_worker, policy_worker
from caseforge.common.hashing import sha256_hex
from caseforge.engine.graph import EngineDeps, build_case_graph, no_fault
from caseforge.events.mapping import EventNormalizer
from caseforge.governance.control_plane import ControlPlane
from caseforge.governance.guards import EmergencyStopEngaged, GovernedReasoner, GovernedTools
from caseforge.governance.permissions import APPROVE_ACTION
from caseforge.governance.store import GovernanceStore
from caseforge.knowledge.bm25 import Bm25KnowledgeProvider
from caseforge.memory.store_provider import StoreEpisodeProvider
from caseforge.persistence.ports import RecordConflictError
from caseforge.persistence.sqlite import SqliteRecordStore
from caseforge.provenance.manifest import build_run_manifest
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.models import ModelSpec
from caseforge.reasoning.ports import Reasoner
from caseforge.reasoning.replay import Cassette, ReplayReasoner
from caseforge.reasoning.structured import SnapshotWriter, StructuredCaller
from caseforge.settings.loader import LoadedSettings, load_settings
from caseforge.simulation.provider import TemplateSimulationProvider
from caseforge.simulation.world import SimulatedWorld
from caseforge.tools.builtin import read_tools
from caseforge.tools.registry import ToolRegistry

Clock = Callable[[], datetime]


def _system_clock() -> datetime:
    return datetime.now(UTC)


def _default_reasoner(loaded: LoadedSettings, base: Path) -> Reasoner:
    """fake without an injected script: every call fails gracefully (no hidden model)."""
    reasoning = loaded.settings.reasoning
    if reasoning.provider == "replay" and reasoning.cassette_path is not None:
        return ReplayReasoner(Cassette(base / reasoning.cassette_path))
    return FakeReasoner({})


class Container:
    """Wired application objects for one process. Close it to release storage handles."""

    def __init__(
        self,
        loaded: LoadedSettings,
        *,
        project_root: Path,
        clock: Clock,
        reasoner: Reasoner | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> None:
        settings = loaded.settings
        base = loaded.settings_path.parent
        self.loaded = loaded
        self._project_root = project_root
        self._clock = clock
        self.store = SqliteRecordStore(base / settings.storage.records_path)
        try:
            knowledge = Bm25KnowledgeProvider(
                loaded.corpus.chunks,
                k1=settings.knowledge.k1,
                b=settings.knowledge.b,
                min_score=settings.knowledge.min_score,
            )
            self.tools = ToolRegistry(
                read_tools(
                    self.store,
                    knowledge,
                    StoreEpisodeProvider(
                        self.store,
                        k1=settings.memory.k1,
                        b=settings.memory.b,
                        min_score=settings.memory.min_score,
                    ),
                ),
                settings.tools,
                clock=clock,
            )
            checkpoints = (base / settings.storage.checkpoints_path).resolve()
            checkpoints.parent.mkdir(parents=True, exist_ok=True)
            self._checkpoint_conn = sqlite3.connect(checkpoints, check_same_thread=False)
        except BaseException:
            self.store.close()
            raise
        self.provider = TemplateSimulationProvider(loaded.families)
        self._simulation_log = SqliteSimulationLog(base / settings.simulation.store_path)
        self.environment = SimulatedEnvironment(self.provider, self._simulation_log)
        self.environment.restore()
        self._governance_store = GovernanceStore(base / settings.governance.store_path)
        self.control_plane = ControlPlane(self._governance_store, settings.governance, clock=clock)
        self._governed_tools = GovernedTools(self.tools, self._guard)
        self.reasoner = GovernedReasoner(reasoner or _default_reasoner(loaded, base), self._guard)
        reasoning, provenance, agents = settings.reasoning, settings.provenance, settings.agents
        self.caller = StructuredCaller(
            self.reasoner,
            loaded.prompts,
            ModelSpec(provider=reasoning.provider, model=reasoning.model, params=reasoning.params),
            clock=clock,
            snapshots=SnapshotWriter(base / provenance.snapshot_dir, provenance.snapshot_mode),
        )
        self.supervisor = Supervisor(
            caller=self.caller,
            plan_version=agents.supervisor.plan_version,
            synthesis_version=agents.supervisor.synthesis_version,
            allowed_actions=agents.supervisor.allowed_actions,
            max_clarification_rounds=agents.supervisor.max_clarification_rounds,
        )
        self.workers: dict[str, Worker] = {
            "evidence": evidence_worker(
                caller=self.caller,
                tools=self._governed_tools,
                template_version=agents.evidence.prompt_version,
                max_steps=agents.evidence.max_steps,
            ),
            "policy": policy_worker(
                caller=self.caller,
                tools=self._governed_tools,
                template_version=agents.policy.prompt_version,
                max_steps=agents.policy.max_steps,
            ),
        }
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
            tools=self._governed_tools,
            supervisor=self.supervisor,
            workers=self.workers,
            mode=settings.engine.mode,
            escalation_action=settings.engine.escalation_action,
            clock=clock,
            fault=fault_injector or no_fault,
            approval_required=settings.engine.approval_required,
            guard=self._guard,
        )
        self.graph = build_case_graph(deps).compile(checkpointer=SqliteSaver(self._checkpoint_conn))

    def __enter__(self) -> Container:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._checkpoint_conn.close()
        self._simulation_log.close()
        self._governance_store.close()
        self.store.close()

    def open_simulated_case(self, family_id: str, seed: int) -> SimulatedWorld:
        """Create and register a simulated case.

        Returns the world handle so evaluation code can read its ground truth; the
        engine only ever sees the environment's ports.
        """
        settings = self.loaded.settings
        return self.environment.open_case(
            family_id,
            seed,
            tenant_id=settings.run.tenant_id,
            start_at=settings.simulation.start_at,
        )

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
            "case_summary": None,
            "plan": None,
            "synthesis": None,
            "synthesis_round": 0,
            "decision": None,
            "approval": None,
            "worker_results": None,
            "llm_calls": None,
            "tool_calls": None,
            "trace": [],
        }
        return self._invoke(state, run_id)

    def pending_approval(self, run_id: str) -> dict[str, Any] | None:
        """The approval request a run is paused on, or None."""
        state = self.graph.get_state({"configurable": {"thread_id": run_id}})
        for task in state.tasks:
            for item in task.interrupts:
                return dict(item.value)
        return None

    def approve(self, run_id: str, *, actor: str, note: str | None = None) -> dict[str, Any]:
        return self._answer_approval(run_id, "approved", actor, note)

    def reject(self, run_id: str, *, actor: str, note: str | None = None) -> dict[str, Any]:
        return self._answer_approval(run_id, "rejected", actor, note)

    def _answer_approval(
        self, run_id: str, decision: str, actor: str, note: str | None
    ) -> dict[str, Any]:
        request = self.pending_approval(run_id)
        if request is None:
            raise ValueError(f"run {run_id!r} is not awaiting approval")
        detail = {"action_type": request["action_type"], "decision": decision}
        self.control_plane.require(actor, APPROVE_ACTION, target=run_id, detail=detail)
        response = {
            "decision": decision,
            "actor": actor,
            "note": note,
            "decided_at": self._clock().astimezone(UTC).isoformat(),
        }
        final = self._invoke(Command(resume=response), run_id)
        if not final.get("halted"):
            self.control_plane.record(actor, f"approval.{decision}", target=run_id, detail=detail)
        return final

    def _guard(self, boundary: str) -> None:
        self.control_plane.check(boundary)

    def _invoke(self, payload: Any, run_id: str) -> dict[str, Any]:
        """Run the graph; an emergency stop returns the saved state marked as halted."""
        config = {"configurable": {"thread_id": run_id}}
        try:
            return self.graph.invoke(payload, config)
        except EmergencyStopEngaged as stop:
            self.control_plane.record(
                "system", "run.halted", target=run_id, detail={"reason": str(stop)}
            )
            state = dict(self.graph.get_state(config).values)
            return {**state, "halted": True, "halt_reason": str(stop)}

    def resume(self, run_id: str) -> dict[str, Any]:
        """Continue an interrupted run from its last checkpoint."""
        return self._invoke(None, run_id)

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
    reasoner: Reasoner | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> Container:
    """Build the application. fault_injector is a test-only seam for crash simulation."""
    loaded = load_settings(settings_path, environ=environ)
    root = Path(project_root) if project_root else loaded.settings_path.parent.parent
    return Container(
        loaded, project_root=root, clock=clock, reasoner=reasoner, fault_injector=fault_injector
    )
