"""Tests for corpus loading and chunking."""

from pathlib import Path

import pytest

from caseforge.common.errors import ConfigError
from caseforge.knowledge.corpus import load_corpus, load_document

CORPUS_DIR = Path(__file__).resolve().parents[2] / "config" / "knowledge" / "policies"
DOC = (
    "---\nid: sample\nversion: 1\ntitle: Sample procedure\n---\n"
    "## First step\nDo the first thing.\n\n## Second step\nDo the second thing.\n"
)


def _write(directory: Path, name: str = "sample.v1.md", text: str = DOC) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_corpus_loads_with_stable_chunk_ids() -> None:
    corpus = load_corpus(CORPUS_DIR)
    ids = [chunk.chunk_id for chunk in corpus.chunks]
    assert len(corpus.paths) == 5
    assert len(ids) == len(set(ids)) == 13
    assert "task-follow-up#reassignment" in ids
    assert {chunk.doc_version for chunk in corpus.chunks} == {1}


def test_sections_become_chunks(tmp_path: Path) -> None:
    chunks = load_document(_write(tmp_path))
    assert [c.chunk_id for c in chunks] == ["sample#first-step", "sample#second-step"]
    assert chunks[0].text == "Do the first thing."


def test_file_name_must_match_front_matter(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not match file name"):
        load_document(_write(tmp_path, name="sample.v2.md"))


def test_text_before_first_section_rejected(tmp_path: Path) -> None:
    text = DOC.replace("---\n## First", "---\nPreamble.\n## First", 1)
    with pytest.raises(ConfigError, match="before the first"):
        load_document(_write(tmp_path, text=text))


def test_duplicate_headings_rejected(tmp_path: Path) -> None:
    text = DOC.replace("## Second step", "## First step", 1)
    with pytest.raises(ConfigError, match="duplicate section headings"):
        load_document(_write(tmp_path, text=text))


def test_empty_section_rejected(tmp_path: Path) -> None:
    text = DOC.replace("Do the second thing.\n", "\n", 1)
    with pytest.raises(ConfigError, match="is empty"):
        load_document(_write(tmp_path, text=text))


def test_multiple_versions_of_a_document_rejected(tmp_path: Path) -> None:
    _write(tmp_path)
    _write(tmp_path, name="sample.v2.md", text=DOC.replace("version: 1", "version: 2"))
    with pytest.raises(ConfigError, match="multiple versions"):
        load_corpus(tmp_path)
