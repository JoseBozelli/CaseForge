"""Versioned procedural documents split into section chunks with provenance.

File name: <doc_id>.v<N>.md. Front matter keys: id, version, title. Each "## " heading
starts one chunk; chunk_id is "<doc_id>#<heading-slug>". A corpus holds exactly one
version of each document.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from caseforge.common.errors import ConfigError
from caseforge.common.yaml_io import parse_yaml_value
from caseforge.events.envelope import NonEmptyStr
from caseforge.events.vocabulary import Identifier

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_FILE_NAME = re.compile(r"^(?P<id>[a-z][a-z0-9-]*)\.v(?P<version>[1-9][0-9]*)\.md$")
_HEADING = re.compile(r"(?m)^## +(.+?)\s*$")
_FRONT_KEYS = frozenset({"id", "version", "title"})


class _Header(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    version: int = Field(ge=1)
    title: NonEmptyStr


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: NonEmptyStr
    doc_version: int = Field(ge=1)
    chunk_id: NonEmptyStr
    title: NonEmptyStr
    heading: NonEmptyStr
    text: NonEmptyStr


@dataclass(frozen=True)
class Corpus:
    chunks: tuple[Chunk, ...]
    paths: tuple[Path, ...]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def load_document(path: str | Path) -> tuple[Chunk, ...]:
    path = Path(path)
    name = _FILE_NAME.match(path.name)
    if name is None:
        raise ConfigError(f"document file name {path.name!r} must look like <id>.v<N>.md")
    parts = _FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if parts is None:
        raise ConfigError(f"{path.name}: missing YAML front matter")
    front = parse_yaml_value(parts.group(1))
    if not isinstance(front, dict) or set(front) != _FRONT_KEYS:
        raise ConfigError(f"{path.name}: front matter must contain exactly {sorted(_FRONT_KEYS)}")
    try:
        header = _Header.model_validate(front)
    except ValidationError as exc:
        raise ConfigError(f"invalid document header in {path.name}:\n{exc}") from exc
    if (header.id, header.version) != (name["id"], int(name["version"])):
        raise ConfigError(f"{path.name}: front matter does not match file name")

    pieces = _HEADING.split(parts.group(2))
    if pieces[0].strip():
        raise ConfigError(f"{path.name}: text before the first '## ' section")
    chunks: list[Chunk] = []
    for heading, body in zip(pieces[1::2], pieces[2::2], strict=True):
        text = " ".join(body.split())
        if not text:
            raise ConfigError(f"{path.name}: section {heading!r} is empty")
        chunks.append(
            Chunk(
                doc_id=header.id,
                doc_version=header.version,
                chunk_id=f"{header.id}#{_slug(heading)}",
                title=header.title,
                heading=heading,
                text=text,
            )
        )
    if not chunks:
        raise ConfigError(f"{path.name}: no '## ' sections")
    duplicates = sorted(c for c, n in Counter(c.chunk_id for c in chunks).items() if n > 1)
    if duplicates:
        raise ConfigError(f"{path.name}: duplicate section headings {duplicates}")
    return tuple(chunks)


def load_corpus(directory: str | Path) -> Corpus:
    paths = tuple(sorted(Path(directory).glob("*.md")))
    if not paths:
        raise ConfigError(f"no knowledge documents found in {directory}")
    chunks = tuple(chunk for path in paths for chunk in load_document(path))
    versions = Counter(doc_id for doc_id, _ in {(c.doc_id, c.doc_version) for c in chunks})
    repeated = sorted(doc_id for doc_id, count in versions.items() if count > 1)
    if repeated:
        raise ConfigError(f"multiple versions of documents {repeated} in {directory}")
    return Corpus(chunks=chunks, paths=paths)
