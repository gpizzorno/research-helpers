"""Interface for running parameter sweeps as scheduler job arrays and collecting the results."""

from research_helpers.sweep.aggregate import aggregate_runs
from research_helpers.sweep.collect import (
    array_spec,
    collect_results,
    leading_columns,
    missing_task_indices,
    read_parts,
    run_status,
)
from research_helpers.sweep.grid import (
    MANIFEST_NAME,
    Manifest,
    combination_id,
    expand_grid,
    restore_tuples,
    slice_bounds,
)
from research_helpers.sweep.runner import (
    ARTEFACTS_DIR,
    PARTS_DIR,
    artefact_path,
    completed_ids,
    jsonable,
    read_artefact,
    run_slice,
    task_index_from_env,
)
from research_helpers.sweep.stats import Interval, confidence_interval, student_t_quantile
from research_helpers.sweep.sweep import Sweep, estimate_runtime, read_config

__all__ = [
    'ARTEFACTS_DIR',
    'MANIFEST_NAME',
    'PARTS_DIR',
    'Interval',
    'Manifest',
    'Sweep',
    'aggregate_runs',
    'array_spec',
    'artefact_path',
    'collect_results',
    'combination_id',
    'completed_ids',
    'confidence_interval',
    'estimate_runtime',
    'expand_grid',
    'jsonable',
    'leading_columns',
    'missing_task_indices',
    'read_artefact',
    'read_config',
    'read_parts',
    'restore_tuples',
    'run_slice',
    'run_status',
    'slice_bounds',
    'student_t_quantile',
    'task_index_from_env',
]
