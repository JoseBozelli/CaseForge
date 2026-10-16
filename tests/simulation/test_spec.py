"""Tests for scenario family specifications."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from caseforge.common.errors import ConfigError
from caseforge.simulation.spec import ScenarioFamily, load_families, load_family

FAMILIES_DIR = Path(__file__).resolve().parents[2] / "config" / "simulation" / "families"


def _family_data() -> dict[str, Any]:
    return {
        "family_id": "test-family",
        "spec_version": 1,
        "case_prefix": "tf",
        "description": "Test family.",
        "source_system": "sim",
        "blockers": {
            "only": {
                "description": "Only blocker.",
                "weight": 1.0,
                "effective_actions": ["send_reminder"],
            }
        },
        "templates": [
            {
                "id": "open",
                "source_type": "case.open",
                "actor": "req",
                "offset_minutes": [0, 0],
                "attributes": {"cat": "general"},
            }
        ],
    }


def _duplicate_template(d):
    d["templates"].append(dict(d["templates"][0]))


def _unknown_blocker(d):
    d["templates"][0]["when_blocker"] = ["ghost"]


def _reversed_offsets(d):
    d["templates"][0]["offset_minutes"] = [5, 1]


def _zero_weight(d):
    d["blockers"]["only"]["weight"] = 0


def _empty_choice(d):
    d["templates"][0]["attributes"]["cat"] = {"choice": []}


def _undefined_variable(d):
    d["templates"][0]["attributes"]["cat"] = {"var": "ghost"}


_DYNAMICS = {"horizon_minutes": 60, "resolution_delay_minutes": [0, 10]}


def _ineffective_declared(d):
    d["dynamics"] = {
        **_DYNAMICS,
        "actions": {"send_reminder": {"only": 0.2}, "escalate_case": {"only": 0.9}},
    }


def _dynamics_unknown_blocker(d):
    d["dynamics"] = {**_DYNAMICS, "actions": {"send_reminder": {"only": 0.9, "ghost": 0.1}}}


def _effective_not_listed(d):
    d["dynamics"] = {**_DYNAMICS, "actions": {"escalate_case": {"only": 0.9}}}


def test_shipped_families_load() -> None:
    families = load_families(FAMILIES_DIR)
    assert [f.family_id for f in families] == [
        "conflicting-records",
        "exception-on-late-task",
        "missing-document",
        "policy-question",
        "routine-stalled-task",
    ]


def test_minimal_family_is_valid() -> None:
    assert ScenarioFamily.model_validate(_family_data()).family_id == "test-family"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_duplicate_template, "duplicate template ids"),
        (_unknown_blocker, "unknown blockers"),
        (_reversed_offsets, "offset_minutes"),
        (_zero_weight, "weight"),
        (_empty_choice, "choice"),
        (_undefined_variable, "undefined variables"),
        (_ineffective_declared, "most effective"),
        (_dynamics_unknown_blocker, "unknown blockers"),
        (_effective_not_listed, "not in dynamics.actions"),
    ],
)
def test_invalid_family_rejected(mutate, message: str) -> None:
    data = _family_data()
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        ScenarioFamily.model_validate(data)


def test_load_family_wraps_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("family_id: Bad Id\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid scenario family"):
        load_family(path)
