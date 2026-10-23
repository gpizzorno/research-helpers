"""Assemble an arXiv submission."""

from __future__ import annotations

import re
import shutil
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from research_helpers.archive import archive_directory
from research_helpers.project import PAPER_DOCUMENT, ArxivSettings, current_project, resolve
from research_helpers.prose import COMMENT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from research_helpers.project import PaperSettings

__all__ = ['ALLOWED', 'bbl_format', 'build', 'check', 'manifest', 'pack', 'preview', 'report', 'unused']

# arXiv's permitted filename characters
ALLOWED = re.compile(r'^[A-Za-z0-9_+,=.-]+$')

# the version comment biblatex writes into a .bbl
BBL_VERSION = re.compile(r'\$ biblatex bbl format version ([\d.]+) \$')

# engines with no font expansion, where microtype's expansion=true is a hard error
NO_FONT_EXPANSION = ('xelatex', 'xetex')

# the files of an upload searched for markers: those TeX reads as text, in which '%' starts a comment
TEXT_SUFFIXES = ('.tex', '.bbl', '.sty', '.cls', '.clo', '.cfg', '.def', '.bst')

# number of lines with problem markers shown before collapsing to only their number
LISTED_LINES = 10

# an '\includegraphics' option list, which may hold one level of braces
GRAPHICS_OPTIONS = r'(?:\[(?:[^\]{}]|\{[^{}]*\})*\]\s*)*'

DEFAULT_PATTERNS = ('*.tex', '*.png', '*.pdf')
DEFAULT_PASSES = 3


def manifest(
    *,
    patterns: Iterable[str] = DEFAULT_PATTERNS,
    extra: Mapping[str, Path] | None = None,
    document: str = PAPER_DOCUMENT,
) -> dict[str, Path]:
    r"""Return the upload set, keyed by the path each file takes inside the submission.

    Names are taken relative to the directory holding the manuscript, so a table installed at
    'tex/tables/scores.tex' and read as '\input{tables/scores}' is uploaded as
    'tables/scores.tex' and resolves the same way on arXiv. Only the tables and figures that
    the manuscript reads are uploaded ('\input' and '\includegraphics' outside a comment).
    A name with no file behind it is listed as written, so that 'check' reports it missing.

    Arguments:
        patterns: glob patterns a file in the tables and figures directories must match.
        extra: anything else the build needs, e.g. a class file or a logo, keyed by its path
            inside the submission.
        document: target: 'paper', or a name under '[tool.research-helpers.documents]'.

    Returns:
        Submission path to source file, in a stable order.

    Raises:
        KeyError: if no document of that name is configured.

    """
    settings = current_project().document(document)
    patterns = tuple(patterns)
    text = _uncommented(settings.main)

    files = {settings.main.name: settings.main, settings.bbl.name: settings.bbl}
    for directory in _float_directories(settings):
        written_as = _written_as(directory, settings.main.parent)
        for name in sorted(_references(text, written_as)):
            for path in _resolve(directory / name, patterns) or [directory / name]:
                files[(written_as / path.relative_to(directory)).as_posix()] = path
    files.update({name: Path(path) for name, path in (extra or {}).items()})
    return files


def unused(
    files: Mapping[str, Path],
    *,
    patterns: Iterable[str] = DEFAULT_PATTERNS,
    document: str = PAPER_DOCUMENT,
) -> list[str]:
    """Return tables and figures omitted from the upload.

    Includes any file that the manuscript does not read, or reads in some
    way the manifest does not recognise, such as through a macro.

    Arguments:
        files: the upload set, from 'manifest'.
        patterns: the glob patterns 'manifest' was given.
        document: the target document.

    Returns:
        Each omitted file.

    """
    settings = current_project().document(document)
    patterns = tuple(patterns)
    uploaded = {path.resolve() for path in files.values()}
    left = {}
    for directory in _float_directories(settings):
        written_as = _written_as(directory, settings.main.parent)
        for path in sorted(directory.rglob('*')) if directory.is_dir() else []:
            if path.is_file() and _admitted(path, patterns) and path.resolve() not in uploaded:
                left[(written_as / path.relative_to(directory)).as_posix()] = None
    return list(left)


def _float_directories(settings: PaperSettings) -> list[Path]:
    """Return a list of unique tables and figures directories."""
    return list(dict.fromkeys((settings.tables_dir, settings.figures_dir)))


def _written_as(directory: Path, base: Path) -> Path:
    """Return a directory as used in the manuscript."""
    return directory.relative_to(base) if directory.is_relative_to(base) else Path(directory.name)


def _references(text: str, directory: Path) -> set[str]:
    r"""Return the names that the text reads from 'directory', by '\input' or '\includegraphics'."""
    name = r'\{\s*' + re.escape(directory.as_posix()) + r'/([^}]+?)\s*\}'
    inputs = re.findall(r'\\input\s*' + name, text)
    graphics = re.findall(r'\\includegraphics\*?\s*' + GRAPHICS_OPTIONS + name, text)
    return set(inputs) | set(graphics)


def _resolve(target: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Resolve a file's name, including any admissible extensions according to the patterns."""
    if not target.parent.is_dir():
        return []
    return [
        path
        for path in sorted(target.parent.iterdir())
        if target.name in (path.name, path.stem) and path.is_file() and _admitted(path, patterns)
    ]


def _admitted(path: Path, patterns: tuple[str, ...]) -> bool:
    """Report whether a file matches any of the patterns."""
    return any(fnmatch(path.name, pattern) for pattern in patterns)


def _uncommented(path: Path) -> str:
    """Return a TeX file's text without its comments, or nothing if there is no such file."""
    return COMMENT.sub('', path.read_text(encoding='utf-8')) if path.is_file() else ''


def bbl_format(path: Path) -> str | None:
    """Return the format version declared in a biblatex .bbl."""
    if not path.exists():
        return None
    found = BBL_VERSION.search(path.read_text(encoding='utf-8'))
    return found.group(1) if found else None


def check(  # noqa: PLR0913 -- a keyword for each setting it can override, and the document
    files: Mapping[str, Path],
    *,
    engine: str | None = None,
    texlive: int | None = None,
    expected_bbl_format: str | None = None,
    markers: Iterable[str] | None = None,
    document: str = PAPER_DOCUMENT,
) -> list[str]:
    """Return every reason this submission would be rejected or would build wrongly.

    Arguments:
        files: the upload set, from 'manifest'.
        engine: the LaTeX engine selected on arXiv. Defaults to the project's setting.
        texlive: the TeX Live year selected on arXiv, used in messages.
        expected_bbl_format: the biblatex .bbl format that year reads. Defaults to the project's setting.
        markers: text that must not reach the submission, checked outside comments in every
            TeX file. Defaults to the project's setting (none).
        document: the target document: 'paper', or a name under '[tool.research-helpers.documents]'.

    Returns:
        One line per problem, empty when there is nothing wrong.

    Raises:
        KeyError: if no document of that name is configured.

    """
    paper = current_project().document(document)
    if not paper.manuscript:
        return [f'the {document} is configured without a manuscript: nothing to submit']
    settings: ArxivSettings = resolve(
        current_project().arxiv,
        engine=engine,
        texlive=texlive,
        bbl_format=expected_bbl_format,
        markers=None if markers is None else tuple(markers),
    )
    return [
        *_unfit_names(files),
        *_bbl_problems(paper.main, paper.bbl, settings),
        *_engine_problems(paper.main, settings),
        *_markers_left(files, settings.markers),
    ]


def _unfit_names(files: Mapping[str, Path]) -> list[str]:
    """Report missing files, or files named in a way arXiv will not accept."""
    problems = [f'missing: {name}' for name, path in files.items() if not path.exists()]
    for name in files:
        parts = name.split('/')
        if not all(ALLOWED.match(part) for part in parts):
            problems.append(f"filename outside arXiv's permitted characters: {name}")
        if any(part.startswith('.') for part in parts):
            problems.append(f'hidden file, arXiv rejects these: {name}')
    return problems


def _bbl_problems(main: Path, bbl: Path, settings: ArxivSettings) -> list[str]:
    """Report a missing .bbl, one in a format the TeX Live year does not read, or older than the manuscript."""
    problems = []
    version = bbl_format(bbl)
    if version is None:
        problems.append(f'no .bbl found at {bbl}. Run the bibliography build first')
    elif version != settings.bbl_format:
        problems.append(f'{bbl.name} is format {version}, TeX Live {settings.texlive} expects {settings.bbl_format}')

    # a .bbl older than the manuscript means citations may have changed since Biber last ran
    if main.exists() and bbl.exists() and main.stat().st_mtime > bbl.stat().st_mtime:
        problems.append(f'{bbl.name} is older than {main.name}. Rebuild so Biber picks up citation changes')
    return problems


def _engine_problems(main: Path, settings: ArxivSettings) -> list[str]:
    """Report manuscript requirements unsupported by the selected engine."""
    # xetex has no font expansion, and microtype raises a hard error rather than ignoring it
    no_expansion = settings.engine.lower() in NO_FONT_EXPANSION and main.exists()
    if no_expansion and 'expansion=true' in main.read_text(encoding='utf-8'):
        return [f'{main.name} sets microtype expansion=true, a hard error under {settings.engine}. Use expansion=false']
    return []


def _markers_left(files: Mapping[str, Path], markers: tuple[str, ...]) -> list[str]:
    """Report markers left in the upload's TeX files, with their corresponding lines."""
    problems = []
    for name, path in files.items():
        if not markers or path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        lines = [COMMENT.sub('', line) for line in path.read_text(encoding='utf-8', errors='replace').splitlines()]
        for marker in markers:
            found = [number for number, line in enumerate(lines, start=1) if marker in line]
            if found:
                problems.append(f'marker {marker} left in {name}: {_line_numbers(found)}')
    return problems


def _line_numbers(numbers: list[int]) -> str:
    """Output the lines."""
    shown = ', '.join(str(number) for number in numbers[:LISTED_LINES])
    if len(numbers) > LISTED_LINES:
        shown += f', ... ({len(numbers)} in all)'
    return ('line ' if len(numbers) == 1 else 'lines ') + shown


def build(files: Mapping[str, Path], destination: Path | str) -> list[str]:
    """Copy the upload set into a freshly emptied directory.

    Arguments:
        files: the upload set, from 'manifest'.
        destination: the submission directory, emptied first so nothing stale is uploaded.

    Returns:
        The submission paths written.

    """
    target = Path(destination)
    if target.exists():
        shutil.rmtree(target)

    written = []
    for name, source in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, path)
        written.append(name)
    return written


def pack(source: Path | str, archive: Path | str | None = None) -> Path:
    """Pack a built submission as the tarball arXiv accepts.

    The archive is byte-reproducible, so re-packing an unchanged submission gives an identical
    file and a resubmission can be told apart from a rebuild.

    Arguments:
        source: the built submission directory.
        archive: where to write the tarball. Defaults to the directory's name plus '.tar.gz'.

    Returns:
        The archive written.

    """
    directory = Path(source)
    return archive_directory(Path(archive) if archive else directory.with_suffix('.tar.gz'), directory)


def preview(
    source: Path | str,
    destination: Path | str,
    *,
    engine: str | None = None,
    passes: int = DEFAULT_PASSES,
    document: str = PAPER_DOCUMENT,
) -> Path:
    """Compile a built submission with the engine arXiv will use.

    Arguments:
        source: the built submission directory.
        destination: where to compile, emptied first.
        engine: the LaTeX engine. Defaults to the project's setting.
        passes: how many times to run it, for cross-references to settle.
        document: the target document.

    Returns:
        The PDF produced.

    Raises:
        RuntimeError: if the engine produced no PDF.

    """
    import subprocess  # noqa: PLC0415 -- only needed for the optional preview

    settings = resolve(current_project().arxiv, engine=engine)
    built, target = Path(source), Path(destination)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(built, target)

    main = current_project().document(document).main.name
    for _ in range(passes):
        subprocess.run(
            [settings.engine, '-interaction=nonstopmode', main],
            cwd=target,
            capture_output=True,
            check=False,
        )

    pdf = target / Path(main).with_suffix('.pdf')
    if not pdf.exists():
        log = target / Path(main).with_suffix('.log')
        msg = f'{settings.engine} produced no PDF, see {log}'
        raise RuntimeError(msg)
    return pdf


def report(
    files: Mapping[str, Path],
    problems: list[str],
    *,
    document: str = PAPER_DOCUMENT,
    unused_files: Iterable[str] = (),
) -> str:
    """Return the manifest and anything wrong with it.

    Arguments:
        files: the upload set, from 'manifest'.
        problems: what 'check' found.
        document: the target document.
        unused_files: output of 'unused'.

    Returns:
        The report, ready to print.

    """
    settings = current_project().arxiv
    if not files:
        return 'nothing to upload: the manifest is empty\n'

    width = max(len(name) for name in files)
    lines, total = [], 0
    for name, path in files.items():
        size = path.stat().st_size if path.exists() else 0
        total += size
        lines.append(f'  {name:<{width}}  {size / 1024:>8.1f} KB' + ('' if path.exists() else '   MISSING'))
    lines.append(f'\n  {len(files)} files, {total / 1024 / 1024:.2f} MB')

    paper = current_project().document(document)
    version = bbl_format(paper.bbl)
    if version:
        lines.append(f'  bbl format {version} (TeX Live {settings.texlive})')
    left_out = list(unused_files)
    if left_out:
        lines.append(f'  not uploaded, since {paper.main.name} does not read them: {", ".join(left_out)}')

    if problems:
        lines.append(f'\n{len(problems)} problem(s):')
        lines += [f'  - {problem}' for problem in problems]
    else:
        lines.append(f'\nready to upload: select {settings.engine} and TeX Live {settings.texlive}')
    return '\n'.join(lines) + '\n'
