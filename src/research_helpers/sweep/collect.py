"""Merge per-task part files back into one results table."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from research_helpers.sweep.grid import Manifest
from research_helpers.sweep.runner import PARTS_DIR

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pandas as pd

__all__ = ['collect_results', 'read_parts', 'run_status']

RESULTS_STEM = 'results'

# engines pandas can use to write Parquet
PARQUET_ENGINES = ('pyarrow', 'fastparquet')


def read_parts(run_dir: Path | str) -> list[dict[str, Any]]:
    """Read every result recorded by this run's tasks.

    Arguments:
        run_dir: the run directory.

    Returns:
        One dict per recorded result, in task order. A partial final line, left by a task killed
        mid-write, is skipped.

    Raises:
        FileNotFoundError: if the array has not run yet.

    """
    parts = Path(run_dir) / PARTS_DIR
    if not parts.exists():
        msg = f'no parts directory at {parts}. Has the array run yet?'
        raise FileNotFoundError(msg)

    records, malformed = [], 0
    for path in sorted(parts.glob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1

    if malformed:
        print(f'warning: skipped {malformed} malformed line(s), most likely tasks killed mid-write')
    return records


def leading_columns(run_dir: Path | str) -> list[str]:
    """Return the configuration columns of a run, in the order they should be read.

    The id first, then the constants, then the swept parameters. Everything else is a measurement.

    Arguments:
        run_dir: the run directory.

    Returns:
        The column names, or an empty list if the run has no manifest to describe it.

    """
    try:
        manifest = Manifest.load(run_dir)
    except (FileNotFoundError, TypeError, ValueError):
        return []
    return ['combination_id', *sorted(manifest.constants), *sorted(manifest.grid)]


def collect_results(
    run_dir: Path | str,
    *,
    write: bool = True,
    leading: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Merge the part files into a table de-duplicating by combination id.

    Duplicates are legitimate: a requeued task can recompute a combination whose result was
    already flushed. The last record written wins.

    Arguments:
        run_dir: the run directory.
        write: also write 'results.csv', and 'results.parquet' where an engine is installed.
        leading: columns to move to the front, so the table reads configuration first and
            measurements second. Defaults to the run's own parameters, taken from the manifest.
            Pass an explicit sequence to override it, or an empty one to leave the order alone.

    Returns:
        One row per combination.

    """
    import pandas as pd  # noqa: PLC0415

    directory = Path(run_dir)
    records = read_parts(directory)
    if not records:
        return pd.DataFrame()
    if leading is None:
        leading = leading_columns(directory)

    frame = pd.DataFrame(records)
    if 'combination_id' in frame:
        frame = frame.drop_duplicates(subset='combination_id', keep='last')

    front = [column for column in leading if column in frame.columns]
    frame = frame[front + [column for column in frame.columns if column not in front]]

    # sort on scalar columns only
    sortable = [
        column
        for column in front
        if column != 'combination_id' and not frame[column].map(lambda value: isinstance(value, list)).any()
    ]
    if sortable:
        frame = frame.sort_values(sortable, kind='stable')
    frame = frame.reset_index(drop=True)

    if write:
        # the CSV is the deliverable and is written first
        frame.to_csv(directory / f'{RESULTS_STEM}.csv', index=False)
        _write_parquet(frame, directory)

    return frame


def _write_parquet(frame: pd.DataFrame, run_dir: Path) -> bool:
    """Write 'results.parquet' beside the CSV when an engine is installed.

    Parquet is just a convenience, so a missing engine is not a warning.

    Arguments:
        frame: the collected results.
        run_dir: the run directory.

    Returns:
        True if the file was written.

    """
    if not any(importlib.util.find_spec(engine) for engine in PARQUET_ENGINES):
        return False

    # a column of lists has no Parquet representation; record it as text rather than fail
    parquet = frame.copy()
    for column in parquet.columns:
        if parquet[column].map(lambda value: isinstance(value, list)).any():
            parquet[column] = parquet[column].astype(str)
    try:
        parquet.to_parquet(run_dir / f'{RESULTS_STEM}.parquet', index=False)
    except (ImportError, ValueError) as error:  # an engine is installed but cannot take this frame
        print(f'note: parquet skipped ({error}), the CSV was still written')
        return False
    return True


def run_status(run_dir: Path | str) -> dict[str, float]:
    """Report how much of a planned sweep has finished.

    Arguments:
        run_dir: the run directory.

    Returns:
        Counts, percentage complete, and the runtime seen so far.

    """
    directory = Path(run_dir)
    manifest = Manifest.load(directory)
    records = read_parts(directory) if (directory / PARTS_DIR).exists() else []

    done = len({record['combination_id'] for record in records if 'combination_id' in record})
    runtimes = [record['runtime_seconds'] for record in records if 'runtime_seconds' in record]
    planned = manifest.n_combinations

    return {
        'planned': planned,
        'completed': done,
        'remaining': planned - done,
        'percent': round(100 * done / planned, 1) if planned else 0.0,
        'mean_runtime_seconds': round(sum(runtimes) / len(runtimes), 2) if runtimes else 0.0,
        'total_compute_seconds': round(sum(runtimes), 1),
    }
