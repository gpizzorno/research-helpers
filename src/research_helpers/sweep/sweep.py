"""The sweep module: plan, run and collect a parameter sweep."""

from __future__ import annotations

import argparse
import json
import math
import random
import time
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from research_helpers.project import current_project, resolve
from research_helpers.sweep.collect import collect_results, run_status
from research_helpers.sweep.grid import Manifest, expand_grid
from research_helpers.sweep.runner import run_slice, task_index_from_env

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ['Sweep', 'estimate_runtime', 'read_config']

DEFAULT_SAMPLES = 12
# config extensions read as YAML rather than TOML
YAML_SUFFIXES = ('.yaml', '.yml')
# array widths the estimate reports per-task wall time for
REPORTED_WIDTHS = (100, 500, 1000)
# schedulers commonly discourage arrays larger than this
LARGE_ARRAY = 1000
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
        max_tasks: int = LARGE_ARRAY,
    ) -> Manifest:
        """Expand a grid and write the manifest that every task will read.

        Arguments:
            run_dir: directory to hold the manifest, parts and results.
            grid: parameter name to the values to sweep.
            constants: fixed values on every combination, included in its identity.
            metadata: anything a task needs, e.g. a dataset name or a seed count.
            notes: free text recorded with the sweep.
            n_tasks: array width. Defaults to the smaller of 'max_tasks' and the grid size.
            max_tasks: the cap applied when 'n_tasks' is not given.

        Returns:
            The manifest, already written.

        """
        combinations = expand_grid(grid, constants)
        tasks = n_tasks or min(max_tasks, len(combinations))
        tasks = max(1, min(tasks, len(combinations)))

        manifest = Manifest(
            grid=grid,
            combinations=combinations,
            n_tasks=tasks,
            metadata=metadata or {},
            notes=notes,
        )
        manifest.save(run_dir)
        return manifest

    def main(self, argv: list[str] | None = None) -> int:
        """Run the sweep command line.

        Arguments:
            argv: command line arguments, or None to read 'sys.argv'.

        Returns:
            A process exit status.

        """
        args = self._parser().parse_args(argv)
        # every subcommand requires --run-dir, so this is always present
        run_dir = Path(args.run_dir)

        if args.command == 'plan':
            return self._plan(args, run_dir)
        if args.command == 'run':
            return self._run(args, run_dir)
        if args.command == 'collect':
            return self._collect(args, run_dir)
        if args.command == 'status':
            return self._status(run_dir)
        return self._estimate(args, run_dir)

    # subcommands
    def _plan(self, args: argparse.Namespace, run_dir: Path) -> int:
        config = read_config(args.config)
        manifest = self.plan(
            run_dir,
            grid=config['grid'],
            constants=config.get('constants'),
            metadata=config.get('metadata'),
            notes=config.get('notes', ''),
            n_tasks=args.tasks,
            max_tasks=config.get('max_tasks', LARGE_ARRAY),
        )
        per_task = math.ceil(manifest.n_combinations / manifest.n_tasks)
        print(
            f'planned {manifest.n_combinations} combinations over {manifest.n_tasks} array tasks '
            f'(~{per_task} per task)',
        )
        print(f'manifest: {run_dir / "manifest.json"}')
        if manifest.n_tasks > LARGE_ARRAY:
            print(
                f'note: many schedulers discourage arrays wider than {LARGE_ARRAY}; '
                'raise the combinations per task instead of the task count.',
            )
        print(f'\nsubmit with:\n  sbatch --array=1-{manifest.n_tasks} <your sbatch script> {run_dir}')
        return 0

    def _run(self, args: argparse.Namespace, run_dir: Path) -> int:
        manifest = Manifest.load(run_dir)
        context = self.build_context(manifest, run_dir)
        part = run_slice(
            run_dir,
            self.evaluation,
            task_index=task_index_from_env(args.task),
            n_tasks=args.tasks or manifest.n_tasks,
            context=context,
            resume=not args.no_resume,
        )
        print(f'wrote {part}')
        return 0

    def _collect(self, args: argparse.Namespace, run_dir: Path) -> int:
        frame = collect_results(run_dir, leading=args.leading or ())
        if frame.empty:
            print('no results found.')
            return 1
        print(f'collected {len(frame)} combinations -> {run_dir / "results.csv"}')
        print(frame.head(10).to_string(index=False))
        return 0

    def _status(self, run_dir: Path) -> int:
        status = run_status(run_dir)
        width = max(len(key) for key in status)
        for key, value in status.items():
            print(f'  {key:<{width}}  {value}')
        return 0

    def _estimate(self, args: argparse.Namespace, run_dir: Path) -> int:
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

        mean = sum(timings) / len(timings)
        print(
            f'\nmean {mean:.1f}s/combination over {len(timings)} random samples '
            f'(min {timings[0]:.1f}, median {timings[len(timings) // 2]:.1f}, max {timings[-1]:.1f})',
        )
        if timings[-1] > WIDE_SPREAD * timings[0]:
            print('note: wide spread across the grid, treat the mean as approximate and raise --samples.')

        settings = resolve(current_project().sweep, contention_factor=args.contention)
        self._report_projection(manifest, mean, settings.contention_factor)
        return 0

    @staticmethod
    def _report_projection(manifest: Manifest, mean: float, contention: float | None) -> None:
        """Print the per-task wall time an array of each width would need."""
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

        print('\nper-task wall time:')
        for width in REPORTED_WIDTHS:
            per_task = math.ceil(manifest.n_combinations / width)
            print(
                f'  {width:>4} tasks -> ~{per_task} combinations/task -> {per_task * projected / SECONDS_PER_HOUR:.2f} h',
            )
        print('\nPick a width whose per-task wall time is comfortably inside your time limit.')

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

        collect = commands.add_parser('collect', help='merge part files into results.csv')
        collect.add_argument('--run-dir', required=True)
        collect.add_argument('--leading', nargs='*', default=None, help='columns to show first')

        status = commands.add_parser('status', help='report sweep progress')
        status.add_argument('--run-dir', required=True)

        estimate = commands.add_parser('estimate', help='time a sample to size the array')
        estimate.add_argument('--run-dir', required=True)
        estimate.add_argument('--samples', type=int, default=DEFAULT_SAMPLES)
        estimate.add_argument('--seed', type=int, default=0)
        estimate.add_argument('--contention', type=float, default=None, help='override the configured factor')

        return parser
