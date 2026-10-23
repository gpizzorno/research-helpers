"""Module to generate a paper's tables and figures from the repository's own data and keep them current."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar

from research_helpers.project import DOCUMENTS_TABLE, PAPER_DOCUMENT, TOOL_TABLE, current_project

# The decorator hands the emitter back untouched, so it must hand back the *same* type
EmitterT = TypeVar('EmitterT', bound='Callable[[], str | bytes]')

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from research_helpers.project import PaperSettings
    from research_helpers.prose import ProseCheck, ProseRegistry

__all__ = ['FIGURES', 'TABLES', 'Artefact', 'Document', 'Drift', 'Kind', 'Registry']

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
    """The three ways a paper and its emitters can disagree.

    Checked without a manuscript, in a repository that publishes a document's floats but not its
    source, 'missing' is None.
    """

    stale: list[str]  # installed, but no longer what the emitter produces
    missing: list[str] | None  # emitted here, but the paper never pulls it in. None: no manuscript to ask
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
    ) -> Callable[[EmitterT], EmitterT]:
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

        def decorator(emitter: EmitterT) -> EmitterT:
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
            if path.resolve() == origin.resolve():
                continue  # already where the paper reads it
            shutil.copyfile(origin, path)
            copied.append(path)
        return copied

    def drift(
        self,
        paper: Path | str | None = None,
        destination: Path | str | None = None,
        *,
        manuscript: bool | None = None,
    ) -> Drift:
        """Compare what the paper carries against what the emitters produce.

        Arguments:
            paper: the manuscript. Defaults to the project's 'paper.main'.
            destination: where the paper reads artefacts from. Defaults to the project's setting.
            manuscript: whether there is a manuscript to read. Defaults to true if 'paper' is given,
                and otherwise to the project's 'paper.manuscript'.

        Returns:
            The three ways they disagree; falsy when they do not.

        Raises:
            FileNotFoundError: if a manuscript is expected and is not there.
            ValueError: if 'paper' is given while 'manuscript' is false.

        """
        if manuscript is None:
            manuscript = paper is not None or current_project().paper.manuscript
        elif not manuscript and paper is not None:
            msg = f'{paper} was given as the manuscript, but manuscript=False says there is none'
            raise ValueError(msg)
        target = self.install_dir(destination)
        if not manuscript:
            return self._against_installed(target)

        source = Path(paper) if paper is not None else current_project().paper.main
        if not source.exists():
            msg = (
                f'no manuscript at {source}, so there is nothing to check against. '
                f'Set paper.main under [tool.{TOOL_TABLE}.paper], or, if this repository publishes '
                f"the paper's floats without its source, manuscript = false in the same table."
            )
            raise FileNotFoundError(msg)
        text = source.read_text(encoding='utf-8')
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

    def _against_installed(self, target: Path) -> Drift:
        """Compare every registered artefact with its installed copy, for a check without a manuscript."""
        stale = []
        for artefact in self:
            installed = target / self.kind.filename(artefact.label)
            if not installed.exists() or self.kind.read(installed) != artefact.emitter():
                stale.append(artefact.label)

        # 'write_all' never removes a file whose emitter has gone, and nothing re-renders one
        files = sorted(target.glob(f'*{self.kind.suffix}')) if target.is_dir() else []
        installed_labels = [
            self.kind.label_prefix + path.name.removesuffix(self.kind.suffix)
            for path in files
            if path.is_file() and not path.name.startswith('.')
        ]
        return Drift(stale=stale, missing=None, ungenerated=[label for label in installed_labels if label not in self])

    def report(
        self,
        found: Drift,
        document: str = PAPER_DOCUMENT,
        *,
        destination: Path | str | None = None,
    ) -> str:
        """Return a description of what drifted.

        Arguments:
            found: what 'drift' returned.
            document: what to call the manuscript in the message.
            destination: the directory of the installed copies, included in the message if there
                is no manuscript to check against.

        """
        lines = _findings(self, found, document, destination)
        if found.missing is None:
            lines.append(_unchecked(document))
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

        root = current_project().root
        if args.check:
            try:
                found = self.drift()
            except FileNotFoundError as error:
                print(error, file=sys.stderr)
                return 1
            print(self.report(found, destination=_relative(self.install_dir(), root)), end='')
            return 1 if found else 0

        for path in self.write_all():
            print(f'wrote {_relative(path, root)}')

        if args.install is not None:
            installed = self.install(args.install or None)
            for path in installed:
                print(f'installed {_relative(path, root)}')
            if len(self) and not installed:
                print(f'nothing to install: the {self.kind.name} are read from where they are built')
        return 0


def _findings(registry: Registry, found: Drift, document: str, destination: Path | str | None) -> list[str]:
    """Describe what drifted in a registry, a line for each kind of drift and one for the remedies.

    Checked without a manuscript ('found.missing' is None), the lines refer to the installed copies,
    in 'destination' if it is given.
    """
    kind = registry.kind
    no_manuscript = found.missing is None
    if destination is not None:
        copies, behind, extra = f'their copies in {destination}', f'{destination} is', f'in {destination}'
    else:
        copies, behind, extra = 'their installed copies', 'the installed copies are', 'installed'

    if not found:
        if no_manuscript:
            return [f'OK: all {len(registry)} {kind.name} match {copies}']
        return [f'OK: all {len(registry)} {kind.name} in the {document} are current']

    lines = []
    if found.stale:
        where = behind if no_manuscript else f'the {document} is'
        lines.append(f'stale, {where} behind the data: {", ".join(found.stale)}')
    if found.missing:
        lines.append(f'emitted but never used by the {document}: {", ".join(found.missing)}')
    if found.ungenerated:
        where = f'{extra} with no emitter' if no_manuscript else f'written into the {document} by hand, with no emitter'
        lines.append(f'{where}: {", ".join(found.ungenerated)}')

    # only suggest remedies for what actually drifted
    remedies = []
    if found.stale:
        remedies.append(f'rebuild and install the {kind.name}')
    if no_manuscript and found.ungenerated:
        remedies.append('delete the files without an emitter')
    elif found.missing or found.ungenerated:
        remedies.append(f'edit the {document}')
    lines.append('to fix: ' + ', then '.join(remedies))
    return lines


def _unchecked(document: str, *, prose: bool = False) -> str:
    """List of items that require a manuscript to be present."""
    unanswered = [f'whether the {document} uses each one', 'whether it carries any written in by hand']
    if prose:
        unanswered.append('the numbers its prose states')
    return 'not checked without the manuscript: ' + _series(unanswered)


def _series(items: list[str]) -> str:
    """Join items as a sentence."""
    *head, last = items
    if len(head) > 1:
        return ', '.join(head) + ', and ' + last
    return ' and '.join([*head, last])


def _setting(name: str, key: str) -> str:
    """Return a setting of a document and the table it is set in, for messages."""
    if name == PAPER_DOCUMENT:
        return f'paper.{key} under [tool.{TOOL_TABLE}.paper]'
    return f'{DOCUMENTS_TABLE}.{name}.{key} under [tool.{TOOL_TABLE}.{DOCUMENTS_TABLE}.{name}]'


class Document:
    """One manuscript, the registries of what it carries, and the checks over them.

    A project with one paper can use its registries directly. A project with a second document (a
    technical note, a supplement, the second half of a split paper) gives each document its own
    registries and a 'Document' class, so that each is built into its own directories and
    checked against its own manuscript:

        paper = Document('paper', tables, figures, prose=prose)
        note = Document('note', note_tables, note_figures, prose=prose)

    A float both documents carry is registered in both documents' registries. The decorator returns
    the emitter unchanged, so it stacks. A prose registry may be shared, since each document checks
    only the entries it prints.
    """

    def __init__(
        self,
        name: str,
        *registries: Registry,
        prose: ProseRegistry | None = None,
        settings: PaperSettings | None = None,
    ) -> None:
        """Group elements carried by a document.

        Arguments:
            name: the document's name: 'paper', or a name under '[tool.research-helpers.documents]'.
            *registries: its artefact registries, at most one of each kind.
            prose: the registry of numbers stated in prose, if any.
            settings: where the document lives, overriding the project's wiring.

        Raises:
            ValueError: if two registries are of the same kind.

        """
        kinds = [registry.kind.name for registry in registries]
        repeated = sorted({kind for kind in kinds if kinds.count(kind) > 1})
        if repeated:
            msg = f'the {name} has more than one registry of {", ".join(repeated)}. Each kind is one directory'
            raise ValueError(msg)
        self.name = name
        self.registries = tuple(registries)
        self.prose = prose
        self._settings = settings

    @property
    def settings(self) -> PaperSettings:
        """Return where the document lives."""
        return self._settings if self._settings is not None else current_project().document(self.name)

    def build_dir(self, registry: Registry) -> Path:
        """Return where a registry's artefacts are built."""
        return self.settings.build_dir / registry.kind.directory

    def install_dir(self, registry: Registry) -> Path:
        """Return where a registry's artefacts are read from."""
        return Path(getattr(self.settings, registry.kind.setting))

    def write_all(self) -> list[Path]:
        """Build every artefact of every registry, and return the paths."""
        return [path for registry in self.registries for path in registry.write_all(self.build_dir(registry))]

    def install(self) -> list[Path]:
        """Copy every built artefact to where the document reads it, and return the paths."""
        return [
            path
            for registry in self.registries
            for path in registry.install(self.install_dir(registry), self.build_dir(registry))
        ]

    def manuscript(self) -> Path:
        """Return the manuscript.

        Raises:
            FileNotFoundError: if it does not exist, or the document is configured without one.

        """
        settings = self.settings
        if not settings.manuscript:
            msg = (
                f'the {self.name} is configured without a manuscript '
                f'({_setting(self.name, "manuscript")} is false), so there is none to read'
            )
            raise FileNotFoundError(msg)
        main = settings.main
        if not main.exists():
            msg = (
                f'no manuscript at {main}, so there is nothing to check the {self.name} against. '
                f'Set {_setting(self.name, "main")}, or, if this repository publishes the '
                f"{self.name}'s floats without its source, manuscript = false in the same table."
            )
            raise FileNotFoundError(msg)
        return main

    def drift(self) -> dict[str, Drift]:
        """Compare the manuscript against every registry by kind.

        A document configured without a manuscript has each artefact compared with its installed
        copy instead (see 'Drift').
        """
        if not self.settings.manuscript:
            return {
                registry.kind.name: registry.drift(destination=self.install_dir(registry), manuscript=False)
                for registry in self.registries
            }
        main = self.manuscript()
        return {registry.kind.name: registry.drift(main, self.install_dir(registry)) for registry in self.registries}

    def check_prose(self) -> ProseCheck | None:
        """Check the numbers this document states in prose.

        Returns:
            What the check found, or None if the document has no prose registry or no manuscript.

        """
        if self.prose is None or not self.settings.manuscript:
            return None
        return self.prose.check({self.name: self.manuscript()}, document=self.name)

    def report(self, drift: dict[str, Drift], prose: ProseCheck | None = None) -> str:
        """Return a description of everything that drifted, and of anything left unchecked."""
        root = current_project().root
        lines = [
            line
            for registry in self.registries
            if registry.kind.name in drift
            for line in _findings(
                registry,
                drift[registry.kind.name],
                self.name,
                _relative(self.install_dir(registry), root),
            )
        ]
        if not self.settings.manuscript:
            lines.append(_unchecked(self.name, prose=self.prose is not None))
        text = ''.join(f'{line}\n' for line in lines)
        if prose is not None and self.prose is not None:
            text += self.prose.report(prose)
        return text

    def main(self, argv: list[str] | None = None) -> int:
        """Run the document's command line.

        Arguments:
            argv: command line arguments, or None to read 'sys.argv'.

        Returns:
            A process exit status: 0 on success, 1 if '--check' found anything.

        """
        parser = argparse.ArgumentParser(description=f'Generate and check what the {self.name} carries.')
        parser.add_argument('--install', action='store_true', help=f'after building, copy where the {self.name} reads')
        parser.add_argument(
            '--check',
            action='store_true',
            help=f'do not rebuild, report whether the {self.name} is current',
        )
        parser.add_argument('--list', action='store_true', help='list what is registered')
        args = parser.parse_args(argv)

        if args.list:
            self._list()
            return 0

        if args.check:
            try:
                drift = self.drift()
                prose = self.check_prose()
            except (FileNotFoundError, KeyError) as error:
                print(error.args[0] if error.args else error, file=sys.stderr)
                return 1
            print(self.report(drift, prose), end='')
            return 1 if any(drift.values()) or prose else 0

        root = current_project().root
        for path in self.write_all():
            print(f'wrote {_relative(path, root)}')
        if args.install:
            installed = self.install()
            for path in installed:
                print(f'installed {_relative(path, root)}')
            if not installed and any(len(registry) for registry in self.registries):
                print(f'nothing to install: the {self.name} reads its floats from where they are built')
        return 0

    def _list(self) -> None:
        """Print what is registered, by kind."""
        entries = [entry for entry in self.prose or () if entry.document == self.name]
        labels = [artefact.label for registry in self.registries for artefact in registry]
        width = max((len(label) for label in labels + [entry.key for entry in entries]), default=0)
        for registry in self.registries:
            print(f'{registry.kind.name}:')
            for artefact in registry:
                print(f'  {artefact.label:<{width}}  {artefact.description}')
        if entries:
            print('prose:')
            for entry in entries:
                print(f'  {entry.key:<{width}}  {entry.section}')
