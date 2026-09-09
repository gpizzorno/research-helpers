"""Project wiring module.

Wiring is read from '[tool.research-helpers]' in the project's 'pyproject.toml'.

Settings resolve in three layers, each overriding the last:

1. the dataclass defaults below, so everything works with no configuration at all
2. '[tool.research-helpers]' in 'pyproject.toml', which overrides defaults
3. explicit keyword arguments, which always take precedence over the other two layers

"""

from __future__ import annotations

import os
import tomllib
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeVar, get_args, get_type_hints

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

__all__ = [
    'ArxivSettings',
    'ConfigWarning',
    'FigureSettings',
    'LogSettings',
    'PaperSettings',
    'Project',
    'ProjectRootNotFoundError',
    'current_project',
    'find_project_root',
    'resolve',
]

# an ancestor directory holding any of these is the project root. 'pyproject.toml' comes first
# because it is also where the settings live.
ROOT_MARKERS = ('pyproject.toml', '.git')

# overrides the search entirely, for hosts where the checkout is not an ancestor of the CWD
ROOT_ENV_VAR = 'RESEARCH_HELPERS_ROOT'

TOOL_TABLE = 'research-helpers'

PROFILES = ('screen', 'print')
COLOURS = ('auto', 'always', 'never')

# settings whose value must be one of a fixed set, whatever section they appear in
CHOICES: Mapping[str, tuple[str, ...]] = MappingProxyType({'profile': PROFILES, 'colour': COLOURS})


class ConfigWarning(UserWarning):
    """A setting was not understood. The value is ignored and the default applies."""


class ProjectRootNotFoundError(RuntimeError):
    """No ancestor directory carried a project-root marker."""


@dataclass(frozen=True)
class PaperSettings:
    """Where the manuscript and its generated inputs live, relative to the project root."""

    main: Path = Path('tex/paper.tex')
    tables_dir: Path = Path('tex/tables')
    figures_dir: Path = Path('tex/figures')
    bbl: Path = Path('tex/out_dir/paper.bbl')
    build_dir: Path = Path('build')
    text_width_in: float = 6.45  # the document's '\\textwidth', in inches
    column_width_in: float = 3.04  # the document's '\\columnwidth', in inches


@dataclass(frozen=True)
class FigureSettings:
    """Figure styling."""

    profile: str = 'screen'
    palette: str = 'husl'
    font: str = 'DejaVu Sans'
    dpi: int = 150


@dataclass(frozen=True)
class LogSettings:
    """Where logs go and how much of them. Every value stays overridable per call."""

    directory: Path | None = None  # log directory, relative to the project root, None for console output only
    console_level: str = 'INFO'
    file_level: str = 'DEBUG'
    colour: str = 'auto'  # console logging level, file logging level, and colour setting


@dataclass(frozen=True)
class ArxivSettings:
    """Facts about the submission target. These track the submission cycle, not the package."""

    engine: str = 'xelatex'
    texlive: int = 2025
    bbl_format: str = '3.3'


Settings = PaperSettings | FigureSettings | LogSettings | ArxivSettings
SettingsT = TypeVar('SettingsT', bound='DataclassInstance')

SECTIONS: Mapping[str, type[Settings]] = MappingProxyType(
    {'paper': PaperSettings, 'figures': FigureSettings, 'log': LogSettings, 'arxiv': ArxivSettings},
)


@dataclass(frozen=True)
class Project:
    """A project's wiring, with every path resolved to an absolute location."""

    root: Path
    paper: PaperSettings = PaperSettings()
    figures: FigureSettings = FigureSettings()
    log: LogSettings = LogSettings()
    arxiv: ArxivSettings = ArxivSettings()
    pyproject: Path | None = None  # the file the settings were read from, or None if they are pure defaults
    sources: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}),
    )  # dotted setting name to 'pyproject' or 'default'

    @classmethod
    def from_pyproject(cls, start: Path | str | None = None, **overrides: Any) -> Project:
        """Load wiring by walking up from 'start' for a project root.

        Arguments:
            start: directory to search upward from. Defaults to the current working directory.
            **overrides: settings objects ('paper', 'figures', 'arxiv') replacing what was loaded.

        Returns:
            The project, with every path made absolute against the root.

        Raises:
            ProjectRootNotFoundError: if no ancestor carries a marker from 'ROOT_MARKERS'.

        """
        root = find_project_root(start)
        loaded = _load(root)
        if not overrides:
            return loaded

        unknown = set(overrides) - set(SECTIONS)
        if unknown:
            msg = f'unknown settings group(s): {", ".join(sorted(unknown))}. Expected {", ".join(SECTIONS)}'
            raise TypeError(msg)
        sources = {**loaded.sources, **{f'{name}.*': 'argument' for name in overrides}}
        return replace(loaded, sources=MappingProxyType(sources), **overrides)

    def doctor(self) -> str:
        """Return every resolved setting with the layer it came from, as well as any missing paths."""
        lines = [f'root       {self.root}']
        origin = self.pyproject.relative_to(self.root) if self.pyproject else 'none found'
        lines.append(f'pyproject  {origin}')
        if not self.pyproject:
            lines.append('           (no [tool.research-helpers] settings. Defaults apply throughout.)')
        lines.append('')

        width = max(len(f'{s}.{f.name}') for s, cls in SECTIONS.items() for f in fields(cls))
        for section in SECTIONS:
            settings = getattr(self, section)
            for field_ in fields(settings):
                dotted = f'{section}.{field_.name}'
                value = getattr(settings, field_.name)
                source = self.sources.get(dotted, self.sources.get(f'{section}.*', 'default'))
                note = ''
                if isinstance(value, Path):
                    value = value.relative_to(self.root) if value.is_relative_to(self.root) else value
                    note = '' if (self.root / value).exists() else '   MISSING'
                lines.append(f'  {dotted:<{width}}  {value!s:<28}  [{source}]{note}')
            lines.append('')
        return '\n'.join(lines).rstrip() + '\n'


def current_project() -> Project:
    """Return the enclosing project, or one carrying pure defaults if there is no root above."""
    try:
        return Project.from_pyproject()
    except ProjectRootNotFoundError:
        return Project(root=Path.cwd())


def resolve(settings: SettingsT, **overrides: Any) -> SettingsT:
    """Return 'settings' with each override applied, ignoring any that is None.

    None means 'not specified at this layer', so a caller may forward its own optional arguments
    straight through without first filtering them.

    Arguments:
        settings: the settings object to start from.
        **overrides: any field of that object.

    Returns:
        The settings, with the overrides applied.

    Raises:
        TypeError: if an override does not name a field of 'settings'.

    """
    known = {f.name for f in fields(settings)}
    unknown = set(overrides) - known
    if unknown:
        msg = f'unknown setting(s): {", ".join(sorted(unknown))}. Expected {", ".join(sorted(known))}'
        raise TypeError(msg)

    given = {name: value for name, value in overrides.items() if value is not None}
    return replace(settings, **given) if given else settings


def find_project_root(start: Path | str | None = None) -> Path:
    """Return the first ancestor of 'start' carrying a project-root marker.

    Arguments:
        start: directory to search upward from (defaults to the current working directory).

    Returns:
        The project root, absolute.

    Raises:
        ProjectRootNotFoundError: if no ancestor carries a marker.

    """
    override = os.getenv(ROOT_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()

    origin = Path(start).expanduser().resolve() if start else Path.cwd()
    for directory in (origin, *origin.parents):
        if any((directory / marker).exists() for marker in ROOT_MARKERS):
            return directory

    msg = (
        f'No project root above {origin}. Expected an ancestor directory containing one of '
        f'{", ".join(ROOT_MARKERS)}. Set {ROOT_ENV_VAR} to override.'
    )
    raise ProjectRootNotFoundError(msg)


@cache
def _load(root: Path) -> Project:
    """Read and resolve '[tool.research-helpers]' for one root."""
    path = root / 'pyproject.toml'
    table: dict[str, Any] = {}
    if path.exists():
        table = tomllib.loads(path.read_text(encoding='utf-8')).get('tool', {}).get(TOOL_TABLE, {})

    unknown = set(table) - set(SECTIONS)
    for name in sorted(unknown):
        _warn(f'unknown section [tool.{TOOL_TABLE}.{name}], ignored', path)

    sources: dict[str, str] = {}

    def read(section: str, settings_cls: type[Settings]) -> dict[str, Any]:
        raw = table.get(section) or {}
        if not isinstance(raw, dict):
            _warn(f'[tool.{TOOL_TABLE}.{section}] is not a table, ignored', path)
            raw = {}
        values, provenance = _section(settings_cls, raw, section, path)
        sources.update(provenance)
        return values

    # built one by one rather than in a loop so each keeps its own type rather than their union
    paper = PaperSettings(**read('paper', PaperSettings))
    figures = FigureSettings(**read('figures', FigureSettings))
    log = LogSettings(**read('log', LogSettings))
    arxiv = ArxivSettings(**read('arxiv', ArxivSettings))

    return Project(
        root=root,
        paper=_resolve(paper, root),
        figures=_resolve(figures, root),
        log=_resolve(log, root),
        arxiv=_resolve(arxiv, root),
        pyproject=path if table else None,
        sources=MappingProxyType(sources),
    )


def _section(
    settings_cls: type[Settings],
    raw: dict[str, Any],
    section: str,
    path: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Convert one TOML table into constructor arguments."""
    hints = get_type_hints(settings_cls)
    known = {f.name for f in fields(settings_cls)}

    values: dict[str, Any] = {}
    sources = {f'{section}.{name}': 'default' for name in known}

    for key, value in raw.items():
        name = key.replace('-', '_')
        if name not in known:
            _warn(f'unknown key "{key}" in [tool.{TOOL_TABLE}.{section}], ignored', path)
            continue
        converted = _coerce(value, hints[name], f'{section}.{key}', path)
        if converted is None:
            continue
        values[name] = converted
        sources[f'{section}.{name}'] = 'pyproject'

    for name, allowed in CHOICES.items():
        if name in values and values[name] not in allowed:
            _warn(f'{section}.{name} must be one of {", ".join(allowed)}, not "{values.pop(name)}"', path)
            sources[f'{section}.{name}'] = 'default'

    return values, sources


def _coerce(value: Any, target: type, dotted: str, path: Path) -> Any:
    """Return 'value' as 'target', or None if it cannot be."""
    target = _required(target)
    # bool is a subclass of int, so it would otherwise pass an int field silently
    if isinstance(value, bool) or (target is Path and not isinstance(value, str)):
        _warn(f'{dotted} must be a {target.__name__}, not {type(value).__name__}', path)
        return None
    if target is Path:
        return Path(value)
    if target is float and isinstance(value, int | float):
        return float(value)
    if isinstance(value, target):
        return value
    _warn(f'{dotted} must be a {target.__name__}, not {type(value).__name__}', path)
    return None


def _required(target: Any) -> Any:
    """Return the type inside an 'X | None' annotation, or 'target' unchanged.

    TOML has no null, so a key that is present always carries a value of the wrapped type; None
    means the key was absent and the default applies.
    """
    arguments = [argument for argument in get_args(target) if argument is not type(None)]
    return arguments[0] if len(arguments) == 1 else target


def _resolve(settings: SettingsT, root: Path) -> SettingsT:
    """Return a copy of a settings object with every path made absolute against 'root'."""
    paths = {
        f.name: root / getattr(settings, f.name)
        for f in fields(settings)
        if isinstance(getattr(settings, f.name), Path)
    }
    return replace(settings, **paths) if paths else settings


def _warn(message: str, path: Path) -> None:
    warnings.warn(f'{path}: {message}', ConfigWarning, stacklevel=3)
