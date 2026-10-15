"""Settings loading: YAML file, environment overrides, and config-graph validation."""

from __future__ import annotations

import copy
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from caseforge.common.errors import ConfigError
from caseforge.common.yaml_io import load_yaml_mapping, parse_yaml_value
from caseforge.events.mapping import MappingSpec, load_mapping
from caseforge.events.vocabulary import CanonicalVocabulary, load_vocabulary
from caseforge.settings.models import Settings
from caseforge.simulation.spec import ScenarioFamily, load_families

ENV_PREFIX: Final = "CASEFORGE__"


@dataclass(frozen=True)
class LoadedSettings:
    """Validated settings plus the vocabulary, mappings and families they reference."""

    settings: Settings
    settings_path: Path
    overrides: tuple[str, ...]
    vocabulary: CanonicalVocabulary
    vocabulary_path: Path
    mappings: tuple[MappingSpec, ...]
    mapping_paths: tuple[Path, ...]
    families: tuple[ScenarioFamily, ...]
    family_paths: tuple[Path, ...]

    @property
    def config_files(self) -> tuple[Path, ...]:
        return (
            self.settings_path,
            self.vocabulary_path,
            *self.mapping_paths,
            *self.family_paths,
        )


def apply_env_overrides(
    data: Mapping[str, Any], environ: Mapping[str, str]
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Apply CASEFORGE__SECTION__KEY=value overrides; return new data and applied keys.

    Values are parsed as YAML scalars ("7" -> 7, "true" -> True). Unknown keys are
    left for schema validation to reject.
    """
    result: dict[str, Any] = copy.deepcopy(dict(data))
    applied: list[str] = []
    for name in sorted(environ):
        if not name.startswith(ENV_PREFIX):
            continue
        parts = [part.lower() for part in name[len(ENV_PREFIX) :].split("__")]
        if not all(parts):
            raise ConfigError(f"malformed override variable {name}")
        target = result
        for part in parts[:-1]:
            node = target.setdefault(part, {})
            if not isinstance(node, dict):
                raise ConfigError(f"{name}: {part!r} is not a section")
            target = node
        target[parts[-1]] = parse_yaml_value(environ[name])
        applied.append(".".join(parts))
    return result, tuple(sorted(applied))


def load_settings(path: str | Path, environ: Mapping[str, str] | None = None) -> LoadedSettings:
    """Load settings, apply overrides, then load and cross-check everything they reference."""
    settings_path = Path(path).resolve()
    raw = load_yaml_mapping(settings_path)
    data, overrides = apply_env_overrides(raw, os.environ if environ is None else environ)
    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        applied = ", ".join(overrides) or "none"
        raise ConfigError(
            f"invalid settings in {settings_path} (overrides: {applied}):\n{exc}"
        ) from exc

    base = settings_path.parent
    vocabulary_path = (base / settings.vocabulary.canonical).resolve()
    vocabulary = load_vocabulary(vocabulary_path)
    mapping_paths = tuple((base / item).resolve() for item in settings.vocabulary.mappings)
    mappings = tuple(load_mapping(item, vocabulary) for item in mapping_paths)

    counts = Counter(spec.source_system for spec in mappings)
    duplicates = sorted(source for source, count in counts.items() if count > 1)
    if duplicates:
        raise ConfigError(f"multiple mappings for source_system {duplicates}")

    unknown = sorted(settings.triage.referenced_event_types() - vocabulary.event_types.keys())
    if unknown:
        raise ConfigError(f"triage rules reference unknown event types {unknown}")

    families_dir = (base / settings.simulation.families_dir).resolve()
    families = load_families(families_dir)
    family_paths = tuple(sorted(families_dir.glob("*.yaml")))

    return LoadedSettings(
        settings=settings,
        settings_path=settings_path,
        overrides=overrides,
        vocabulary=vocabulary,
        vocabulary_path=vocabulary_path,
        mappings=mappings,
        mapping_paths=mapping_paths,
        families=families,
        family_paths=family_paths,
    )
