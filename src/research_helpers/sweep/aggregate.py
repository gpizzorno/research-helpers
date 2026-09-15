"""Combine several runs of the same grid into one table with confidence intervals.

Grouping is by the parameters, never by 'combination_id'. The id hashes the constants along with
the parameters, which is what stops two datasets colliding in a shared results table—and means
the same parameter setting carries a *different* id in every run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from research_helpers.sweep.collect import read_parts
from research_helpers.sweep.grid import Manifest
from research_helpers.sweep.stats import confidence_interval

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import pandas as pd

__all__ = ['aggregate_runs']

# recorded by the engine, so never aggregated as a metric.
BOOKKEEPING = ('combination_id', 'task_index')


def _metric_columns(frame: pd.DataFrame, group_by: Sequence[str]) -> list[str]:
    """Return the numeric columns that are measurements rather than configuration."""
    import pandas as pd  # noqa: PLC0415

    excluded = {*group_by, *BOOKKEEPING}
    return [
        column for column in frame.columns if column not in excluded and pd.api.types.is_numeric_dtype(frame[column])
    ]


def aggregate_runs(
    run_dirs: Iterable[Path | str],
    *,
    group_by: Sequence[str] | None = None,
    metrics: Sequence[str] | None = None,
    confidence: float = 0.95,
) -> pd.DataFrame:
    """Combine the results of several runs of one grid, with a confidence interval per metric.

    Arguments:
        run_dirs: the run directories, one per independent draw.
        group_by: the columns identifying a parameter setting across runs. Defaults to the swept
            parameter names on the first run's manifest.
        metrics: the measurements to aggregate. Defaults to every numeric column that is not a
            grouping column or engine bookkeeping.
        confidence: the two-sided confidence level.

    Returns:
        One row per parameter setting, carrying 'n_runs' and, for each metric, its mean, the
        half-width of the interval, and the standard error.

    Raises:
        ValueError: if no run directories were given, if they share no parameter setting, or if
            'group_by' contains 'combination_id'.

    """
    import pandas as pd  # noqa: PLC0415

    directories = [Path(directory) for directory in run_dirs]
    if not directories:
        msg = 'no run directories given'
        raise ValueError(msg)

    if group_by is None:
        group_by = sorted(Manifest.load(directories[0]).grid)
    if 'combination_id' in group_by:
        msg = (
            "group by the parameters, not 'combination_id': the id hashes the constants too, so "
            'the same setting carries a different id in every run and each group would hold one '
            "observation. Pass the swept parameter names, or omit 'group_by' to read them from the "
            'manifest.'
        )
        raise ValueError(msg)

    frames = []
    for directory in directories:
        records = read_parts(directory)
        if records:
            frame = pd.DataFrame(records)
            frame['run_dir'] = str(directory)
            frames.append(frame)
    if not frames:
        msg = f'none of the {len(directories)} run directories hold any results yet'
        raise ValueError(msg)

    combined = pd.concat(frames, ignore_index=True)
    missing = [column for column in group_by if column not in combined.columns]
    if missing:
        msg = f'no column {missing} in the results, the runs may not share a grid'
        raise ValueError(msg)

    chosen = list(metrics) if metrics is not None else _metric_columns(combined, group_by)
    chosen = [column for column in chosen if column in combined.columns]

    rows: list[dict[str, Any]] = []
    # sort=False keeps the grid's own ordering
    for setting, group in combined.groupby(list(group_by), sort=False, dropna=False):
        values = setting if isinstance(setting, tuple) else (setting,)
        row: dict[str, Any] = dict(zip(group_by, values, strict=True))
        row['n_runs'] = group['run_dir'].nunique()
        for metric in chosen:
            interval = confidence_interval(group[metric].tolist(), confidence)
            row[f'{metric}_mean'] = interval.mean
            row[f'{metric}_ci'] = interval.half_width
            row[f'{metric}_sem'] = interval.standard_error
        rows.append(row)

    return pd.DataFrame(rows)
