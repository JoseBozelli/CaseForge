"""CaseForge: stateful, governed, multi-agent workflow engine."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("caseforge")
except PackageNotFoundError:  # source tree without an installed distribution
    __version__ = "0.0.0+unknown"
