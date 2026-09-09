"""Interface for running parameter sweeps as scheduler job arrays and collecting the results."""

from research_helpers.sweep.collect import collect_results, read_parts, run_status
from research_helpers.sweep.grid import (
    MANIFEST_NAME,
    Manifest,
    combination_id,
    expand_grid,
    slice_bounds,
)
from research_helpers.sweep.runner import PARTS_DIR, completed_ids, run_slice, task_index_from_env
from research_helpers.sweep.sweep import Sweep, estimate_runtime, read_config

__all__ = [
    'MANIFEST_NAME',
    'PARTS_DIR',
    'Manifest',
    'Sweep',
    'collect_results',
    'combination_id',
    'completed_ids',
    'estimate_runtime',
    'expand_grid',
    'read_config',
    'read_parts',
    'run_slice',
    'run_status',
    'slice_bounds',
    'task_index_from_env',
]
