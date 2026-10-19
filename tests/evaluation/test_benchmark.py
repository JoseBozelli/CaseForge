"""Benchmark loading, expansion and validation."""

from collections import Counter
from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.evaluation.benchmark import CONDITIONS, load_benchmark
from caseforge.settings.loader import load_settings

GROUP = """\
benchmark_id: test-bench
version: 1
description: Test benchmark.
groups:
  - family: routine-stalled-task
    expected_route: fast_path
    escalation_acceptable: false
    forbidden_actions: [grant_policy_exception]
    cases:
      - {seeds: [0, 1], condition: none}
"""


@pytest.fixture(scope="module")
def loaded(shipped_settings_path_module):
    return load_settings(shipped_settings_path_module, environ={})


@pytest.fixture(scope="module")
def shipped_settings_path_module() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "caseforge.yaml"


def _load(path: Path, loaded):
    settings = loaded.settings
    return load_benchmark(
        path,
        families=loaded.families,
        allowed_actions=settings.agents.supervisor.allowed_actions,
        approval_required=settings.engine.approval_required,
    )


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "benchmark.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_benchmark_has_48_unique_cases(loaded) -> None:
    benchmark_path = loaded.settings_path.parent / loaded.settings.evaluation.benchmark_path
    benchmark = _load(benchmark_path, loaded)
    keys = [case.key for case in benchmark.cases]
    assert len(keys) == len(set(keys)) == 48
    families = Counter(case.family for case in benchmark.cases)
    assert set(families) == {f.family_id for f in loaded.families}
    assert {case.condition for case in benchmark.cases} <= CONDITIONS
    assert len(benchmark.sha256) == 64


def test_groups_expand_in_order_with_readable_keys(tmp_path: Path, loaded) -> None:
    benchmark = _load(_write(tmp_path, GROUP), loaded)
    assert [c.key for c in benchmark.cases] == [
        "routine-stalled-task/000/none",
        "routine-stalled-task/001/none",
    ]
    assert benchmark.cases[0].forbidden_actions == {"grant_policy_exception"}


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("family: routine-stalled-task", "family: ghost-family", "unknown family"),
        ("condition: none", "condition: meteor_strike", "condition"),
        ("[grant_policy_exception]", "[shred_case]", "not in allowed actions"),
        ("condition: none", "condition: approval_rejected", "requires approval"),
        ("expected_route: fast_path", "expected_route: teleport", "expected_route"),
        (
            "      - {seeds: [0, 1], condition: none}\n",
            "      - {seeds: [0, 1], condition: none}\n      - {seeds: [1], condition: none}\n",
            "duplicate benchmark cases",
        ),
    ],
)
def test_inconsistent_benchmarks_are_rejected(
    tmp_path: Path, loaded, old: str, new: str, message: str
) -> None:
    assert old in GROUP
    with pytest.raises(ConfigError, match=message):
        _load(_write(tmp_path, GROUP.replace(old, new, 1)), loaded)


def test_benchmark_hash_tracks_file_content(tmp_path: Path, loaded) -> None:
    first = _load(_write_in(tmp_path, "a", GROUP), loaded)
    second = _load(_write_in(tmp_path, "b", GROUP.replace("Test benchmark.", "Edited.")), loaded)
    assert first.sha256 != second.sha256


def _write_in(tmp_path: Path, name: str, text: str) -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return _write(folder, text)
