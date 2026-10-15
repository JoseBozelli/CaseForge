"""Structural rules: agent-side code cannot reach simulator ground truth."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
GROUND_TRUTH = "caseforge.simulation.ground_truth"
TRUTH_ALLOWED = ("caseforge.simulation", "caseforge.evaluation")
AGENT_SIDE = (
    "caseforge.engine",
    "caseforge.agents",
    "caseforge.tools",
    "caseforge.reasoning",
    "caseforge.governance",
)


def _within(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def _module_name(path: Path, src: Path) -> str:
    return ".".join(path.relative_to(src).with_suffix("").parts).removesuffix(".__init__")


def _scan(path: Path) -> tuple[set[str], bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    relative = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative = True
                continue
            if node.module:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names, relative


def find_violations(src: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(src.rglob("*.py")):
        module = _module_name(path, src)
        imports, relative = _scan(path)
        if relative:
            violations.append(f"{module}: relative import")
        if not _within(module, TRUTH_ALLOWED) and any(
            _within(name, (GROUND_TRUTH,)) for name in imports
        ):
            violations.append(f"{module} imports {GROUND_TRUTH}")
        if _within(module, AGENT_SIDE) and any(
            _within(name, ("caseforge.simulation",)) for name in imports
        ):
            violations.append(f"{module} imports caseforge.simulation")
    return violations


def _write(root: Path, relative_path: str, source: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_source_tree_respects_boundaries() -> None:
    assert find_violations(SRC) == []


def test_detects_agent_side_simulation_import(tmp_path: Path) -> None:
    _write(tmp_path, "caseforge/engine/bad.py", f"from {GROUND_TRUTH} import GroundTruth\n")
    violations = find_violations(tmp_path)
    assert f"caseforge.engine.bad imports {GROUND_TRUTH}" in violations
    assert "caseforge.engine.bad imports caseforge.simulation" in violations


def test_detects_ground_truth_import_elsewhere(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "caseforge/reporting/summary.py",
        "from caseforge.simulation import ground_truth\n",
    )
    assert find_violations(tmp_path) == [f"caseforge.reporting.summary imports {GROUND_TRUTH}"]


def test_allows_simulation_internals_and_detects_relative_imports(tmp_path: Path) -> None:
    _write(tmp_path, "caseforge/simulation/world.py", f"from {GROUND_TRUTH} import GroundTruth\n")
    assert find_violations(tmp_path) == []
    _write(tmp_path, "caseforge/simulation/other.py", "from . import world\n")
    assert find_violations(tmp_path) == ["caseforge.simulation.other: relative import"]
