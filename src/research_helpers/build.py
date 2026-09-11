"""Module to generate a paper's tables and figures from the repository's own data and keep them current."""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from research_helpers.project import current_project

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = ['FIGURES', 'TABLES', 'Artefact', 'Drift', 'Kind', 'Registry']

LABEL = re.compile(r'\\label\{([^}]*)\}')


def _relative(path: Path, root: Path) -> Path:
    """Return 'path' relative to the project root."""
    return path.relative_to(root) if path.is_relative_to(root) else path


def _first_line(text: str | None) -> str:
    """Return the first line of a docstring."""
    lines = (text or '').strip().splitlines()
    return lines[0] if lines else ''


def _input_reference(directory: str) -> re.Pattern[str]:
    """Match 'input' basenames."""
    return re.compile(r'\\input\{' + re.escape(directory) + r'/([^}]+)\}')


def _graphics_reference(directory: str) -> re.Pattern[str]:
    """Match 'includegraphics' basenames."""
    return re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{' + re.escape(directory) + r'/([^}]+)\}')


def _float_block(environment: str) -> re.Pattern[str]:
    """Match a float of a given environment."""
    return re.compile(r'\n[ \t]*\\begin\{' + environment + r'\*?\}.*?\\end\{' + environment + r'\*?\}', re.DOTALL)


@dataclass(frozen=True)
class Kind:
    """A class of generated artefact (and how the paper refers to it)."""

    name: str  # plural, as it appears in messages, e.g. 'tables'
    suffix: str  # file extension including the dot, e.g. '.tex'
    directory: str  # directory name as the paper writes it, e.g. 'tables' in '\\input{tables/scores}'
    label_prefix: str  # required start of every label of this kind, e.g. 'tab:'
    setting: str  # name of the '~research_helpers.project.PaperSettings' field holding the install directory
    reference: re.Pattern[str]  # matches how the paper pulls one in, capturing the basename
    block: re.Pattern[str]  # matches a whole float of the corresponding environment
    float_is_generated: bool  # whether the emitter produces the float itself, or only what goes inside one
    binary: bool = False  # compare and write bytes rather than text

    def stem(self, label: str) -> str:
        """Return the filename that 'label' is written to (without extension)."""
        return label.removeprefix(self.label_prefix)

    def filename(self, label: str) -> str:
        """Return the filename that 'label' is written to."""
        return f'{self.stem(label)}{self.suffix}'

    def referenced(self, paper: str) -> set[str]:
        """Return the stems the paper pulls in with any extension removed."""
        return {name.removesuffix(self.suffix) for name in self.reference.findall(paper)}

    def hand_written(self, paper: str) -> dict[str, str]:
        """Return the floats the paper carries with no emitter behind them, keyed by label.

        Where the emitter produces the float itself, any literal float is hand-written. Where it
        produces only the contents, a float counts as hand-written when nothing inside it is
        pulled in from this kind's directory.
        """
        found = {}
        for match in self.block.finditer(paper):
            text = match.group(0)
            if not self.float_is_generated and self.reference.search(text):
                continue
            label = LABEL.search(text)
            if label:
                found[label.group(1)] = text
        return found

    def read(self, path: Path) -> str | bytes:
        """Read a built or installed artefact for comparison."""
        return path.read_bytes() if self.binary else path.read_text(encoding='utf-8')

    def write(self, path: Path, content: str | bytes) -> None:
        """Write one artefact, creating the parent directory."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding='utf-8')


TABLES = Kind(
    name='tables',
    suffix='.tex',
    directory='tables',
    label_prefix='tab:',
    setting='tables_dir',
    reference=_input_reference('tables'),
    block=_float_block('table'),
    float_is_generated=True,
)

FIGURES = Kind(
    name='figures',
    suffix='.png',
    directory='figures',
    label_prefix='fig:',
    setting='figures_dir',
    reference=_graphics_reference('figures'),
    block=_float_block('figure'),
    float_is_generated=False,
    binary=True,
)


@dataclass(frozen=True)
class Artefact:
    """A registered artefact."""

    label: str
    emitter: Callable[[], str | bytes]
    description: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)  # free-form, for a project's own tooling


class Drift(NamedTuple):
    """The three ways a paper and its emitters can disagree."""

    stale: list[str]  # installed, but no longer what the emitter produces
    missing: list[str]  # emitted here, but the paper never pulls it in
    ungenerated: list[str]  # carried by the paper by hand, with no emitter behind it

    def __bool__(self) -> bool:
        """Report whether the paper and the emitters disagree in any of the three defined ways."""
        return bool(self.stale or self.missing or self.ungenerated)


class Registry:
    """The emitters for one kind of artefact and the checks over them."""

    def __init__(self, kind: Kind) -> None:
        """Create an empty registry for artefacts of 'kind'."""
        self.kind = kind
        self._artefacts: dict[str, Artefact] = {}

    def register(
        self,
        label: str,
        *,
        description: str = '',
        **metadata: Any,
    ) -> Callable[[Callable[[], str | bytes]], Callable[[], str | bytes]]:
        r"""Register the decorated function as the emitter for 'label'.

        Arguments:
            label: the '\\label' the paper cites this artefact as, e.g. 'tab:scores'. Must carry
                the kind's prefix, since the filename is the label without it.
            description: one line, shown by '--list'.
            **metadata: kept on the 'artefact' for a project's own use.

        Returns:
            The decorator, which returns the emitter unchanged so it stays directly callable.

        Raises:
            ValueError: if the label is already registered or lacks the kind's prefix.

        """
        if not label.startswith(self.kind.label_prefix):
            msg = f'{label!r} must start with {self.kind.label_prefix!r}, which names the file it is written to'
            raise ValueError(msg)
        if label in self._artefacts:
            existing = getattr(self._artefacts[label].emitter, '__qualname__', 'another emitter')
            msg = f'{label!r} is already registered, by {existing}'
            raise ValueError(msg)

        def decorator(emitter: Callable[[], str | bytes]) -> Callable[[], str | bytes]:
            self._artefacts[label] = Artefact(
                label=label,
                emitter=emitter,
                description=description or _first_line(emitter.__doc__),
                metadata=metadata,
            )
            return emitter

        return decorator

    def __len__(self) -> int:
        """Return how many artefacts are registered."""
        return len(self._artefacts)

    def __iter__(self) -> Iterator[Artefact]:
        """Iterate the artefacts in registration order."""
        return iter(self._artefacts.values())

    def __contains__(self, label: object) -> bool:
        """Report whether 'label' is registered."""
        return label in self._artefacts

    def __getitem__(self, label: str) -> Artefact:
        """Return one artefact by label."""
        return self._artefacts[label]

    @property
    def labels(self) -> list[str]:
        """Return every registered label, in registration order."""
        return list(self._artefacts)

    def build_dir(self, directory: Path | str | None = None) -> Path:
        """Return where artefacts are built, defaulting to the project's build directory."""
        if directory is not None:
            return Path(directory)
        return current_project().paper.build_dir / self.kind.directory

    def install_dir(self, destination: Path | str | None = None) -> Path:
        """Return where the paper reads artefacts from, defaulting to the project's setting."""
        if destination is not None:
            return Path(destination)
        return Path(getattr(current_project().paper, self.kind.setting))

    def write_all(self, directory: Path | str | None = None) -> list[Path]:
        """Build every artefact into 'directory', one file per label, and return the paths."""
        target = self.build_dir(directory)
        written = []
        for artefact in self:
            path = target / self.kind.filename(artefact.label)
            self.kind.write(path, artefact.emitter())
            written.append(path)
        return written

    def install(
        self,
        destination: Path | str | None = None,
        source: Path | str | None = None,
    ) -> list[Path]:
        """Copy built artefacts to where the paper reads them.

        Arguments:
            destination: where the paper reads from. Defaults to the project's setting.
            source: where the artefacts were built. Defaults to the project's build directory.

        Returns:
            The paths written.

        Raises:
            FileNotFoundError: if an artefact has not been built.

        """
        target = self.install_dir(destination)
        built = self.build_dir(source)
        target.mkdir(parents=True, exist_ok=True)

        copied = []
        for artefact in self:
            origin = built / self.kind.filename(artefact.label)
            if not origin.exists():
                msg = f'{origin} does not exist. Build the {self.kind.name} before installing them'
                raise FileNotFoundError(msg)
            path = target / origin.name
            shutil.copyfile(origin, path)
            copied.append(path)
        return copied

    def drift(
        self,
        paper: Path | str | None = None,
        destination: Path | str | None = None,
    ) -> Drift:
        """Compare what the paper carries against what the emitters produce.

        Arguments:
            paper: the manuscript. Defaults to the project's 'paper.main'.
            destination: where the paper reads artefacts from. Defaults to the project's setting.

        Returns:
            The three ways they disagree; falsy when they do not.

        """
        manuscript = Path(paper) if paper is not None else current_project().paper.main
        target = self.install_dir(destination)
        if not manuscript.exists():
            # a repository can legitimately generate artefacts without carrying the manuscript
            msg = (
                f'no manuscript at {manuscript}, so there is nothing to check against. '
                f'Set paper.main under [tool.{TOOL_TABLE}.paper], or build without --check '
                f'in a repository that carries no paper.'
            )
            raise FileNotFoundError(msg)
        text = manuscript.read_text(encoding='utf-8')
        referenced = self.kind.referenced(text)

        stale, missing = [], []
        for artefact in self:
            stem = self.kind.stem(artefact.label)
            if stem not in referenced:
                missing.append(artefact.label)
                continue
            installed = target / self.kind.filename(artefact.label)
            if not installed.exists() or self.kind.read(installed) != artefact.emitter():
                stale.append(artefact.label)

        return Drift(stale=stale, missing=missing, ungenerated=sorted(self.kind.hand_written(text)))

    def report(self, found: Drift) -> str:
        """Return a description of what drifted, and what to do about it."""
        if not found:
            return f'OK: all {len(self)} {self.kind.name} in the paper are current\n'

        lines = []
        if found.stale:
            lines.append(f'stale, the paper is behind the data: {", ".join(found.stale)}')
        if found.missing:
            lines.append(f'emitted but never used by the paper: {", ".join(found.missing)}')
        if found.ungenerated:
            lines.append(f'written into the paper by hand, with no emitter: {", ".join(found.ungenerated)}')

        # only suggest the remedies for what actually drifted
        remedies = []
        if found.stale:
            remedies.append(f'rebuild and install the {self.kind.name}')
        if found.missing or found.ungenerated:
            remedies.append('edit the paper')
        lines.append('to fix: ' + ', then '.join(remedies))
        return '\n'.join(lines) + '\n'

    def main(self, argv: list[str] | None = None) -> int:
        """Run the build command line.

        Arguments:
            argv: command line arguments, or None to read 'sys.argv'.

        Returns:
            A process exit status: 0 on success, 1 if '--check' found drift.

        """
        parser = argparse.ArgumentParser(description=f"Generate the paper's {self.kind.name}.")
        parser.add_argument(
            '--install',
            nargs='?',
            const='',
            metavar='DIR',
            help='after building, copy into DIR (default: where the paper reads them)',
        )
        parser.add_argument(
            '--check',
            action='store_true',
            help='do not rebuild, report whether the paper is current',
        )
        parser.add_argument('--list', action='store_true', help='list what is registered')
        args = parser.parse_args(argv)

        if args.list:
            width = max((len(label) for label in self.labels), default=0)
            for artefact in self:
                print(f'  {artefact.label:<{width}}  {artefact.description}')
            return 0

        if args.check:
            try:
                found = self.drift()
            except FileNotFoundError as error:
                print(error, file=sys.stderr)
                return 1
            print(self.report(found), end='')
            return 1 if found else 0

        root = current_project().root
        for path in self.write_all():
            print(f'wrote {_relative(path, root)}')

        if args.install is not None:
            for path in self.install(args.install or None):
                print(f'installed {_relative(path, root)}')
        return 0
