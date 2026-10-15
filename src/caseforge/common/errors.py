"""Exception types shared across CaseForge packages."""


class ConfigError(ValueError):
    """Raised when a configuration file is missing, malformed or semantically invalid."""
