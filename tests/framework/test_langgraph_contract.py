"""Contract tests for LangGraph behaviors the CaseForge architecture depends on.

These tests exercise the installed framework, not CaseForge code. They fail first if
an upgrade changes interrupt, checkpoint, resume or routing semantics.
"""

from __future__ import annotations

import operator
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

QUESTION = {"question": "Approve the proposed action?"}


class SpikeState(TypedDict, total=False):
    steps: Annotated[list[str], operator.add]
    decision: str


def _builder(calls: list[str]) -> StateGraph:
    def prepare(state: SpikeState) -> SpikeState:
        calls.append("prepare")
        return {"steps": ["prepare"]}

    def approval(state: SpikeState) -> SpikeState:
        calls.append("approval_entered")
        decision = interrupt(QUESTION)
        return {"steps": ["approval"], "decision": decision}

    def execute(state: SpikeState) -> SpikeState:
        calls.append("execute")
        return {"steps": ["execute"]}

    def route(state: SpikeState) -> str:
        return "execute" if state.get("decision") == "approved" else "end"

    builder = StateGraph(SpikeState)
    builder.add_node("prepare", prepare)
    builder.add_node("approval", approval)
    builder.add_node("execute", execute)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "approval")
    builder.add_conditional_edges("approval", route, {"execute": "execute", "end": END})
    builder.add_edge("execute", END)
    return builder


@contextmanager
def _graph(path: Path, calls: list[str]) -> Iterator:
    """Compile the graph on a fresh connection, as a restarted process would."""
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        yield _builder(calls).compile(checkpointer=SqliteSaver(conn))
    finally:
        conn.close()


def _config(thread_id: str = "run-0001") -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _start(path: Path, calls: list[str]) -> None:
    with _graph(path, calls) as graph:
        graph.invoke({"steps": []}, _config())


def test_interrupt_pauses_before_approval_completes(tmp_path: Path) -> None:
    calls: list[str] = []
    with _graph(tmp_path / "cp.db", calls) as graph:
        graph.invoke({"steps": []}, _config())
        state = graph.get_state(_config())
    assert state.next == ("approval",)
    assert state.values["steps"] == ["prepare"]
    assert state.tasks[0].interrupts[0].value == QUESTION
    assert "execute" not in calls


def test_resume_after_restart_completes(tmp_path: Path) -> None:
    path = tmp_path / "cp.db"
    _start(path, [])
    with _graph(path, []) as restarted:
        result = restarted.invoke(Command(resume="approved"), _config())
        final = restarted.get_state(_config())
    assert result["steps"] == ["prepare", "approval", "execute"]
    assert result["decision"] == "approved"
    assert final.next == ()


def test_interrupted_node_reruns_from_start_but_completed_nodes_do_not(tmp_path: Path) -> None:
    path = tmp_path / "cp.db"
    calls: list[str] = []
    _start(path, calls)
    with _graph(path, calls) as restarted:
        restarted.invoke(Command(resume="approved"), _config())
    assert calls == ["prepare", "approval_entered", "approval_entered", "execute"]


def test_rejection_routes_around_execution(tmp_path: Path) -> None:
    path = tmp_path / "cp.db"
    calls: list[str] = []
    _start(path, calls)
    with _graph(path, calls) as restarted:
        result = restarted.invoke(Command(resume="rejected"), _config())
    assert result["decision"] == "rejected"
    assert result["steps"] == ["prepare", "approval"]
    assert "execute" not in calls


def test_threads_are_isolated(tmp_path: Path) -> None:
    path = tmp_path / "cp.db"
    _start(path, [])
    with _graph(path, []) as graph:
        other = graph.get_state(_config("run-0002"))
        paused = graph.get_state(_config("run-0001"))
    assert other.next == ()
    assert other.values == {}
    assert paused.next == ("approval",)
