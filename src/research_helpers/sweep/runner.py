"""Run one array task's slice of a sweep."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from research_helpers.sweep.grid import Manifest, slice_bounds

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    'ARTEFACTS_DIR',
    'PARTS_DIR',
    'artefact_path',
    'completed_ids',
    'jsonable',
    'read_artefact',
    'run_slice',
    'task_index_from_env',
]

PARTS_DIR = 'parts'
ARTEFACTS_DIR = 'artefacts'

# the environment variables a scheduler uses to tell a task which one it is, in the order tried
TASK_INDEX_VARS = ('SLURM_ARRAY_TASK_ID', 'SGE_TASK_ID', 'PBS_ARRAYID', 'LSB_JOBINDEX')


def jsonable(value: Any) -> Any:
    """Convert result values into JSON-serialisable equivalents.

    Arguments:
        value: any result value, including nested containers.

    Returns:
        The same value with numpy scalars unwrapped and tuples and sets rendered as lists.

    """
    if hasattr(value, 'item') and hasattr(value, 'dtype'):  # a numpy scalar
        return value.item()
    if isinstance(value, tuple | set):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def task_index_from_env(explicit: int | None = None) -> int:
    """Return the array task index, from the argument, the scheduler, or 1 for a local run.

    Arguments:
        explicit: an index given on the command line, which wins.

    Returns:
        The 1-based task index.

    """
    if explicit is not None:
        return explicit
    for name in TASK_INDEX_VARS:
        value = os.environ.get(name)
        if value:
            return int(value)
    return 1


def completed_ids(run_dir: Path | str) -> set[str]:
    """Return the combination ids already recorded in this run's parts.

    A task killed mid-write leaves a partial final line, which is skipped rather than
    treated as corruption.

    Arguments:
        run_dir: the run directory.

    Returns:
        The ids found.

    """
    done: set[str] = set()
    parts = Path(run_dir) / PARTS_DIR
    if not parts.exists():
        return done

    for path in sorted(parts.glob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                done.add(json.loads(line)['combination_id'])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def artefact_path(run_dir: Path | str, combination_id: str) -> Path:
    """Return the location where a combination's artefact is written.

    Arguments:
        run_dir: the run directory.
        combination_id: the combination's id.

    Returns:
        The path, whether or not anything was written there.

    """
    return Path(run_dir) / ARTEFACTS_DIR / f'{combination_id}.json'


def read_artefact(run_dir: Path | str, combination_id: str) -> Any:
    """Read back what a combination put aside.

    Arguments:
        run_dir: the run directory.
        combination_id: the combination's id.

    Returns:
        Whatever the evaluation returned under the manifest's 'artefact_key'.

    Raises:
        FileNotFoundError: if this combination recorded no artefact.

    """
    path = artefact_path(run_dir, combination_id)
    if not path.exists():
        msg = f'no artefact at {path}. Was the sweep planned with an artefact key?'
        raise FileNotFoundError(msg)
    return json.loads(path.read_text(encoding='utf-8'))


def run_slice(  # noqa: PLR0913
    run_dir: Path | str,
    evaluate: Callable[[dict[str, Any], Any], dict[str, Any]],
    *,
    task_index: int,
    n_tasks: int | None = None,
    context: Any = None,
    resume: bool = True,
    quiet: bool = False,
    artefact_key: str | None = None,
) -> Path:
    """Run this task's slice of the sweep, appending each result to its own part file.

    Arguments:
        run_dir: the run directory, holding the manifest.
        evaluate: called as 'evaluate(params, context)' for each combination, returning the
            measurements to record. The parameters are recorded alongside them automatically.
        task_index: 1-based array task index.
        n_tasks: total array tasks. Defaults to the manifest's value.
        context: whatever the evaluation needs, built once for the task.
        resume: skip combinations already recorded in this run.
        quiet: suppress per-combination progress.
        artefact_key: the key under which the evaluation returns output too bulky for a results row.

    Returns:
        The part file written.

    """
    directory = Path(run_dir)
    manifest = Manifest.load(directory)
    n_tasks = n_tasks or manifest.n_tasks
    artefact_key = artefact_key or manifest.artefact_key

    start, end = slice_bounds(manifest.n_combinations, n_tasks, task_index)
    assigned = manifest.combinations[start:end]

    parts = directory / PARTS_DIR
    parts.mkdir(parents=True, exist_ok=True)
    part = parts / f'task-{task_index:05d}.jsonl'
    if artefact_key:
        (directory / ARTEFACTS_DIR).mkdir(parents=True, exist_ok=True)

    already = completed_ids(directory) if resume else set()
    todo = [combination for combination in assigned if combination['combination_id'] not in already]

    if not quiet:
        print(
            f'[task {task_index}/{n_tasks}] combinations {start}..{end - 1} '
            f'({len(assigned)} assigned, {len(assigned) - len(todo)} already done, {len(todo)} to run)',
            flush=True,
        )

    with part.open('a', encoding='utf-8') as handle:
        for position, params in enumerate(todo, start=1):
            began = time.monotonic()
            measured = evaluate(params, context)
            result = {**params, **measured}

            if artefact_key:
                artefact = result.pop(artefact_key, None)
                if artefact is not None:
                    path = artefact_path(directory, params['combination_id'])
                    path.write_text(json.dumps(jsonable(artefact)), encoding='utf-8')

            result['task_index'] = task_index
            result['runtime_seconds'] = round(time.monotonic() - began, 3)

            handle.write(json.dumps(jsonable(result)) + '\n')
            handle.flush()  # a kill on a requeue partition then costs one combination

            if not quiet:
                print(
                    f'[task {task_index}] {position}/{len(todo)} '
                    f'{params["combination_id"]} in {result["runtime_seconds"]:.1f}s',
                    flush=True,
                )
    return part
