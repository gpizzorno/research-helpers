"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from research_helpers import arxiv as arxiv_module
from research_helpers import latex, textmath
from research_helpers.project import PAPER_DOCUMENT, Project, ProjectRootNotFoundError, current_project

if TYPE_CHECKING:
    from pathlib import Path

# 'python -OO' strips docstrings, leaving __doc__ as None
DESCRIPTION = __doc__.splitlines()[0] if __doc__ else 'Command line entry point.'


def doctor(args: argparse.Namespace) -> int:
    """Print every resolved setting, where it came from, and any path that is missing."""
    try:
        project = Project.from_pyproject(args.directory)
    except ProjectRootNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    print(project.doctor(), end='')
    return 0


def arxiv(args: argparse.Namespace) -> int:
    """Assemble the arXiv submission or report what would go into it."""
    try:
        document = current_project().document(args.document)
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return 1
    files = arxiv_module.manifest(document=args.document)
    problems = arxiv_module.check(files, document=args.document)
    unused = arxiv_module.unused(files, document=args.document)
    print(arxiv_module.report(files, problems, document=args.document, unused_files=unused), end='')

    if problems:
        return 1
    if args.dry_run:
        print('\n(dry run, nothing written)')
        return 0

    root = current_project().root
    submission = document.build_dir / 'arxiv'
    arxiv_module.build(files, submission)
    print(f'\nwrote {_relative(submission, root)}/')

    if args.tar:
        archive = arxiv_module.pack(submission)
        print(f'packed {_relative(archive, root)} ({archive.stat().st_size / 1024 / 1024:.2f} MB)')
    if args.preview:
        pdf = arxiv_module.preview(submission, submission.with_name('arxiv-preview'), document=args.document)
        print(f'preview at {_relative(pdf, root)}')
    return 0


def sty(args: argparse.Namespace) -> int:
    """Copy the LaTeX packages generated tables need beside the manuscript, or check the copies there."""
    project = current_project()
    try:
        document = project.document(args.document)
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return 1
    if not document.manuscript:
        print(
            f'the {args.document} is configured without a manuscript, so there is nowhere to copy to',
            file=sys.stderr,
        )
        return 1

    behind = 0
    for name, source in latex.packages().items():
        path = document.main.parent / name
        state = 'current' if path.is_file() and path.read_text(encoding='utf-8') == source else None
        if state is None and args.check:
            state = 'stale' if path.exists() else 'missing'
            behind += 1
        elif state is None:
            path.write_text(source, encoding='utf-8')
            state = 'written'
        # flushed: Python buffers stdout in a pipe, and the hint on stderr would land above these lines
        print(f'{state:<8} {_relative(path, project.root)}', flush=True)
    if behind:
        print(f'\nto fix: research-helpers sty --document {args.document}', file=sys.stderr)
    return 1 if behind else 0


def textmath_command(args: argparse.Namespace) -> int:
    """Print maths rewritten as text, for a caption or a cell written by hand."""
    try:
        for expression in args.expressions:
            # flushed, as in sty
            print(textmath.to_text(expression), flush=True)
    except textmath.UnsupportedMathError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _relative(path: Path, root: Path) -> Path:
    """Return 'path' relative to the project root, if it lies inside it."""
    return path.relative_to(root) if path.is_relative_to(root) else path


def main(argv: list[str] | None = None) -> int:
    """Dispatch to a subcommand."""
    parser = argparse.ArgumentParser(prog='research-helpers', description=DESCRIPTION)
    subcommands = parser.add_subparsers(dest='command', required=True)

    check = subcommands.add_parser('doctor', help=doctor.__doc__)
    check.add_argument(
        'directory',
        nargs='?',
        default=None,
        help='directory to search upward from (default: the working directory)',
    )
    check.set_defaults(handler=doctor)

    submission = subcommands.add_parser('arxiv', help=arxiv.__doc__)
    submission.add_argument(
        '--document',
        default=PAPER_DOCUMENT,
        metavar='NAME',
        help=f'the document to submit, configured under [tool.research-helpers.documents] (default: {PAPER_DOCUMENT})',
    )
    submission.add_argument('--dry-run', action='store_true', help='inventory and check without writing')
    submission.add_argument('--tar', action='store_true', help='also pack the submission as a tarball')
    submission.add_argument('--preview', action='store_true', help='also compile it with the engine arXiv will use')
    submission.set_defaults(handler=arxiv)

    packages = subcommands.add_parser('sty', help=sty.__doc__)
    packages.add_argument(
        '--document',
        default=PAPER_DOCUMENT,
        metavar='NAME',
        help=f'the document whose manuscript directory receives them (default: {PAPER_DOCUMENT})',
    )
    packages.add_argument('--check', action='store_true', help='report copies that are missing or stale, write nothing')
    packages.set_defaults(handler=sty)

    maths = subcommands.add_parser('textmath', help=textmath_command.__doc__)
    maths.add_argument(
        'expressions',
        nargs='+',
        metavar='EXPRESSION',
        help="maths without its delimiters, e.g. 'Q_{ov}'",
    )
    maths.set_defaults(handler=textmath_command)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == '__main__':
    raise SystemExit(main())
