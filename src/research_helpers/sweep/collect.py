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


def collect_results(
    run_dir: Path | str,
    *,
    write: bool = True,
    leading: Iterable[str] = (),
) -> pd.DataFrame:
    """Merge the part files into a table de-duplicating by combination id.

    Duplicates are legitimate: a requeued task can recompute a combination whose result was
    already flushed. The last record written wins.

    Arguments:
        run_dir: the run directory.
        write: also write 'results.csv', and 'results.parquet' where pyarrow allows it.
        leading: columns to move to the front, e.g. the swept parameters, so the table reads
            configuration first and measurements second.

    Returns:
        One row per combination.

    """
    import pandas as pd  # noqa: PLC0415 -- only this function needs pandas

    directory = Path(run_dir)
    records = read_parts(directory)
    if not records:
        return pd.DataFrame()

    frame = pd.DataFrame(records)
    if 'combination_id' in frame:
        frame = frame.drop_duplicates(subset='combination_id', keep='last')

    front = [column for column in leading if column in frame.columns]
    frame = frame[front + [column for column in frame.columns if column not in front]]

    # sort on scalar columns only: a parameter holding a list cannot be factorized, and the id
    # carries no ordering meaning
    sortable = [
        column
        for column in front
        if column != 'combination_id' and not frame[column].map(lambda value: isinstance(value, list)).any()
    ]
    if sortable:
        frame = frame.sort_values(sortable, kind='stable')
    frame = frame.reset_index(drop=True)

    if write:
        frame.to_csv(directory / f'{RESULTS_STEM}.csv', index=False)
        # a column of lists has no Parquet representation
        # record it as text rather than fail
        parquet = frame.copy()
        for column in parquet.columns:
            if parquet[column].map(lambda value: isinstance(value, list)).any():
                parquet[column] = parquet[column].astype(str)
        try:
            parquet.to_parquet(directory / f'{RESULTS_STEM}.parquet', index=False)
        except (ImportError, ValueError) as error:
            print(f'warning: could not write parquet ({error}), the CSV was still written')

    return frame


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
