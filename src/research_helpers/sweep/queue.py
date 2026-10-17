"""Put many sweeps through few scheduler arrays: plan lists, unit queues, and quarantine.

A sweep is one run directory, one manifest, and one array. The unit of work is a (run directory,
task index) pair: exactly one slice of one sweep, which 'run_slice' already knows how to run and
resume.

A queue is a text file of units, one per line, and each element of one array runs a contiguous block
of them ('templates/queue.sbatch'). Nothing about a sweep changes.

A unit is re-runnable, never re-partitioned. It names a slice by the index its manifest planned, so
a queue regenerated with 'pending=True' after a partial run reproduces the same slices.
"""

from __future__ import annotations

import glob
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from research_helpers.project import current_project
from research_helpers.sweep.collect import missing_task_indices
from research_helpers.sweep.grid import MANIFEST_NAME, Manifest, slice_bounds
from research_helpers.sweep.runner import ARTEFACTS_DIR, PARTS_DIR

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping

__all__ = [
    'QUARANTINE_SUFFIX',
    'QUEUE_SUFFIX',
    'Unit',
    'build_units',
    'chunk',
    'expand_run_dirs',
    'quarantine',
    'read_plan_list',
    'read_units',
    'select_run_dirs',
    'shuffled',
    'write_queues',
]

QUEUE_SUFFIX = '.units'

# appended to a set-aside file
QUARANTINE_SUFFIX = '.quarantined'

# how often 'build_units(pending=True)' reports progress
PENDING_PROGRESS = 250

# a plan list line is a config and a run directory
PLAN_FIELDS = 2


@dataclass(frozen=True)
class Unit:
    """A slice of a sweep."""

    run_dir: str
    task: int

    def line(self) -> str:
        """Render the unit as a line of a queue file."""
        return f'{self.run_dir}\t{self.task}'


def read_plan_list(path: Path | str) -> list[tuple[Path, Path]]:
    """Read a plan list: one 'config<TAB>run_dir' per line, blank lines and '#' comments skipped.

    Paths are taken as written, so relative ones resolve against the working directory.

    Arguments:
        path: the plan list.

    Returns:
        The (config, run directory) pairs, in order.

    Raises:
        ValueError: if a line does not have exactly two tab-separated fields.

    """
    source = Path(path)
    pairs = []
    for number, raw in enumerate(source.read_text(encoding='utf-8').splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != PLAN_FIELDS:
            msg = f'{source}:{number}: expected "config<TAB>run_dir", got {raw!r}'
            raise ValueError(msg)
        pairs.append((Path(fields[0]), Path(fields[1])))
    return pairs


def expand_run_dirs(patterns: Iterable[str | Path]) -> list[Path]:
    """Expand run directory arguments.

    Arguments:
        patterns: run directories, or patterns matching them.

    Returns:
        The planned run directories (those holding a manifest), sorted and without duplicates.

    Raises:
        FileNotFoundError: if a plain path is not a planned run directory, or a pattern matches none.

    """
    found: set[Path] = set()
    for pattern in map(str, patterns):
        if glob.has_magic(pattern):
            # glob.glob because Path.glob refuses an absolute pattern
            matches = [Path(match) for match in glob.glob(pattern) if (Path(match) / MANIFEST_NAME).exists()]  # noqa: PTH207
            if not matches:
                msg = f'{pattern!r} matches no planned run directory'
                raise FileNotFoundError(msg)
            found.update(matches)
            continue
        path = Path(pattern)
        if not (path / MANIFEST_NAME).exists():
            msg = f'{path} is not a planned run directory (no {MANIFEST_NAME}). Plan it first'
            raise FileNotFoundError(msg)
        found.add(path)
    return sorted(found)


def _manifest_value(manifest: Manifest, key: str) -> str | None:
    """Return a manifest's value for 'key' from its metadata."""
    for source in (manifest.metadata, manifest.constants):
        if key in source:
            return str(source[key])
    return None


def select_run_dirs(
    run_dirs: Iterable[Path],
    *,
    where: Mapping[str, Collection[str]] | None = None,
    where_not: Mapping[str, Collection[str]] | None = None,
) -> list[Path]:
    """Keep the sweeps whose manifests match, to queue a campaign in parts.

    Arguments:
        run_dirs: planned run directories.
        where: key to accepted values. A sweep is kept only if, for every key, its value is one of
            these. Keys are looked up in the manifest's metadata, then its constants, and values are
            compared as text.
        where_not: key to rejected values. A sweep is dropped if any of its values is one of these.

    Returns:
        The run directories kept, in the order given.

    """
    wanted = {key: {str(value) for value in values} for key, values in (where or {}).items()}
    unwanted = {key: {str(value) for value in values} for key, values in (where_not or {}).items()}
    kept = []
    for run_dir in run_dirs:
        manifest = Manifest.load(run_dir)
        if any(_manifest_value(manifest, key) not in values for key, values in wanted.items()):
            continue
        if any(_manifest_value(manifest, key) in values for key, values in unwanted.items()):
            continue
        kept.append(run_dir)
    return kept


def build_units(run_dirs: Iterable[Path], *, pending: bool = False) -> list[Unit]:
    """Return every slice of every sweep, in run directory then task order.

    Arguments:
        run_dirs: planned run directories.
        pending: only the slices still holding an unfinished combination, as 'status' finds them.

    Returns:
        The units.

    """
    run_dirs = list(run_dirs)
    units = []
    for number, run_dir in enumerate(run_dirs, start=1):
        tasks = missing_task_indices(run_dir) if pending else range(1, Manifest.load(run_dir).n_tasks + 1)
        units += [Unit(str(run_dir), task) for task in tasks]
        if pending and number % PENDING_PROGRESS == 0:
            print(f'  {number} of {len(run_dirs)} sweeps read', flush=True)
    return units


def shuffled(units: Iterable[Unit], seed: int) -> list[Unit]:
    """Return the units in a seeded random order, so that each element draws a mix of sweeps.

    Arguments:
        units: the units.
        seed: the seed for the order.

    Returns:
        The same units, reordered.

    """
    order = list(units)
    random.Random(seed).shuffle(order)
    return order


def chunk(units: list[Unit], per_task: int, max_array: int) -> list[list[Unit]]:
    """Split units into groups small enough for one array of at most 'max_array' elements each.

    Arguments:
        units: the units.
        per_task: units each element runs.
        max_array: elements per array.

    Returns:
        The groups, in order, each holding at most 'per_task * max_array' units.

    Raises:
        ValueError: if 'per_task' or 'max_array' is below 1.

    """
    if per_task < 1 or max_array < 1:
        msg = f'per_task and max_array must be at least 1, got {per_task} and {max_array}'
        raise ValueError(msg)
    size = per_task * max_array
    return [units[start : start + size] for start in range(0, len(units), size)]


def write_queues(
    units: list[Unit],
    out: Path | str,
    per_task: int,
    max_array: int | None = None,
    *,
    force: bool = False,
) -> list[tuple[Path, int]]:
    """Write the queue files for a list of units, named '<out>.01.units', '<out>.02.units', ...

    An existing queue of the same stem is refused unless 'force' is set. A resumed queue
    takes a new stem. With 'force', every file of the old queue is removed first, so that a
    shorter queue never leaves an old file behind.

    Arguments:
        units: the units, in the order the elements should run them.
        out: the queue's stem.
        per_task: units each element runs. Part of the queue: submit it with the same number.
        max_array: elements per array, and so per file. Defaults to the project's 'max-array'.
        force: replace an existing queue of this stem.

    Returns:
        For each file, its path and the array width to submit it with.

    Raises:
        FileExistsError: if a queue of this stem exists and 'force' is not set.

    """
    stem = Path(out)
    width = max_array if max_array is not None else current_project().sweep.max_array
    groups = chunk(units, per_task, width)

    stem.parent.mkdir(parents=True, exist_ok=True)
    existing = sorted(stem.parent.glob(f'{glob.escape(stem.name)}.*{QUEUE_SUFFIX}'))
    if existing and not force:
        msg = (
            f'{existing[0]} exists. Give this queue a new stem (e.g. {stem.name}_r1), or rewrite it '
            'with --force (force=True) only once no array is still reading it'
        )
        raise FileExistsError(msg)
    for stale in existing:
        stale.unlink()

    written = []
    for number, group in enumerate(groups, start=1):
        path = stem.parent / f'{stem.name}.{number:02d}{QUEUE_SUFFIX}'
        path.write_text(''.join(unit.line() + '\n' for unit in group), encoding='utf-8')
        written.append((path, -(-len(group) // per_task)))
    return written


def read_units(path: Path | str, element: int, per_task: int) -> list[Unit]:
    """Return the units that an array element runs.

    Arguments:
        path: the queue file.
        element: the 1-based array element.
        per_task: units per element.

    Returns:
        Lines '(element - 1) * per_task + 1' to 'element * per_task' of the file, as units. Empty
        past the end of the file.

    Raises:
        ValueError: if 'element' or 'per_task' is below 1, or a line is malformed.

    """
    if element < 1 or per_task < 1:
        msg = f'element and per_task must be at least 1, got {element} and {per_task}'
        raise ValueError(msg)
    source = Path(path)
    block = source.read_text(encoding='utf-8').splitlines()[(element - 1) * per_task : element * per_task]
    units = []
    for raw in block:
        fields = raw.split('\t')
        if len(fields) != PLAN_FIELDS:
            msg = f'{source}: malformed unit {raw!r}'
            raise ValueError(msg)
        units.append(Unit(fields[0], int(fields[1])))
    return units


def _damaged(part: Path) -> bool:
    """Report whether a part file holds NUL bytes or a line that is not JSON."""
    data = part.read_bytes()
    if b'\x00' in data:
        return True
    for line in data.decode('utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            return True
    return False


def _set_aside(path: Path) -> None:
    """Rename a file, never over an earlier set-aside copy."""
    target = path.with_name(path.name + QUARANTINE_SUFFIX)
    number = 1
    while target.exists():
        number += 1
        target = path.with_name(f'{path.name}{QUARANTINE_SUFFIX}.{number}')
    path.rename(target)


def quarantine(
    units: Iterable[Unit],
    *,
    apply: bool = False,
    artefacts_dir: str = ARTEFACTS_DIR,
) -> Counter[str]:
    """Set aside every result of these units, so that a pending queue runs them again.

    This is for units that two processes ran at once. When a scheduler re-queues an element whose
    node has stopped answering, the original process can keep running, and the same block then runs
    twice, from two nodes, appending to the same part files. On network storage that leaves runs of
    NUL bytes and lines spliced together.

    Arguments:
        units: the units the duplicated elements ran ('read_units' of each element).
        apply: rename the files. Without it, only count them.
        artefacts_dir: the run directory's subdirectory holding per-combination artefacts.

    Returns:
        Counts of 'units', 'part files', 'damaged part files' and 'artefacts' found, and of files
        'set aside'.

    """
    counts: Counter[str] = Counter()
    for unit in units:
        run_dir = Path(unit.run_dir)
        manifest = Manifest.load(run_dir)
        start, end = slice_bounds(manifest.n_combinations, manifest.n_tasks, unit.task)
        part = run_dir / PARTS_DIR / f'task-{unit.task:05d}.jsonl'
        artefacts = [
            run_dir / artefacts_dir / f'{combination["combination_id"]}.json'
            for combination in manifest.combinations[start:end]
        ]
        found = [path for path in artefacts if path.exists()]

        counts['units'] += 1
        counts['artefacts'] += len(found)
        if part.exists():
            counts['part files'] += 1
            counts['damaged part files'] += _damaged(part)
        if apply:
            for path in ([part] if part.exists() else []) + found:
                _set_aside(path)
                counts['set aside'] += 1
    return counts
