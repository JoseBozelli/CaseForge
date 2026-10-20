"""Operator console: renders, starts a run, and the service helpers it relies on."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from caseforge.api.service import DemoService

ROOT = Path(__file__).resolve().parents[2]
APP = str(ROOT / "src" / "caseforge" / "ui" / "app.py")


def _app(config_copy, monkeypatch) -> AppTest:
    monkeypatch.setenv("CASEFORGE_SETTINGS", str(config_copy))
    return AppTest.from_file(APP, default_timeout=60)


def test_console_renders(config_copy, monkeypatch) -> None:
    at = _app(config_copy, monkeypatch).run()
    assert not at.exception
    assert at.title[0].value == "CaseForge operator console"


def test_console_starts_a_rules_only_run(config_copy, monkeypatch) -> None:
    at = _app(config_copy, monkeypatch).run()
    at.selectbox(key="case").set_value("routine-stalled-task/000/none")
    at.radio(key="mode").set_value("deterministic")
    at.button(key="start").click().run()
    assert not at.exception
    assert at.session_state["run_id"].startswith("deterministic-routine-stalled-task-000-")


def test_service_lists_operators_and_runs(config_copy) -> None:
    svc = DemoService(config_copy)
    assert svc.operators() == ["admin-1", "approver-1", "viewer-1"]
    assert svc.list_runs() == []
    svc.start_run(family="routine-stalled-task", seed=7, mode="deterministic")
    assert [r["family"] for r in svc.list_runs()] == ["routine-stalled-task"]


def test_theme_escapes_model_text() -> None:
    from caseforge.ui.theme import card, timeline

    hostile = "<script>alert(1)</script>"
    assert "<script>" not in timeline([{"node": "synthesize", "reason": hostile}])
    assert "<script>" not in card("Decision", hostile, hostile)
