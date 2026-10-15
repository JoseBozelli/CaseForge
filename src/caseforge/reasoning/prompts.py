"""Versioned prompt templates: Markdown files with YAML front matter.

File name: <id>.v<N>.md. Front matter keys: id, version, purpose, output_schema.
Placeholders use $name (string.Template), so JSON braces in prompt text need no
escaping. Rendering requires exactly the template's placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from string import Template

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from caseforge.common.errors import ConfigError
from caseforge.common.hashing import file_sha256
from caseforge.common.yaml_io import parse_yaml_value
from caseforge.events.envelope import NonEmptyStr, Sha256Hex
from caseforge.events.vocabulary import Identifier

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_FILE_NAME = re.compile(r"^(?P<id>[a-z][a-z0-9_-]*)\.v(?P<version>[1-9][0-9]*)\.md$")
_FRONT_KEYS = frozenset({"id", "version", "purpose", "output_schema"})


class PromptTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    template_id: Identifier
    version: int = Field(ge=1)
    purpose: NonEmptyStr
    output_schema: NonEmptyStr
    body: str = Field(min_length=1)
    sha256: Sha256Hex

    def variables(self) -> frozenset[str]:
        return frozenset(Template(self.body).get_identifiers())

    def render(self, variables: Mapping[str, str]) -> str:
        expected, provided = self.variables(), set(variables)
        missing, unexpected = sorted(expected - provided), sorted(provided - expected)
        if missing or unexpected:
            raise ValueError(
                f"template {self.template_id} v{self.version}: "
                f"missing variables {missing}, unexpected variables {unexpected}"
            )
        return Template(self.body).substitute(variables)


def load_prompt(path: str | Path) -> PromptTemplate:
    """Load one template; its hash covers the whole file with LF line endings."""
    path = Path(path)
    name = _FILE_NAME.match(path.name)
    if name is None:
        raise ConfigError(f"prompt file name {path.name!r} must look like <id>.v<N>.md")
    text = path.read_text(encoding="utf-8")
    parts = _FRONT_MATTER.match(text)
    if parts is None:
        raise ConfigError(f"{path.name}: missing YAML front matter")
    front = parse_yaml_value(parts.group(1))
    if not isinstance(front, dict):
        raise ConfigError(f"{path.name}: front matter must be a mapping")
    unknown = sorted(set(front) - _FRONT_KEYS)
    if unknown:
        raise ConfigError(f"{path.name}: unknown front matter keys {unknown}")
    try:
        template = PromptTemplate(
            template_id=front.get("id"),
            version=front.get("version"),
            purpose=front.get("purpose"),
            output_schema=front.get("output_schema"),
            body=parts.group(2),
            sha256=file_sha256(path),
        )
    except ValidationError as exc:
        raise ConfigError(f"invalid prompt template {path.name}:\n{exc}") from exc
    if (template.template_id, template.version) != (name["id"], int(name["version"])):
        raise ConfigError(f"{path.name}: front matter does not match file name")
    return template


class PromptRegistry:
    """Index of prompt templates by (id, version)."""

    def __init__(self, templates: Iterable[PromptTemplate]) -> None:
        self._templates: dict[tuple[str, int], PromptTemplate] = {}
        for template in templates:
            key = (template.template_id, template.version)
            if key in self._templates:
                raise ConfigError(f"duplicate prompt template {key}")
            self._templates[key] = template

    @classmethod
    def from_directory(cls, directory: str | Path) -> PromptRegistry:
        return cls(load_prompt(path) for path in sorted(Path(directory).glob("*.md")))

    def get(self, template_id: str, version: int | None = None) -> PromptTemplate:
        """Return the requested version, or the latest when version is None."""
        if version is not None:
            template = self._templates.get((template_id, version))
            if template is None:
                raise KeyError(f"unknown prompt template {template_id!r} v{version}")
            return template
        versions = [v for (tid, v) in self._templates if tid == template_id]
        if not versions:
            raise KeyError(f"unknown prompt template {template_id!r}")
        return self._templates[(template_id, max(versions))]
