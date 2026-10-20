"""CaseForge operator console. Run: streamlit run src/caseforge/ui/app.py

Uses the same DemoService as the API. Agent decisions replay recorded model answers, so
the console never calls a model or spends money.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import streamlit as st
from fastapi.encoders import jsonable_encoder

from caseforge.api.service import DemoService
from caseforge.composition import PermissionDenied

SETTINGS = os.environ.get("CASEFORGE_SETTINGS", "config/caseforge.yaml")
MODES = ["single_agent", "hierarchical", "deterministic"]


@st.cache_resource
def get_service(settings_path: str) -> DemoService:
    return DemoService(settings_path)


def plain(value: Any) -> Any:
    return jsonable_encoder(value)


def attempt(action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run an operator action; show refusals and invalid requests instead of crashing."""
    try:
        return action(*args, **kwargs)
    except PermissionDenied as exc:
        st.error(f"Not permitted: {exc}")
    except (ValueError, LookupError) as exc:
        st.error(str(exc))
    return None


def action_button(
    label: str,
    key: str,
    action: Callable[..., Any],
    *args: Any,
    primary: bool = False,
    **kwargs: Any,
) -> None:
    """A button that runs an operator action and refreshes the page when the action succeeds."""
    pressed = st.button(label, key=key, type="primary" if primary else "secondary")
    if pressed and attempt(action, *args, **kwargs):
        st.rerun()


def show_run(svc: DemoService, run: dict[str, Any], operator: str) -> None:
    run = plain(run)
    decision = run.get("decision") or {}
    action = run.get("action") or {}
    outcome = run.get("outcome") or {}
    usage = run.get("usage") or {}
    model = f", {run['model']}" if run.get("model") else ""
    st.subheader(f"{run['family']} / seed {run['seed']} ({run['mode']}{model})")
    cols = st.columns(4)
    cols[0].metric("Status", run["status"])
    cols[1].metric("Route", run.get("route") or "-")
    cols[2].metric("Decision", decision.get("action_type") or "-", decision.get("source"))
    cols[3].metric(
        "Model calls / cost", f"{usage.get('llm_calls', 0)} / ${usage.get('cost_usd', 0)}"
    )
    st.write(
        f"Ledger: **{action.get('ledger_status', '-')}** · "
        f"Outcome: **{outcome.get('status', '-')}**"
    )
    if decision.get("reason"):
        st.info(f"Escalation reason: {decision['reason']}")

    if run["status"] == "awaiting_approval":
        with st.container(border=True):
            st.markdown("**Approval required**")
            st.json(run.get("pending_approval"))
            note = st.text_input("Note", key=f"note-{run['run_id']}")
            left, right = st.columns(2)
            rid, note_value = run["run_id"], note or None
            with left:
                action_button(
                    "Approve",
                    f"approve-{rid}",
                    svc.approve,
                    rid,
                    actor=operator,
                    note=note_value,
                    primary=True,
                )
            with right:
                action_button(
                    "Reject", f"reject-{rid}", svc.reject, rid, actor=operator, note=note_value
                )
    if run["status"] in {"halted", "interrupted"}:
        action_button("Resume", f"resume-{run['run_id']}", svc.resume, run["run_id"])
    with st.expander("Decision trace"):
        st.dataframe(run.get("trace") or [], use_container_width=True)
    with st.expander("Full run record"):
        st.json(run)


def cases_tab(svc: DemoService, operator: str) -> None:
    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Start a demo case**")
        cases = svc.demo_cases()
        key = st.selectbox("Case", [c["key"] for c in cases], key="case")
        mode = st.radio("Mode", MODES, key="mode", horizontal=True)
        model = st.selectbox(
            "Model (recorded answers)",
            svc.demo_models(),
            key="model",
            disabled=mode == "deterministic",
        )
        if st.button("Start", key="start", type="primary"):
            case = next(c for c in cases if c["key"] == key)
            run = attempt(
                svc.start_run, family=case["family"], seed=case["seed"], mode=mode, model=model
            )
            if run:
                st.session_state["run_id"] = run["run_id"]
        runs = svc.list_runs()
        st.markdown("**Recent runs**")
        ids = [r["run_id"] for r in runs]
        if ids:
            current = st.session_state.get("run_id")
            index = ids.index(current) if current in ids else 0
            st.session_state["run_id"] = st.selectbox("Run", ids, index=index)
    with right:
        run_id = st.session_state.get("run_id")
        if run_id:
            run = attempt(svc.get_run, run_id)
            if run:
                show_run(svc, run, operator)
        else:
            st.write("Start a case to see how it is handled.")


def governance_tab(svc: DemoService, operator: str) -> None:
    gov = plain(svc.governance())
    stop = gov["emergency_stop"]
    st.markdown(f"**Emergency stop:** {'ENGAGED' if stop else 'released'}")
    if stop:
        st.json(stop)
        action_button("Release stop", "release", svc.release_stop, actor=operator)
    else:
        reason = st.text_input("Reason", key="stop-reason")
        action_button(
            "Engage stop",
            "engage",
            svc.engage_stop,
            actor=operator,
            reason=reason or "operator request",
            primary=True,
        )
    st.markdown("**Circuit breakers**")
    st.dataframe(
        [
            {"resource": r, **(b or {"state": "closed (unused)"})}
            for r, b in gov["breakers"].items()
        ],
        use_container_width=True,
    )
    st.markdown("**Recent audit entries**")
    st.dataframe(list(reversed(gov["audit"])), use_container_width=True)


def evaluation_tab(svc: DemoService) -> None:
    ev = plain(svc.evaluation())
    st.caption(
        "Outcomes are synthetic: results measure decisions inside the simulator. "
        "See docs/evaluation.md for method, findings and limitations."
    )
    st.markdown("**Reports**")
    st.dataframe(
        [
            {
                "label": r["label"],
                "mode": r["mode"],
                "reasoner": r["reasoner"],
                "cases": r["summary"].get("cases"),
                "decision accuracy": r["summary"].get("decision_accuracy"),
                "resolution rate": r["summary"].get("resolution_rate"),
                "failure escalations": r["summary"].get("failure_escalations"),
                "unauthorized": r["summary"].get("unauthorized_actions"),
                "cost (USD)": r["summary"].get("total_cost_usd"),
            }
            for r in ev["reports"]
        ],
        use_container_width=True,
    )
    names = [c["name"] for c in ev["comparisons"]]
    if names:
        default = names.index("comparison-v1-models") if "comparison-v1-models" in names else 0
        chosen = st.selectbox("Comparison", names, index=default)
        comparison = next(c for c in ev["comparisons"] if c["name"] == chosen)
        st.markdown("**Held-out results**")
        st.dataframe(
            [
                {
                    "configuration": label,
                    "decision accuracy": m["decision_accuracy"],
                    "95% interval": m["accuracy_ci95"],
                    "resolution rate": m["resolution_rate"],
                    "cost per agent case (USD)": m["cost_per_agent_case_usd"],
                }
                for label, m in comparison["held_out"].items()
            ],
            use_container_width=True,
        )
        st.markdown("**Paired comparisons (exact McNemar)**")
        st.dataframe(comparison["pairs"], use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="CaseForge", layout="wide")
    svc = get_service(SETTINGS)
    st.title("CaseForge operator console")
    st.caption(
        "Demo mode: agent decisions replay recorded Claude Sonnet 5.5 answers from the "
        "benchmark. Nothing calls a model or spends money. Operator identity is simulated; "
        "roles are enforced."
    )
    operator = st.sidebar.selectbox("Acting as", svc.operators(), key="operator")
    if plain(svc.governance())["emergency_stop"]:
        st.error("Emergency stop engaged: runs halt at the next checkpoint until released.")
    cases, governance, evaluation = st.tabs(["Cases", "Governance", "Evaluation"])
    with cases:
        cases_tab(svc, operator)
    with governance:
        governance_tab(svc, operator)
    with evaluation:
        evaluation_tab(svc)


main()
