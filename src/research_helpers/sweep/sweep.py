"""The sweep module: plan, run and collect a parameter sweep."""

from __future__ import annotations

import argparse
import glob
import json
import math
import random
import sys
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from research_helpers.project import current_project, resolve
from research_helpers.sweep.collect import collect_results, run_status
from research_helpers.sweep.grid import Manifest, expand_grid
from research_helpers.sweep.queue import (
    QUARANTINE_SUFFIX,
    Unit,
    build_units,
    expand_run_dirs,
    quarantine,
    read_plan_list,
    read_units,
    select_run_dirs,
    shuffled,
    write_queues,
)
from research_helpers.sweep.runner import run_slice, task_index_from_env
from research_helpers.sweep.stats import confidence_interval

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ['Sweep', 'estimate_runtime', 'read_config']

DEFAULT_SAMPLES = 12
# config extensions read as YAML rather than TOML
YAML_SUFFIXES = ('.yaml', '.yml')
# array widths the estimate reports per-task wall-time for
REPORTED_WIDTHS = (100, 500, 1000)
# how often a collect over many sweeps reports progress
COLLECT_PROGRESS = 250
SECONDS_PER_HOUR = 3600
# a spread this wide means the mean is a poor guide to any individual combination
WIDE_SPREAD = 3


def read_config(path: Path | str) -> dict[str, Any]:
    """Read a sweep config from TOML, JSON, or YAML.

    TOML and JSON are standard library, YAML needs 'pyyaml'.

    Arguments:
        path: the config file, read by extension.

    Returns:
        The parsed config: 'grid', and optionally 'constants', 'metadata', 'notes', 'max_tasks',
        'tuple_params', and 'artefact_key'.

    Raises:
        ImportError: for a YAML config when 'pyyaml' is not installed.

    """
    source = Path(path)
    text = source.read_text(encoding='utf-8')

    if source.suffix == '.json':
        return json.loads(text)
    if source.suffix in YAML_SUFFIXES:
        try:
            import yaml  # noqa: PLC0415
        except ImportError as error:
            msg = f'reading {source.name} needs pyyaml: pip install pyyaml, or convert the config to TOML'
            raise ImportError(msg) from error
        return yaml.safe_load(text) or {}
    return tomllib.loads(text)


def estimate_runtime(
    manifest: Manifest,
    evaluate: Callable[[dict[str, Any], Any], dict[str, Any]],
    context: Any = None,
    *,
    samples: int = DEFAULT_SAMPLES,
    seed: int = 0,
) -> list[float]:
    """Time a random sample of combinations.

    The sample is random, not strided. 'research_helpers.sweep.grid.expand_grid' orders
    combinations by the Cartesian product over sorted parameter names, so a stride lands on a
    systematically correlated subset.

    Arguments:
        manifest: the planned sweep.
        evaluate: the evaluation, called as for a real task.
        context: whatever the evaluation needs.
        samples: how many combinations to time.
        seed: seed for choosing the sample.

    Returns:
        The timings, sorted ascending.

    """
    chosen = random.Random(seed).sample(manifest.combinations, min(samples, manifest.n_combinations))
    timings = []
    for params in chosen:
        began = time.monotonic()
        evaluate(params, context)
        elapsed = time.monotonic() - began
        timings.append(elapsed)
        print(f'  {params["combination_id"]}: {elapsed:.1f}s', flush=True)
    return sorted(timings)


class Sweep:
    """A parameter sweep: an evaluation, an optional per-task context, and a command line."""

    def __init__(
        self,
        evaluate: Callable[[dict[str, Any], Any], dict[str, Any]] | None = None,
        context: Callable[[Manifest, Path], Any] | None = None,
    ) -> None:
        """Create a sweep, optionally supplying the callables rather than registering them."""
        self._evaluate = evaluate
        self._context = context

    def evaluate(
        self,
        function: Callable[[dict[str, Any], Any], dict[str, Any]],
    ) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
        """Register the evaluation, called as 'function(params, context)' for each combination."""
        self._evaluate = function
        return function

    def context(self, function: Callable[[Manifest, Path], Any]) -> Callable[[Manifest, Path], Any]:
        """Register what to build once per task, called as 'function(manifest, run_dir)'."""
        self._context = function
        return function

    @property
    def evaluation(self) -> Callable[[dict[str, Any], Any], dict[str, Any]]:
        """Return the registered evaluation.

        Raises:
            RuntimeError: if none was registered.

        """
        if self._evaluate is None:
            msg = 'this sweep has no evaluation. Register one with @sweep.evaluate'
            raise RuntimeError(msg)
        return self._evaluate

    def build_context(self, manifest: Manifest, run_dir: Path) -> Any:
        """Return the per-task context, or None if the sweep registered no context factory."""
        return self._context(manifest, run_dir) if self._context is not None else None

    def runs_dir(self) -> Path:
        """Return where sweeps live."""
        return current_project().sweep.runs_dir

    def plan(  # noqa: PLR0913
        self,
        run_dir: Path | str,
        grid: dict[str, list[Any]],
        *,
        constants: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        notes: str = '',
        n_tasks: int | None = None,
        max_tasks: int | None = None,
        tuple_params: Sequence[str] = (),
        artefact_key: str | None = None,
    ) -> Manifest:
        """Expand a grid and write the manifest that every task will read.

        Arguments:
            run_dir: directory to hold the manifest, parts and results.
            grid: parameter name to the values to sweep.
            constants: fixed values on every combination, included in its identity.
            metadata: anything a task needs, e.g. a dataset name or a seed count.
            notes: free text recorded with the sweep.
            n_tasks: array width. Defaults to the smaller of 'max_tasks' and the grid size.
            max_tasks: the cap applied when 'n_tasks' is not given. Defaults to the project's 'max-array'.
            tuple_params: parameters whose values are tuples rather than lists.
            artefact_key: the key under which the evaluation returns output too bulky for a results row.

        Returns:
            The manifest, already written.

        """
        combinations = expand_grid(grid, constants, tuple_params=tuple_params)
        cap = max_tasks if max_tasks is not None else current_project().sweep.max_array
        tasks = n_tasks or min(cap, len(combinations))
        tasks = max(1, min(tasks, len(combinations)))

        manifest = Manifest(
            grid=grid,
            combinations=combinations,
            n_tasks=tasks,
            metadata=metadata or {},
            notes=notes,
            constants=dict(constants or {}),
            tuple_params=list(tuple_params),
            artefact_key=artefact_key,
        )
        manifest.save(run_dir)
        return manifest

    def plan_config(self, config: Path | str, run_dir: Path | str, n_tasks: int | None = None) -> Manifest:
        """Plan a sweep from a config file, as the 'plan' command does.

        Arguments:
            config: the sweep config, TOML, JSON or YAML.
            run_dir: directory to hold the manifest, parts and results.
            n_tasks: array width, overriding the config's 'max_tasks' cap.

        Returns:
            The manifest.

        """
        settings = read_config(config)
        return self.plan(
            run_dir,
            grid=settings['grid'],
            constants=settings.get('constants'),
            metadata=settings.get('metadata'),
            notes=settings.get('notes', ''),
            n_tasks=n_tasks,
            max_tasks=settings.get('max_tasks'),
            tuple_params=settings.get('tuple_params', ()),
            artefact_key=settings.get('artefact_key'),
        )

    def run_unit(self, unit: Unit, *, resume: bool = True) -> Path:
        """Run a slice of a sweep, as an element of a queue does.

        The context is rebuilt for every unit and never shared between slices,
        even between two of the same sweep.

        Arguments:
            unit: the run directory and the slice's task index.
            resume: skip combinations already recorded.

        Returns:
            The part file.

        """
        run_dir = Path(unit.run_dir)
        manifest = Manifest.load(run_dir)
        return run_slice(
            run_dir,
            self.evaluation,
            task_index=unit.task,
            context=self.build_context(manifest, run_dir),
            resume=resume,
        )

    def main(self, argv: list[str] | None = None) -> int:
        """Run the sweep command line.

        Arguments:
            argv: command line arguments, or None to read 'sys.argv'.

        Returns:
            A process exit status.

        """
        args = self._parser().parse_args(argv)
        handlers: dict[str, Callable[[argparse.Namespace], int]] = {
            'plan': self._plan,
            'run': self._run,
            'collect': self._collect,
            'status': self._status,
            'estimate': self._estimate,
            'plan-list': self._plan_list,
            'queue': self._queue,
            'run-units': self._run_units,
            'quarantine': self._quarantine,
        }
        return handlers[args.command](args)

    # subcommands
    def _plan(self, args: argparse.Namespace) -> int:
        run_dir = Path(args.run_dir)
        manifest = self.plan_config(args.config, run_dir, args.tasks)
        limit = current_project().sweep.max_array
        per_task = math.ceil(manifest.n_combinations / manifest.n_tasks)
        print(
            f'planned {manifest.n_combinations} combinations over {manifest.n_tasks} array tasks '
            f'(~{per_task} per task)',
        )
        print(f'manifest: {run_dir / "manifest.json"}')
        if manifest.n_tasks > limit:
            print(
                f'note: many schedulers discourage arrays wider than {limit} (max-array); '
                'raise the combinations per task instead of the task count.',
            )
        print(f'\nsubmit with:\n  sbatch --array=1-{manifest.n_tasks} <your sbatch script> {run_dir}')
        return 0

    def _run(self, args: argparse.Namespace) -> int:
        run_dir = Path(args.run_dir)
        manifest = Manifest.load(run_dir)
        context = self.build_context(manifest, run_dir)
        part = run_slice(
            run_dir,
            self.evaluation,
            task_index=task_index_from_env(args.task),
            n_tasks=args.tasks or manifest.n_tasks,
            context=context,
            resume=not args.no_resume,
            artefact_key=args.artefact_key,
        )
        print(f'wrote {part}')
        return 0

    def _collect(self, args: argparse.Namespace) -> int:
        run_dirs = _run_dirs(args.run_dir)
        if len(run_dirs) > 1:
            empty = []
            for number, run_dir in enumerate(run_dirs, start=1):
                if collect_results(run_dir, leading=args.leading or None).empty:
                    empty.append(run_dir)
                if number % COLLECT_PROGRESS == 0:
                    print(f'  {number} of {len(run_dirs)} sweeps', flush=True)
            print(f'collected {len(run_dirs) - len(empty)} of {len(run_dirs)} sweeps')
            for run_dir in empty:
                print(f'  no results yet: {run_dir}')
            return 1 if empty else 0

        [run_dir] = run_dirs
        frame = collect_results(run_dir, leading=args.leading or None)
        if frame.empty:
            print('no results found.')
            return 1
        print(f'collected {len(frame)} combinations -> {run_dir / "results.csv"}')
        print(frame.head(10).to_string(index=False))
        return 0

    def _status(self, args: argparse.Namespace) -> int:
        run_dirs = _run_dirs(args.run_dir)
        if len(run_dirs) > 1:
            return _campaign_status(run_dirs)

        [run_dir] = run_dirs
        status = run_status(run_dir)
        width = max(len(key) for key in status)
        for key, value in status.items():
            print(f'  {key:<{width}}  {value}')

        unfinished = status.get('unfinished_tasks')
        if unfinished:
            print('\nResubmit the unfinished slices. Resuming skips what is already recorded:')
            print(f'  sbatch --array={unfinished} <your sbatch script> {run_dir}')
            print(
                f'\nThe range comes from the MANIFEST (n_tasks={status["manifest_n_tasks"]}), not from the\n'
                "config. If the config's task cap changed after this run was planned the two disagree,\n"
                'and the plan must be re-run to adopt the new value.',
            )
        return 0

    def _estimate(self, args: argparse.Namespace) -> int:
        run_dir = Path(args.run_dir)
        manifest = Manifest.load(run_dir)
        context = self.build_context(manifest, run_dir)
        timings = estimate_runtime(
            manifest,
            self.evaluation,
            context,
            samples=args.samples,
            seed=args.seed,
        )
        if not timings:
            print('nothing to time.')
            return 1

        interval = confidence_interval(timings)
        mean = interval.mean
        print(
            f'\nmean {mean:.1f}s/combination over {len(timings)} random samples '
            f'(min {timings[0]:.1f}, median {timings[len(timings) // 2]:.1f}, max {timings[-1]:.1f})',
        )
        if not math.isnan(interval.half_width):
            print(f'  95% confidence interval on the mean: {interval.low:.1f}s to {interval.high:.1f}s')
        if timings[-1] > WIDE_SPREAD * timings[0]:
            print('note: wide spread across the grid, treat the mean as approximate and raise --samples.')

        settings = resolve(current_project().sweep, contention_factor=args.contention)
        self._report_projection(manifest, mean, settings.contention_factor)
        return 0

    @staticmethod
    def _report_projection(manifest: Manifest, mean: float, contention: float | None) -> None:
        """Print the per-task wall-time an array of each width would need."""
        alone = mean * manifest.n_combinations / SECONDS_PER_HOUR
        print(f'estimated serial total: {alone:.1f} compute-hours, measured alone on a node')

        if contention is None:
            print(
                '\nNo contention factor is set, so these numbers are optimistic: a real array puts\n'
                'many tasks on one node, competing for memory bandwidth, and each combination takes\n'
                'longer than it does alone. Measure yours by timing the same combinations both ways,\n'
                'then set contention-factor under [tool.research-helpers.sweep].',
            )
            projected = mean
        else:
            projected = mean * contention
            print(
                f'projected in-array: ~{projected:.1f}s/combination at {contention}x contention, '
                f'~{alone * contention:.1f} compute-hours total',
            )

        print('\nper-task wall-time:')
        for width in REPORTED_WIDTHS:
            per_task = math.ceil(manifest.n_combinations / width)
            print(
                f'  {width:>4} tasks -> ~{per_task} combinations/task -> {per_task * projected / SECONDS_PER_HOUR:.2f} h',
            )
        print('\nPick a width whose per-task wall-time is comfortably inside your time limit.')

    # many sweeps through few arrays
    def _plan_list(self, args: argparse.Namespace) -> int:
        # one process for the whole list
        sweeps = combinations = slices = 0
        for listing in args.list:
            for config, run_dir in read_plan_list(listing):
                manifest = self.plan_config(config, run_dir)
                sweeps += 1
                combinations += manifest.n_combinations
                slices += manifest.n_tasks
        print(f'planned {sweeps} sweeps: {combinations} combinations in {slices} slices')
        print('queue them with the queue command instead of submitting one array per sweep')
        return 0

    def _queue(self, args: argparse.Namespace) -> int:
        patterns = list(args.run_dir or [])
        for listing in args.list or []:
            patterns += [str(run_dir) for _config, run_dir in read_plan_list(listing)]
        if not patterns:
            print('name the sweeps with --run-dir (paths or quoted globs) or --list', file=sys.stderr)
            return 1

        run_dirs = select_run_dirs(
            expand_run_dirs(patterns),
            where=_pairs(args.where),
            where_not=_pairs(args.where_not),
        )
        units = build_units(run_dirs, pending=args.pending)
        if args.shuffle is not None:
            units = shuffled(units, args.shuffle)
        if not units:
            print(f'{len(run_dirs)} sweeps, nothing {"pending" if args.pending else "planned"}.')
            return 0

        try:
            written = write_queues(units, args.out, args.per_task, args.max_array, force=args.force)
        except FileExistsError as error:
            print(error, file=sys.stderr)
            return 1
        print(
            f'{len(run_dirs)} sweeps, {len(units)} {"pending " if args.pending else ""}units, '
            f'{args.per_task} per array element, {len(written)} queue file(s)',
        )
        print('\nsubmit with:')
        for path, width in written:
            print(f'  sbatch --array=1-{width} <your queue script> {path} {args.per_task}')
        return 0

    def _run_units(self, args: argparse.Namespace) -> int:
        # a unit that raises is reported and the rest of the block still runs
        element = task_index_from_env(args.element)
        units = read_units(args.units, element, args.per_task)
        print(f'element {element}: {len(units)} unit(s) from {args.units}', flush=True)

        failed = []
        for unit in units:
            print(f'\n=== {unit.run_dir} task {unit.task} ===', flush=True)
            try:
                part = self.run_unit(unit, resume=not args.no_resume)
            except Exception as error:  # noqa: BLE001
                print(f'FAILED {unit.line()}: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
                failed.append(unit)
                continue
            print(f'wrote {part}', flush=True)

        if failed:
            print(f'\n{len(failed)} of {len(units)} unit(s) failed:', file=sys.stderr)
            for unit in failed:
                print(f'  {unit.line()}', file=sys.stderr)
            return 1
        return 0

    def _quarantine(self, args: argparse.Namespace) -> int:
        units = [unit for element in args.elements for unit in read_units(args.units, element, args.per_task)]
        counts = quarantine(units, apply=args.apply)
        found = ', '.join(f'{counts[key]} {key}' for key in ('units', 'part files', 'damaged part files', 'artefacts'))
        print(f'{len(args.elements)} element(s) of {args.units}: {found}')
        if not args.apply:
            print(f'nothing changed. With --apply, the part files and artefacts are renamed *{QUARANTINE_SUFFIX}')
            return 0
        print(f'set aside {counts["set aside"]} file(s). Queue what is missing with queue --pending')
        return 0

    # parser
    @staticmethod
    def _parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description='Plan, run and collect a parameter sweep.')
        commands = parser.add_subparsers(dest='command', required=True)

        plan = commands.add_parser('plan', help='expand a grid into a run manifest')
        plan.add_argument('--config', required=True, help='sweep config, TOML or JSON')
        plan.add_argument('--run-dir', required=True)
        plan.add_argument('--tasks', type=int, default=None, help='array width')

        run = commands.add_parser('run', help="run one array task's slice")
        run.add_argument('--run-dir', required=True)
        run.add_argument('--task', type=int, default=None, help='1-based index (default: from the scheduler)')
        run.add_argument('--tasks', type=int, default=None, help='override the planned array width')
        run.add_argument('--no-resume', action='store_true', help='recompute combinations already recorded')
        run.add_argument('--artefact-key', default=None, help="override the manifest's artefact key")

        collect = commands.add_parser('collect', help='merge part files into results.csv')
        collect.add_argument('--run-dir', required=True, nargs='+', help='run directories, or quoted globs')
        collect.add_argument('--leading', nargs='*', default=None, help='columns to show first')

        status = commands.add_parser('status', help='report sweep progress')
        status.add_argument('--run-dir', required=True, nargs='+', help='run directories, or quoted globs')

        estimate = commands.add_parser('estimate', help='time a sample to size the array')
        estimate.add_argument('--run-dir', required=True)
        estimate.add_argument('--samples', type=int, default=DEFAULT_SAMPLES)
        estimate.add_argument('--seed', type=int, default=0)
        estimate.add_argument('--contention', type=float, default=None, help='override the configured factor')

        _add_campaign_commands(commands)
        return parser


def _add_campaign_commands(commands: Any) -> None:
    """Register the commands that put many sweeps through few arrays."""
    plan_list = commands.add_parser('plan-list', help='plan every sweep of one or more plan lists')
    plan_list.add_argument('--list', required=True, nargs='+', help='plan lists of config<TAB>run_dir lines')

    queue = commands.add_parser('queue', help="pack sweeps' slices into queue files for few arrays")
    queue.add_argument('--run-dir', nargs='+', default=None, help='run directories, or quoted globs')
    queue.add_argument('--list', nargs='+', default=None, help='plan lists naming the run directories')
    queue.add_argument('--out', required=True, help='queue file stem: queues/c1 writes queues/c1.01.units')
    queue.add_argument('--per-task', type=int, required=True, help='units each array element runs')
    queue.add_argument('--max-array', type=int, default=None, help='elements per array (default: max-array)')
    queue.add_argument('--pending', action='store_true', help='only slices with an unfinished combination')
    queue.add_argument('--force', action='store_true', help='rewrite an existing queue, only once no array reads it')
    queue.add_argument('--where', action='append', type=_pair, default=None, metavar='KEY=VALUE', help='keep matching')
    queue.add_argument(
        '--where-not',
        action='append',
        type=_pair,
        default=None,
        metavar='KEY=VALUE',
        help='drop matching',
    )
    queue.add_argument('--shuffle', type=int, default=None, metavar='SEED', help='mix every sweep across elements')

    run_units = commands.add_parser('run-units', help="run one array element's block of a queue file")
    run_units.add_argument('--units', required=True, help='queue file')
    run_units.add_argument('--per-task', type=int, required=True, help='units per element')
    run_units.add_argument('--element', type=int, default=None, help='1-based element (default: from the scheduler)')
    run_units.add_argument('--no-resume', action='store_true', help='recompute combinations already recorded')

    hold = commands.add_parser('quarantine', help='set aside the results of elements that ran twice')
    hold.add_argument('--units', required=True, help='queue file the elements ran')
    hold.add_argument('--per-task', type=int, required=True, help='units per element')
    hold.add_argument('--elements', type=int, nargs='+', required=True, help='the elements that ran twice')
    hold.add_argument('--apply', action='store_true', help='rename the files. Without it, it only counts them')


def _pair(text: str) -> tuple[str, str]:
    """Parse a 'KEY=VALUE' argument.

    Raises:
        argparse.ArgumentTypeError: if there is no '='.

    """
    key, separator, value = text.partition('=')
    if not separator or not key:
        msg = f'expected KEY=VALUE, got {text!r}'
        raise argparse.ArgumentTypeError(msg)
    return key, value


def _pairs(pairs: list[tuple[str, str]] | None) -> dict[str, set[str]]:
    """Group repeated 'KEY=VALUE' arguments by key."""
    grouped: dict[str, set[str]] = {}
    for key, value in pairs or []:
        grouped.setdefault(key, set()).add(value)
    return grouped


def _run_dirs(arguments: list[str]) -> list[Path]:
    """Return the run directories named on the command line.

    A single plain path is taken as given, so 'collect' still reads the parts of
    a run whose manifest is gone. Anything else is expanded and must be planned.
    """
    if len(arguments) == 1 and not glob.has_magic(arguments[0]):
        return [Path(arguments[0])]
    return expand_run_dirs(arguments)


def _campaign_status(run_dirs: list[Path]) -> int:
    """Print one line of progress per sweep, and resume instructions."""
    width = max(len(str(run_dir)) for run_dir in run_dirs)
    unfinished = 0
    for run_dir in run_dirs:
        status = run_status(run_dir)
        line = f'  {run_dir!s:<{width}}  {status["completed"]}/{status["planned"]}  {status["percent"]:>5}%'
        if status.get('unfinished_tasks'):
            unfinished += 1
            line += f'  unfinished slices {status["unfinished_tasks"]}'
        print(line)
    print(f'\n{len(run_dirs) - unfinished} of {len(run_dirs)} sweeps finished')
    if unfinished:
        print('queue the unfinished slices with queue --pending, under a new --out')
    return 0
