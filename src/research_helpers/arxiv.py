"""Assemble an arXiv submission."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from research_helpers.archive import archive_directory
from research_helpers.project import ArxivSettings, current_project, resolve

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ['ALLOWED', 'bbl_format', 'build', 'check', 'manifest', 'pack', 'preview', 'report']

# arXiv's permitted filename characters
ALLOWED = re.compile(r'^[A-Za-z0-9_+,=.-]+$')

# the version comment biblatex writes into a .bbl
BBL_VERSION = re.compile(r'\$ biblatex bbl format version ([\d.]+) \$')

# engines with no font expansion, where microtype's expansion=true is a hard error
NO_FONT_EXPANSION = ('xelatex', 'xetex')

DEFAULT_PATTERNS = ('*.tex', '*.png', '*.pdf')
DEFAULT_PASSES = 3


def manifest(
    *,
    patterns: Iterable[str] = DEFAULT_PATTERNS,
    extra: Mapping[str, Path] | None = None,
) -> dict[str, Path]:
    r"""Return the upload set, keyed by the path each file takes inside the submission.

    Names are taken relative to the directory holding the manuscript, so a table installed at
    'tex/tables/scores.tex' and read as '\input{tables/scores}' is uploaded as
    'tables/scores.tex' and resolves the same way on arXiv.

    Arguments:
        patterns: glob patterns collected from the tables and figures directories.
        extra: anything else the build needs, e.g. a class file or a logo, keyed by its path
            inside the submission.

    Returns:
        Submission path to source file, in a stable order.

    """
    paper = current_project().paper
    base = paper.main.parent

    files = {paper.main.name: paper.main, paper.bbl.name: paper.bbl}
    for directory in (paper.tables_dir, paper.figures_dir):
        for pattern in patterns:
            for path in sorted(directory.glob(pattern)):
                name = path.relative_to(base) if path.is_relative_to(base) else Path(directory.name) / path.name
                files[str(name)] = path
    files.update({name: Path(path) for name, path in (extra or {}).items()})
    return files


def bbl_format(path: Path) -> str | None:
    """Return the format version declared in a biblatex .bbl."""
    if not path.exists():
        return None
    found = BBL_VERSION.search(path.read_text(encoding='utf-8'))
    return found.group(1) if found else None


def check(
    files: Mapping[str, Path],
    *,
    engine: str | None = None,
    texlive: int | None = None,
    expected_bbl_format: str | None = None,
) -> list[str]:
    """Return every reason this submission would be rejected or would build wrongly.

    Arguments:
        files: the upload set, from 'manifest'.
        engine: the LaTeX engine selected on arXiv. Defaults to the project's setting.
        texlive: the TeX Live year selected on arXiv, used in messages.
        expected_bbl_format: the biblatex .bbl format that year reads. Defaults to the project's setting.

    Returns:
        One line per problem, empty when there is nothing wrong.

    """
    paper = current_project().paper
    settings: ArxivSettings = resolve(
        current_project().arxiv,
        engine=engine,
        texlive=texlive,
        bbl_format=expected_bbl_format,
    )
    problems = []

    problems += [f'missing: {name}' for name, path in files.items() if not path.exists()]

    for name in files:
        parts = name.split('/')
        if not all(ALLOWED.match(part) for part in parts):
            problems.append(f"filename outside arXiv's permitted characters: {name}")
        if any(part.startswith('.') for part in parts):
            problems.append(f'hidden file, arXiv rejects these: {name}')

    main, bbl = paper.main, paper.bbl
    version = bbl_format(bbl)
    if version is None:
        problems.append(f'no .bbl found at {bbl}. Run the bibliography build first')
    elif version != settings.bbl_format:
        problems.append(
            f'{bbl.name} is format {version}, TeX Live {settings.texlive} expects {settings.bbl_format}',
        )

    # a .bbl older than the manuscript means citations may have changed since Biber last ran
    if main.exists() and bbl.exists() and main.stat().st_mtime > bbl.stat().st_mtime:
        problems.append(f'{bbl.name} is older than {main.name}. Rebuild so Biber picks up citation changes')

    # xetex has no font expansion, and microtype raises a hard error rather than ignoring it
    no_expansion = settings.engine.lower() in NO_FONT_EXPANSION and main.exists()
    if no_expansion and 'expansion=true' in main.read_text(encoding='utf-8'):
        problems.append(
            f'{main.name} sets microtype expansion=true, a hard error under {settings.engine}. Use expansion=false',
        )

    return problems


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
) -> Path:
    """Compile a built submission with the engine arXiv will use.

    Arguments:
        source: the built submission directory.
        destination: where to compile, emptied first.
        engine: the LaTeX engine. Defaults to the project's setting.
        passes: how many times to run it, for cross-references to settle.

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

    main = current_project().paper.main.name
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


def report(files: Mapping[str, Path], problems: list[str]) -> str:
    """Return the manifest and anything wrong with it.

    Arguments:
        files: the upload set, from 'manifest'.
        problems: what 'check' found.

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

    version = bbl_format(current_project().paper.bbl)
    if version:
        lines.append(f'  bbl format {version} (TeX Live {settings.texlive})')

    if problems:
        lines.append(f'\n{len(problems)} problem(s):')
        lines += [f'  - {problem}' for problem in problems]
    else:
        lines.append(f'\nready to upload: select {settings.engine} and TeX Live {settings.texlive}')
    return '\n'.join(lines) + '\n'
