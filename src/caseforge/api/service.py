"""Operator demo service: runs cases in isolated workspaces with shared governance.

Each run gets its own records, checkpoints and simulated world, so recorded model answers
replay exactly (no other run's episodes reach its prompts). Governance (stop, breakers,
budgets, audit) is shared by all runs, as in production.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from caseforge.composition import Container, build_container
from caseforge.evaluation.benchmark import load_benchmark
from caseforge.reasoning.ports import Reasoner
from caseforge.settings.loader import load_settings

MODES = ("deterministic", "single_agent", "hierarchical")
RUN_ID = re.compile(r"^[a-z0-9-]{1,80}$")
RESOURCES = (
    "reasoner",
    "executor",
    "tool:get_case",
    "tool:get_timeline",
    "tool:search_policies",
    "tool:search_prior_episodes",
)


class RunNotFound(LookupError):
    """No run with this id exists in the demo workspace."""


class DemoService:
    def __init__(
        self,
        settings_path: str | Path,
        *,
        environ: Mapping[str, str] | None = None,
        reasoner_factory: Callable[[str], Reasoner | None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings_path = Path(settings_path).resolve()
        self._environ = dict(environ or {})
        loaded = load_settings(self._settings_path, environ=self._environ)
        self._settings = loaded.settings
        self._families = loaded.families
        self._base = self._settings_path.parent
        self._workspace = self._base / self._settings.api.workspace_dir
        self._reasoner_factory = reasoner_factory
        self._clock = clock
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # catalog

    def demo_cases(self) -> list[dict[str, Any]]:
        s = self._settings
        benchmark = load_benchmark(
            self._base / s.evaluation.benchmark_path,
            families=self._families,
            allowed_actions=s.agents.supervisor.allowed_actions,
            approval_required=s.engine.approval_required,
        )
        return [
            {"key": c.key, "family": c.family, "seed": c.seed}
            for c in benchmark.cases
            if c.condition == "none"
        ]

    # runs

    def start_run(self, *, family: str, seed: int, mode: str) -> dict[str, Any]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}")
        if family not in {f.family_id for f in self._families}:
            raise ValueError(f"unknown family {family!r}")
        run_id = f"{mode.replace('_', '-')}-{family}-{seed:03d}-{secrets.token_hex(3)}"
        with self._lock(run_id), self._container(run_id, mode) as container:
            world = container.open_simulated_case(family, seed)
            meta = {
                "run_id": run_id,
                "mode": mode,
                "family": family,
                "seed": seed,
                "case_id": world.case_id,
                "started_at": self._now().isoformat(),
            }
            self._save_meta(meta)
            container.run_case(run_id, world.case_id)
            return self._view(container, meta)

    def get_run(self, run_id: str) -> dict[str, Any]:
        meta = self._meta(run_id)
        with self._lock(run_id), self._container(run_id, meta["mode"]) as container:
            return self._view(container, meta)

    def approve(self, run_id: str, *, actor: str, note: str | None) -> dict[str, Any]:
        meta = self._meta(run_id)
        with self._lock(run_id), self._container(run_id, meta["mode"]) as container:
            container.approve(run_id, actor=actor, note=note)
            return self._view(container, meta)

    def reject(self, run_id: str, *, actor: str, note: str | None) -> dict[str, Any]:
        meta = self._meta(run_id)
        with self._lock(run_id), self._container(run_id, meta["mode"]) as container:
            container.reject(run_id, actor=actor, note=note)
            return self._view(container, meta)

    def resume(self, run_id: str) -> dict[str, Any]:
        meta = self._meta(run_id)
        with self._lock(run_id), self._container(run_id, meta["mode"]) as container:
            container.resume(run_id)
            return self._view(container, meta)

    # governance (shared by all runs)

    def governance(self) -> dict[str, Any]:
        with self._container("control", "deterministic") as container:
            plane = container.control_plane
            return {
                "emergency_stop": plane.emergency_stop(),
                "breakers": {resource: plane.breaker(resource) for resource in RESOURCES},
                "audit": list(plane.audit_entries())[-50:],
            }

    def engage_stop(self, *, actor: str, reason: str) -> dict[str, Any]:
        with self._container("control", "deterministic") as container:
            container.control_plane.engage_emergency_stop(actor, reason)
        return self.governance()

    def release_stop(self, *, actor: str) -> dict[str, Any]:
        with self._container("control", "deterministic") as container:
            container.control_plane.release_emergency_stop(actor)
        return self.governance()

    # evaluation results (read-only)

    def evaluation(self) -> dict[str, Any]:
        results = self._base / self._settings.evaluation.results_dir
        reports: list[dict[str, Any]] = []
        comparisons: list[dict[str, Any]] = []
        for path in sorted(results.glob("*.json")) if results.is_dir() else []:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "summary" in data and "cases" in data:
                reports.append(
                    {
                        "label": data["label"],
                        "mode": data["mode"],
                        "reasoner": data.get("reasoner", ""),
                        "summary": data["summary"],
                    }
                )
            elif "pairs" in data:
                keys = ("a", "b", "cases", "both", "only_a", "only_b", "neither", "p_value")
                comparisons.append(
                    {
                        "name": path.stem,
                        "excluded_cases": data["dev_cases"],
                        "held_out": {k: v["held_out"] for k, v in data["architectures"].items()},
                        "pairs": [{k: pair[k] for k in keys} for pair in data["pairs"]],
                    }
                )
        return {"reports": reports, "comparisons": comparisons}

    # internals

    def _now(self) -> datetime:
        return self._clock() if self._clock else datetime.now(UTC)

    def _lock(self, run_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.Lock())

    def _meta_path(self, run_id: str) -> Path:
        return self._workspace / run_id / "meta.json"

    def _save_meta(self, meta: Mapping[str, Any]) -> None:
        path = self._meta_path(meta["run_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=2), encoding="utf-8", newline="\n")

    def _meta(self, run_id: str) -> dict[str, Any]:
        if not RUN_ID.match(run_id) or not self._meta_path(run_id).is_file():
            raise RunNotFound(run_id)
        return json.loads(self._meta_path(run_id).read_text(encoding="utf-8"))

    @contextmanager
    def _container(self, workspace: str, mode: str) -> Iterator[Container]:
        case_dir = f"{self._settings.api.workspace_dir}/{workspace}"
        environ = {
            **self._environ,
            "CASEFORGE__STORAGE__RECORDS_PATH": f"{case_dir}/records.db",
            "CASEFORGE__STORAGE__CHECKPOINTS_PATH": f"{case_dir}/checkpoints.db",
            "CASEFORGE__SIMULATION__STORE_PATH": f"{case_dir}/simulation.db",
            "CASEFORGE__PROVENANCE__SNAPSHOT_DIR": f"{case_dir}/snapshots",
            "CASEFORGE__ENGINE__MODE": mode,
        }
        kwargs: dict[str, Any] = {"environ": environ}
        if self._clock is not None:
            kwargs["clock"] = self._clock
        if self._reasoner_factory is not None:
            reasoner = self._reasoner_factory(mode)
            if reasoner is not None:
                kwargs["reasoner"] = reasoner
        elif mode != "deterministic":
            cassette = self._settings.api.demo_cassettes.get(mode)
            if cassette is None:
                raise ValueError(f"no recorded answers configured for mode {mode!r}")
            environ.update(
                {
                    "CASEFORGE__REASONING__PROVIDER": "anthropic",
                    "CASEFORGE__REASONING__SOURCE": "replay",
                    "CASEFORGE__REASONING__MODEL": self._settings.api.demo_model,
                    "CASEFORGE__REASONING__CASSETTE_PATH": str(cassette),
                }
            )
        with build_container(self._settings_path, **kwargs) as container:
            yield container

    def _view(self, container: Container, meta: Mapping[str, Any]) -> dict[str, Any]:
        run_id = meta["run_id"]
        state = dict(container.graph.get_state({"configurable": {"thread_id": run_id}}).values)
        pending = container.pending_approval(run_id)
        if pending is not None:
            status = "awaiting_approval"
        elif state.get("outcome"):
            status = "completed"
        elif container.control_plane.emergency_stop() is not None:
            status = "halted"
        else:
            status = "interrupted"
        record = container.store.get_decision_outcome(run_id)
        return {
            **meta,
            "status": status,
            "route": (state.get("triage") or {}).get("route"),
            "decision": state.get("decision"),
            "action": state.get("action"),
            "outcome": state.get("outcome"),
            "pending_approval": pending,
            "decision_outcome": record,
            "usage": container.run_usage(run_id),
            "trace": state.get("trace") or [],
        }
