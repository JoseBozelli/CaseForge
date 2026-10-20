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
from caseforge.ui.theme import CSS, badge, card, esc, timeline

SETTINGS = os.environ.get("CASEFORGE_SETTINGS", "config/caseforge.yaml")
MODES = ["single_agent", "hierarchical", "deterministic"]
MODE_LABELS = {
    "single_agent": "Single agent",
    "hierarchical": "Hierarchy",
    "deterministic": "Rules only",
}
PAGES = ["Cases", "Governance", "Evaluation"]


@st.cache_resource
def get_service(settings_path: str) -> DemoService:
    return DemoService(settings_path)


def plain(value: Any) -> Any:
    return jsonable_encoder(value)


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


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
    decision, action = run.get("decision") or {}, run.get("action") or {}
    outcome, usage = run.get("outcome") or {}, run.get("usage") or {}
    model = f" · {run['model']}" if run.get("model") else ""
    html(f"### {esc(run['family'])} · seed {esc(run['seed'])} &nbsp; {badge(run['status'])}")
    html(f"<p class='cf-muted'>{esc(MODE_LABELS.get(run['mode'], run['mode']))}{esc(model)}</p>")

    cols = st.columns(4)
    with cols[0]:
        html(card("Route", run.get("route") or "-"))
    with cols[1]:
        html(card("Decision", decision.get("action_type") or "-", decision.get("source")))
    with cols[2]:
        html(
            card(
                "Execution",
                action.get("ledger_status", "-"),
                f"outcome: {outcome.get('status', '-')}",
            )
        )
    with cols[3]:
        html(
            card(
                "Spend", f"${usage.get('cost_usd', 0)}", f"{usage.get('llm_calls', 0)} model calls"
            )
        )
    if decision.get("reason"):
        st.info(f"Escalation reason: {decision['reason']}")

    rid = run["run_id"]
    if run["status"] == "awaiting_approval":
        with st.container(border=True):
            st.markdown("**Approval required**")
            pending = run.get("pending_approval") or {}
            st.write(f"Proposed action: `{pending.get('action_type', '-')}`")
            note = st.text_input("Note", key=f"note-{rid}")
            left, right = st.columns(2)
            with left:
                action_button(
                    "Approve",
                    f"approve-{rid}",
                    svc.approve,
                    rid,
                    actor=operator,
                    note=note or None,
                    primary=True,
                )
            with right:
                action_button(
                    "Reject", f"reject-{rid}", svc.reject, rid, actor=operator, note=note or None
                )
    if run["status"] in {"halted", "interrupted"}:
        action_button("Resume", f"resume-{rid}", svc.resume, rid, primary=True)

    st.markdown("#### Decision trace")
    html(timeline(run.get("trace") or []))
    with st.expander("Full run record"):
        st.json(run)


def cases_page(svc: DemoService, operator: str) -> None:
    left, right = st.columns([1, 2], gap="large")
    with left:
        with st.container(border=True):
            st.markdown("#### Start a demo case")
            cases = svc.demo_cases()
            key = st.selectbox("Case", [c["key"] for c in cases], key="case")
            mode = st.radio(
                "Mode", MODES, key="mode", horizontal=True, format_func=lambda m: MODE_LABELS[m]
            )
            model = st.selectbox(
                "Model (recorded answers)",
                svc.demo_models(),
                key="model",
                disabled=mode == "deterministic",
            )
            if st.button("Start", key="start", type="primary", use_container_width=True):
                case = next(c for c in cases if c["key"] == key)
                run = attempt(
                    svc.start_run, family=case["family"], seed=case["seed"], mode=mode, model=model
                )
                if run:
                    st.session_state["run_id"] = run["run_id"]
        runs = svc.list_runs()
        if runs:
            with st.container(border=True):
                st.markdown("#### Recent runs")
                ids = [r["run_id"] for r in runs]
                current = st.session_state.get("run_id")
                index = ids.index(current) if current in ids else 0
                st.session_state["run_id"] = st.selectbox(
                    "Run", ids, index=index, label_visibility="collapsed"
                )
    with right:
        run_id = st.session_state.get("run_id")
        run = attempt(svc.get_run, run_id) if run_id else None
        if run:
            show_run(svc, run, operator)
        else:
            html(
                card(
                    "No run selected",
                    "Start a demo case",
                    "Decisions replay recorded model answers.",
                )
            )


def governance_page(svc: DemoService, operator: str) -> None:
    gov = plain(svc.governance())
    stop = gov["emergency_stop"]
    with st.container(border=True):
        st.markdown("#### Emergency stop")
        if stop:
            reason = esc(stop.get("reason", ""))
            html(f"{badge('halted')} &nbsp; <span class='cf-muted'>{reason}</span>")
            action_button("Release stop", "release", svc.release_stop, actor=operator)
        else:
            html(f"{badge('completed').replace('completed', 'running')}")
            reason = st.text_input("Reason", key="stop-reason")
            action_button(
                "Engage stop",
                "engage",
                svc.engage_stop,
                actor=operator,
                reason=reason or "operator request",
                primary=True,
            )
    st.markdown("#### Circuit breakers")
    st.dataframe(
        [
            {"resource": r, **(b or {"state": "closed (unused)"})}
            for r, b in gov["breakers"].items()
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("#### Recent audit entries")
    st.dataframe(list(reversed(gov["audit"])), use_container_width=True, hide_index=True)


def evaluation_page(svc: DemoService) -> None:
    ev = plain(svc.evaluation())
    st.caption(
        "Outcomes are synthetic: results measure decisions inside the simulator. "
        "Method, findings and limitations: docs/evaluation.md."
    )
    names = [c["name"] for c in ev["comparisons"]]
    if names:
        default = names.index("comparison-v1-models") if "comparison-v1-models" in names else 0
        chosen = st.selectbox("Comparison", names, index=default)
        comparison = next(c for c in ev["comparisons"] if c["name"] == chosen)
        cols = st.columns(len(comparison["held_out"]))
        for col, (label, m) in zip(cols, comparison["held_out"].items(), strict=True):
            with col:
                html(card(label, m["decision_accuracy"], f"95% CI {m['accuracy_ci95']}"))
        st.markdown("#### Paired comparisons (exact McNemar)")
        st.dataframe(comparison["pairs"], use_container_width=True, hide_index=True)
    st.markdown("#### All reports")
    st.dataframe(
        [
            {
                "label": r["label"],
                "mode": r["mode"],
                "reasoner": r["reasoner"],
                "cases": r["summary"].get("cases"),
                "decision accuracy": r["summary"].get("decision_accuracy"),
                "resolution rate": r["summary"].get("resolution_rate"),
                "cost (USD)": r["summary"].get("total_cost_usd"),
            }
            for r in ev["reports"]
        ],
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(page_title="CaseForge", page_icon="◆", layout="wide")
    html(CSS)
    svc = get_service(SETTINGS)
    stop = plain(svc.governance())["emergency_stop"]
    with st.sidebar:
        html(
            "<div class='cf-brand'>CaseForge</div>"
            "<div class='cf-muted'>Governed case operations</div>"
        )
        st.write("")
        page = st.radio("Navigate", PAGES, key="page", label_visibility="collapsed")
        st.divider()
        operator = st.selectbox("Acting as", svc.operators(), key="operator")
        if stop:
            st.error("Emergency stop engaged")
        else:
            st.success("Operations running")
        st.caption(
            "Demo mode: decisions replay recorded model answers; nothing calls a model. "
            "Operator identity is simulated; roles are enforced."
        )
    st.title("CaseForge operator console")
    if page == "Cases":
        cases_page(svc, operator)
    elif page == "Governance":
        governance_page(svc, operator)
    else:
        evaluation_page(svc)


main()
