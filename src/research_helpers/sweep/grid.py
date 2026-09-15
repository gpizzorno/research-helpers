"""Expand a parameter grid and the manifest that records a planned sweep."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

__all__ = ['MANIFEST_NAME', 'Manifest', 'combination_id', 'expand_grid', 'slice_bounds']

MANIFEST_NAME = 'manifest.json'

# long enough to make a collision implausible across any grid that fits on a cluster
# short enough to read in a log line
ID_LENGTH = 12


def _canonical(params: dict[str, Any]) -> str:
    """Render parameters to a stable string."""
    return json.dumps(params, sort_keys=True, default=list)


def combination_id(params: dict[str, Any]) -> str:
    """Return a short, stable id for a parameter combination.

    Derived from the values alone, so the same combination keeps the same id however the grid was
    expanded and on whichever machine.

    Arguments:
        params: the parameter values, excluding any id already assigned.

    Returns:
        Twelve hex characters.

    """
    return hashlib.sha1(_canonical(params).encode(), usedforsecurity=False).hexdigest()[:ID_LENGTH]


def expand_grid(grid: dict[str, list[Any]], constants: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Expand a parameter grid into the full Cartesian product of combinations.

    Arguments:
        grid: parameter name to the list of values to sweep.
        constants: fixed values added to every combination before it is hashed, e.g. the label of
            the dataset being swept. Part of the identity, so two datasets do not collide.

    Returns:
        One dict per combination, each carrying the constants and a 'combination_id'. Ordering is
        deterministic: parameter names sorted, values in the order given.

    Raises:
        ValueError: if the grid is empty.

    """
    if not grid:
        msg = 'the parameter grid is empty'
        raise ValueError(msg)

    names = sorted(grid)
    combinations = []
    for values in product(*(grid[name] for name in names)):
        params: dict[str, Any] = dict(zip(names, values, strict=True))
        params.update(constants or {})
        params['combination_id'] = combination_id(params)
        combinations.append(params)
    return combinations


def slice_bounds(n_items: int, n_tasks: int, task_index: int) -> tuple[int, int]:
    """Return the [start, end) slice of items belonging to a 1-based array task.

    Arguments:
        n_items: total number of combinations.
        n_tasks: number of array tasks the sweep was planned for.
        task_index: 1-based task index.

    Returns:
        Start and end indices into the combination list.

    Raises:
        ValueError: if 'task_index' is outside 1..n_tasks.

    """
    if not 1 <= task_index <= n_tasks:
        msg = f'task index {task_index} is outside 1..{n_tasks}'
        raise ValueError(msg)

    base, remainder = divmod(n_items, n_tasks)
    zero_based = task_index - 1
    start = zero_based * base + min(zero_based, remainder)
    end = start + base + (1 if zero_based < remainder else 0)
    return start, end


@dataclass
class Manifest:
    """The full description of a planned sweep, written once and read by every task."""

    grid: dict[str, list[Any]]
    combinations: list[dict[str, Any]]
    n_tasks: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)  # e.g. a dataset name, a seed count, options
    notes: str = ''
    constants: dict[str, Any] = field(default_factory=dict)  # the fixed values folded into every combination
    tuple_params: list[str] = field(default_factory=list)  # parameters whose values are tuples, not lists
    artefact_key: str | None = None

    @property
    def n_combinations(self) -> int:
        """Return how many parameter combinations the sweep covers."""
        return len(self.combinations)

    def save(self, run_dir: Path | str) -> Path:
        """Write the manifest into 'run_dir' and return the path."""
        directory = Path(run_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / MANIFEST_NAME
        path.write_text(json.dumps(asdict(self), indent=2, default=list), encoding='utf-8')
        return path

    @classmethod
    def load(cls, run_dir: Path | str) -> Manifest:
        """Read the manifest from 'run_dir'.

        Raises:
            FileNotFoundError: if the sweep has not been planned.

        """
        path = Path(run_dir) / MANIFEST_NAME
        if not path.exists():
            msg = f'no manifest at {path}. Plan the sweep first'
            raise FileNotFoundError(msg)
        manifest = cls(**json.loads(path.read_text(encoding='utf-8')))
        for combination in manifest.combinations:
            restore_tuples(combination, manifest.tuple_params)
        return manifest
