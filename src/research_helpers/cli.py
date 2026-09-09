"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from research_helpers import arxiv as arxiv_module
from research_helpers.project import Project, ProjectRootNotFoundError, current_project


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
    files = arxiv_module.manifest()
    problems = arxiv_module.check(files)
    print(arxiv_module.report(files, problems), end='')

    if problems:
        return 1
    if args.dry_run:
        print('\n(dry run, nothing written)')
        return 0

    submission = current_project().paper.build_dir / 'arxiv'
    arxiv_module.build(files, submission)
    print(f'\nwrote {submission}/')

    if args.tar:
        archive = arxiv_module.pack(submission)
        print(f'packed {archive} ({archive.stat().st_size / 1024 / 1024:.2f} MB)')
    if args.preview:
        pdf = arxiv_module.preview(submission, submission.with_name('arxiv-preview'))
        print(f'preview at {pdf}')
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch to a subcommand."""
    parser = argparse.ArgumentParser(prog='research-helpers', description=__doc__.splitlines()[0])
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
    submission.add_argument('--dry-run', action='store_true', help='inventory and check without writing')
    submission.add_argument('--tar', action='store_true', help='also pack the submission as a tarball')
    submission.add_argument('--preview', action='store_true', help='also compile it with the engine arXiv will use')
    submission.set_defaults(handler=arxiv)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == '__main__':
    raise SystemExit(main())
