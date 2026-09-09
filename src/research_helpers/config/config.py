"""Centralized configuration system using Pydantic + YAML.

Provides a type-safe, validated configuration combining:
- Human-readable YAML configuration files
- Pydantic validation and type checking
- Environment variable overrides (SECTION__KEY=value)
- Computed properties for common paths

Scope note: this module was inherited from the parent `stevenson-graph-rag` project, where it
also carried LLM, retrieval, extraction, provenance, entity-resolution and evaluation sections.
Those have no consumer here and were removed, along with the `AppConfig` fields that made
`get_config()` fail validation against this project's single-section `config.yaml`.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel for a ${VAR} reference whose environment variable is unset; such keys are dropped
# from the parsed YAML so the corresponding field default applies.
_UNRESOLVED = object()


class PathConfig(BaseSettings):
    """File path configurations."""

    project_root: str = Field(default='.', description='Root directory of the project')
    data_dir: str = Field(default='data', description='Data directory, relative to project_root')
    cache_dir: str = Field(default='cache', description='Cache directory, relative to project_root')
    storage_dir: str = Field(default='storage', description='Storage directory, relative to project_root')

    @property
    def data_path(self) -> Path:
        """Datasets directory."""
        return Path(self.project_root) / self.data_dir

    @property
    def storage_path(self) -> Path:
        """Storage directory."""
        return Path(self.project_root) / self.storage_dir

    @property
    def cache_path(self) -> Path:
        """Cache directory."""
        return Path(self.project_root) / self.cache_dir

    @property
    def logs_path(self) -> Path:
        """Logs directory."""
        return Path(self.project_root) / self.data_dir / 'logs'

    @property
    def outputs_path(self) -> Path:
        """Outputs directory."""
        return Path(self.project_root) / self.data_dir / 'outputs'

    @property
    def analysis_path(self) -> Path:
        """Directory for analysis data."""
        return Path(self.project_root) / self.data_dir / 'analysis'

    @property
    def reports_path(self) -> Path:
        """Reports directory."""
        return Path(self.project_root) / self.data_dir / 'reports'


class CommunityConfig(BaseSettings):
    """Community detection configuration.

    The size weights mirror :data:`mltc.constants.SLPA_DEFAULT_SIZE_WEIGHTS`, which remains the
    default used by :func:`mltc.slpa.slpa`. Use :attr:`size_weights` to pass a configured set.
    """

    slpa_oversized_penalty: float = Field(
        default=0.1,
        ge=0.0,
        description='Penalty factor for oversized communities',
    )
    slpa_undersized_reward: float = Field(
        default=1.2,
        ge=1.0,
        description='Reward factor for undersized communities',
    )
    slpa_target_range_reward: float = Field(
        default=1.1,
        ge=1.0,
        description='Reward factor for communities in target size range',
    )

    @property
    def size_weights(self) -> dict[str, float]:
        """Return the weights in the shape :func:`mltc.slpa.slpa` expects."""
        return {
            'oversized_penalty': self.slpa_oversized_penalty,
            'undersized_reward': self.slpa_undersized_reward,
            'target_range_reward': self.slpa_target_range_reward,
        }


class AppConfig(BaseSettings):
    """Main application configuration."""

    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        env_nested_delimiter='__',
        env_prefix='',
        extra='ignore',
        case_sensitive=False,
    )

    # Nested configuration sections. Both default, so a partial (or absent) config.yaml loads.
    paths: PathConfig = Field(default_factory=PathConfig)
    community: CommunityConfig = Field(default_factory=CommunityConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> AppConfig:
        """Load configuration from YAML file."""
        path = Path(path)
        if not path.exists():
            msg = f'Configuration file not found: {path}'
            raise FileNotFoundError(msg)

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Handle environment variable substitution in YAML
        data = cls._substitute_env_vars(data)

        return cls(**data)

    @classmethod
    def _substitute_env_vars(cls, data: Any) -> Any:
        """Recursively substitute ${VAR} patterns with environment variables.

        A ``${VAR}`` referencing an unset variable resolves to :data:`_UNRESOLVED` and its key is
        dropped, so the field's declared default applies. Leaving the literal ``'${VAR}'`` in
        place would otherwise produce paths like ``${PROJECT_ROOT}/data``.
        """
        if isinstance(data, dict):
            substituted = {k: cls._substitute_env_vars(v) for k, v in data.items()}
            return {k: v for k, v in substituted.items() if v is not _UNRESOLVED}
        if isinstance(data, list):
            return [item for item in map(cls._substitute_env_vars, data) if item is not _UNRESOLVED]
        if isinstance(data, str) and data.startswith('${') and data.endswith('}'):
            return os.getenv(data[2:-1], _UNRESOLVED)
        return data

    def to_yaml(self, path: str | Path, exclude_none: bool = True) -> None:  # noqa: FBT001
        """Save configuration to YAML file."""
        # Convert to dict, excluding computed properties and optional None values
        data = self.model_dump(mode='json', exclude_none=exclude_none)

        with open(path, 'w') as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                indent=2,
                allow_unicode=True,
            )


# Context-local configuration using contextvars
# This provides thread-safe and async-safe configuration management
_config_var: ContextVar[AppConfig | None] = ContextVar('config', default=None)


def get_config() -> AppConfig:
    """Get context-local configuration instance.

    Returns configuration for the current context, loading from `config.yaml` if present and
    falling back to model defaults otherwise. Each context (thread, async task) gets its own
    independent configuration instance.

    Returns:
        AppConfig instance for current context

    """
    config = _config_var.get()
    if config is None:
        config_path = Path('config.yaml')
        config = AppConfig.from_yaml(config_path) if config_path.exists() else AppConfig()
        _config_var.set(config)

    return config


def set_config(config: AppConfig) -> None:
    """Set configuration instance for current context.

    Useful for testing or programmatic configuration. Changes only affect the current
    context (thread, async task) and do not impact other contexts.

    Args:
        config: AppConfig instance to use in current context

    """
    _config_var.set(config)


def reload_config(path: str | Path = 'config.yaml') -> AppConfig:
    """Reload configuration from file for current context.

    Args:
        path: Path to YAML configuration file

    Returns:
        Newly loaded AppConfig instance

    """
    config = AppConfig.from_yaml(path)
    _config_var.set(config)
    return config


def reset_config() -> None:
    """Reset configuration to uninitialized state for current context.

    Next call to get_config() in this context will reload from file/defaults.
    Does not affect other contexts.
    """
    _config_var.set(None)
