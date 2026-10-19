"""Composition root: builds the configured store, checkpointer, environment and case graph."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from caseforge.adapters.simulation import SimulatedEnvironment
from caseforge.adapters.simulation_log import SqliteSimulationLog
from caseforge.agents.single import SingleAgent
from caseforge.agents.supervisor import Supervisor
from caseforge.agents.workers import Worker, evidence_worker, policy_worker
from caseforge.common.errors import ConfigError
from caseforge.common.hashing import sha256_hex
from caseforge.engine.graph import EngineDeps, build_case_graph, no_fault
from caseforge.events.mapping import EventNormalizer
from caseforge.governance.budgets import LlmBudget
from caseforge.governance.control_plane import ControlPlane
from caseforge.governance.guards import (
    EmergencyStopEngaged,
    GovernedExecutor,
    GovernedReasoner,
    GovernedTools,
)
from caseforge.governance.models import RunUsage
from caseforge.governance.permissions import APPROVE_ACTION, RECONCILE_ACTION
from caseforge.governance.store import GovernanceStore
from caseforge.knowledge.bm25 import Bm25KnowledgeProvider
from caseforge.memory.episodes import describe_episode
from caseforge.memory.store_provider import StoreEpisodeProvider
from caseforge.persistence.ports import RecordConflictError
from caseforge.persistence.records import ActionLedgerEntry, DecisionOutcomeRecord, LedgerStatus
from caseforge.persistence.sqlite import SqliteRecordStore
from caseforge.provenance.manifest import build_run_manifest
from caseforge.reasoning.claude import ClaudeReasoner, load_api_key
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.models import ModelSpec
from caseforge.reasoning.ports import Reasoner
from caseforge.reasoning.replay import Cassette, RecordingReasoner, ReplayReasoner
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
    """fake without an injected script: every call fails gracefully (no hidden model).

    anthropic: live calls are always recorded to the cassette; replay reads it at no cost.
    """
    reasoning = loaded.settings.reasoning
    if reasoning.provider == "replay" and reasoning.cassette_path is not None:
        return ReplayReasoner(Cassette(base / reasoning.cassette_path))
    if reasoning.provider == "anthropic":
        if reasoning.cassette_path is None:
            raise ConfigError("the anthropic provider requires reasoning.cassette_path")
        cassette = Cassette(base / reasoning.cassette_path)
        if reasoning.source == "replay":
            return ReplayReasoner(cassette)
        import anthropic

        client = anthropic.Anthropic(
            api_key=load_api_key(base / reasoning.api_key_file, os.environ),
            timeout=reasoning.timeout_seconds,
            max_retries=2,
        )
        return RecordingReasoner(ClaudeReasoner(client), cassette)
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
        self.control_plane = ControlPlane(
            self._governance_store,
            settings.governance,
            clock=clock,
            pricing=settings.reasoning.price_table.get(
                settings.reasoning.model, settings.reasoning.pricing
            ),
        )
        self._governed_tools = GovernedTools(
            self.tools, self._guard, budget=self.control_plane, breakers=self.control_plane
        )
        self.reasoner = GovernedReasoner(
            reasoner or _default_reasoner(loaded, base), self._guard, breakers=self.control_plane
        )
        retries = settings.governance.retries
        self._governed_executor = GovernedExecutor(
            self.environment,
            self.control_plane,
            max_attempts=retries.max_attempts,
            backoff_seconds=retries.backoff_seconds,
            sleep=time.sleep,
        )
        reasoning, provenance, agents = settings.reasoning, settings.provenance, settings.agents
        self.caller = StructuredCaller(
            self.reasoner,
            loaded.prompts,
            ModelSpec(provider=reasoning.provider, model=reasoning.model, params=reasoning.params),
            clock=clock,
            snapshots=SnapshotWriter(base / provenance.snapshot_dir, provenance.snapshot_mode),
            budget=LlmBudget(self.control_plane),
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
        single_agent = SingleAgent(
            caller=self.caller,
            tools=self._governed_tools,
            template_version=settings.agents.single.prompt_version,
            max_steps=settings.agents.single.max_steps,
            allowed_actions=settings.agents.supervisor.allowed_actions,
        )
        deps = EngineDeps(
            store=self.store,
            normalizers={
                spec.source_system: EventNormalizer(spec, loaded.vocabulary)
                for spec in loaded.mappings
            },
            triage=settings.triage,
            case_source=self.environment,
            executor=self._governed_executor,
            outcomes=self.environment,
            tools=self._governed_tools,
            supervisor=self.supervisor,
            workers=self.workers,
            single_agent=single_agent,
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
            "action": None,
            "outcome": None,
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

    def reconcile_action(
        self,
        idempotency_key: str,
        *,
        actor: str,
        outcome: Literal["succeeded", "failed"],
        note: str,
    ) -> ActionLedgerEntry:
        """Resolve an action whose external result is unknown. Admin-only and audited."""
        target = f"action:{idempotency_key}"
        detail = {"outcome": outcome, "note": note}
        self.control_plane.require(actor, RECONCILE_ACTION, target=target, detail=detail)
        entry = self.store.get_action(idempotency_key)
        if entry is None:
            raise ValueError(f"unknown action {idempotency_key!r}")
        if entry.status != LedgerStatus.UNKNOWN:
            raise ValueError(
                f"action {idempotency_key!r} is {entry.status}; "
                "only unknown actions can be reconciled"
            )
        updated = self.store.transition_action(
            idempotency_key,
            LedgerStatus.SUCCEEDED if outcome == "succeeded" else LedgerStatus.FAILED,
            at=self._clock(),
            result={"reconciled_by": actor, "note": note},
            error=None if outcome == "succeeded" else note,
        )
        self.control_plane.record(actor, "action.reconciled", target=target, detail=detail)
        return updated

    def refresh_outcomes(self, as_of: datetime) -> int:
        """Re-observe pending outcomes of executed actions; update records and episodes."""
        updated = 0
        for record in self.store.decision_outcomes(outcome_status="pending"):
            if record.ledger_status != LedgerStatus.SUCCEEDED:
                continue
            try:
                observation = self.environment.observe(
                    tenant_id=record.tenant_id,
                    case_id=record.case_id,
                    action_id=f"{record.run_id}:{record.action_type}",
                    as_of=as_of,
                )
            except Exception:  # an unreachable outcome source leaves the record pending
                continue
            status = str(observation.status)
            if status == record.outcome_status:
                continue
            self.store.save_decision_outcome(
                record.model_copy(
                    update={
                        "outcome_status": status,
                        "horizon_end": observation.horizon_end,
                        "outcome_observed_at": observation.observed_at,
                        "updated_at": self._clock(),
                    }
                )
            )
            self._refresh_episode(record.tenant_id, record.run_id, status)
            updated += 1
        return updated

    def _record_outcome(self, final: dict[str, Any]) -> None:
        action, outcome = final.get("action"), final.get("outcome")
        if not action or not outcome:
            return  # paused for approval or otherwise incomplete
        run_id = final["run_id"]
        decision = self.store.get_decision(run_id)
        synthesis_output = (final.get("synthesis") or {}).get("output") or {}
        if action["source"] in {"supervisor", "single_agent"}:
            candidates = tuple(synthesis_output.get("candidate_actions") or ())
        else:
            candidates = (action["action_type"],)
        manifest = self.store.get_manifest(run_id)
        usage = self.control_plane.run_usage(run_id)
        self.store.save_decision_outcome(
            DecisionOutcomeRecord(
                run_id=run_id,
                tenant_id=final["tenant_id"],
                case_id=final["case_id"],
                decision_source=action["source"],
                action_type=action["action_type"],
                candidate_actions=candidates,
                evidence_refs=decision.evidence_refs if decision else (),
                approval=(final.get("approval") or {}).get("decision"),
                ledger_status=action["ledger_status"],
                outcome_status=outcome["status"],
                acted_at=action["acted_at"],
                horizon_end=outcome.get("horizon_end"),
                outcome_observed_at=outcome.get("observed_at"),
                config_sha256=manifest.effective_config_sha256 if manifest else None,
                llm_calls=usage.llm_calls,
                total_tokens=usage.total_tokens,
                cost_usd=usage.cost_usd,
                tool_calls=usage.tool_calls,
                updated_at=self._clock(),
            )
        )

    def _refresh_episode(self, tenant_id: str, run_id: str, outcome_status: str) -> None:
        episode = next(
            (e for e in self.store.episodes_for_tenant(tenant_id) if e.run_id == run_id), None
        )
        if episode is None:
            return
        decision = self.store.get_decision(run_id)
        summary = describe_episode(
            event_types=episode.event_types,
            source=episode.decision_source,
            action_type=episode.action_type,
            reason=decision.reason if decision else None,
            ledger_status=episode.ledger_status,
            outcome_status=outcome_status,
        )
        self.store.save_episode(
            episode.model_copy(update={"outcome_status": outcome_status, "summary": summary})
        )

    def run_usage(self, run_id: str) -> RunUsage:
        """Spend counted for a run (model calls, tokens, estimated cost, tool calls)."""
        return self.control_plane.run_usage(run_id)

    def _guard(self, boundary: str) -> None:
        self.control_plane.check(boundary)

    def _invoke(self, payload: Any, run_id: str) -> dict[str, Any]:
        """Run the graph and record the decision outcome of a completed run.

        An emergency stop returns the saved state marked as halted.
        """
        config = {"configurable": {"thread_id": run_id}}
        try:
            final = self.graph.invoke(payload, config)
        except EmergencyStopEngaged as stop:
            self.control_plane.record(
                "system", "run.halted", target=run_id, detail={"reason": str(stop)}
            )
            state = dict(self.graph.get_state(config).values)
            return {**state, "halted": True, "halt_reason": str(stop)}
        self._record_outcome(final)
        return final

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
