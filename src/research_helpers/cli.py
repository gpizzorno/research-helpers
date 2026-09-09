"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from research_helpers.project import Project, ProjectRootNotFoundError


def doctor(args: argparse.Namespace) -> int:
    """Print every resolved setting, where it came from, and any path that is missing."""
    try:
        project = Project.from_pyproject(args.directory)
    except ProjectRootNotFoundError as error:
        print(error, file=sys.stderr)
        return 1
    print(project.doctor(), end='')
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

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == '__main__':
    raise SystemExit(main())
