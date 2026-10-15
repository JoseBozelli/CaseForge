"""Tests for versioned prompt templates."""

from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.reasoning.prompts import PromptRegistry, load_prompt

PROMPT = (
    "---\n"
    "id: probe\n"
    "version: 1\n"
    "purpose: Test prompt.\n"
    "output_schema: ProbeFinding\n"
    "---\n"
    "Case $case_id has events: $events\n"
)


def _write(directory: Path, name: str = "probe.v1.md", text: str = PROMPT) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_load_and_render(tmp_path: Path) -> None:
    template = load_prompt(_write(tmp_path))
    assert (template.template_id, template.version) == ("probe", 1)
    assert template.output_schema == "ProbeFinding"
    assert template.variables() == {"case_id", "events"}
    assert template.render({"case_id": "c1", "events": "none"}) == "Case c1 has events: none\n"


def test_missing_and_unexpected_variables_rejected(tmp_path: Path) -> None:
    template = load_prompt(_write(tmp_path))
    with pytest.raises(ValueError, match=r"missing variables \['events'\]"):
        template.render({"case_id": "c1"})
    with pytest.raises(ValueError, match=r"unexpected variables \['other'\]"):
        template.render({"case_id": "c1", "events": "x", "other": "y"})


def test_hash_ignores_line_endings(tmp_path: Path) -> None:
    lf = load_prompt(_write(tmp_path / "lf"))
    crlf_path = tmp_path / "crlf" / "probe.v1.md"
    crlf_path.parent.mkdir()
    crlf_path.write_bytes(PROMPT.replace("\n", "\r\n").encode("utf-8"))
    crlf = load_prompt(crlf_path)
    assert lf.sha256 == crlf.sha256
    assert lf.body == crlf.body


def test_hash_changes_with_content(tmp_path: Path) -> None:
    first = load_prompt(_write(tmp_path / "a"))
    second = load_prompt(_write(tmp_path / "b", text=PROMPT.replace("has events", "lists")))
    assert first.sha256 != second.sha256


def test_file_name_must_match_front_matter(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not match file name"):
        load_prompt(_write(tmp_path, name="probe.v2.md"))


def test_bad_file_name_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="must look like"):
        load_prompt(_write(tmp_path, name="Probe.md"))


def test_missing_front_matter_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="front matter"):
        load_prompt(_write(tmp_path, text="No header here.\n"))


def test_unknown_front_matter_key_rejected(tmp_path: Path) -> None:
    text = PROMPT.replace("purpose:", "temperature: 0\npurpose:", 1)
    with pytest.raises(ConfigError, match="unknown front matter keys"):
        load_prompt(_write(tmp_path, text=text))


def test_registry_returns_latest_by_default(tmp_path: Path) -> None:
    _write(tmp_path)
    _write(tmp_path, name="probe.v2.md", text=PROMPT.replace("version: 1", "version: 2"))
    registry = PromptRegistry.from_directory(tmp_path)
    assert registry.get("probe").version == 2
    assert registry.get("probe", 1).version == 1
    with pytest.raises(KeyError):
        registry.get("ghost")
