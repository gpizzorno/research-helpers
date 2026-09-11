# Parameter sweeps

{py:mod}`research_helpers.sweep` runs a parameter grid as a scheduler job array. The grid is 
planned once, the array is submitted, each task works on its own slice, and the results are then
collected together.

It fits the shape *one parameter grid, one expensive function, independent tasks*, meaning that it 
is not suitable for tasks that depend on each other, or situations where the grid is generated 
dynamically.

Planning, running, and checking status need only the standard library. The `sweep` extra
(which depends on `pandas` and `pyarrow`) is needed for `collect`, which means a status check 
from a login node does not require any installs.

## Define the sweep

```python
"""A sweep over a toy objective."""

from research_helpers.sweep import Sweep

sweep = Sweep()


@sweep.context
def prepare(manifest, run_dir):
    """Load anything every combination in this task needs, once per task."""
    return {'dataset': manifest.metadata.get('dataset', 'demo')}


@sweep.evaluate
def evaluate(params, context):
    """Score one parameter combination."""
    objective = params['alpha'] * params['beta'] + len(context['dataset'])
    return {'objective': round(objective, 4), 'seeds': 5}


if __name__ == '__main__':
    raise SystemExit(sweep.main())
```

`@sweep.evaluate` is the expensive function: one combination in, a `dict` of measurements out.
`@sweep.context` is optional and runs once per *task* (not once per combination).

## Configure the grid

```toml
notes = "toy objective, alpha x beta"

[metadata]
dataset = "demo"

[grid]
alpha = [0.1, 0.5, 1.0]
beta = [1, 2, 4, 8]

[constants]
tolerance = 1e-6
```

`grid` is swept over, while `constants` are passed to every combination unchanged. Both TOML and JSON
are accepted.

:::{note}
`constants` are part of a combination's identity. Two sweeps over the same grid
with different constants produce different `combination_id`s and cannot collide in a shared
results table.
:::

## Plan

```console
$ python sweep_demo.py plan --config config.toml --run-dir runs/demo --tasks 4
planned 12 combinations over 4 array tasks (~3 per task)
manifest: runs/demo/manifest.json

submit with:
  sbatch --array=1-4 <your sbatch script> runs/demo
```

The manifest is the record of what the run *is*. It holds the grid, every expanded combination
with its `id`, the array width, the metadata, and the notes. It is written once and tasks read it,
nothing recomputes the partition.

That means that if tasks 17 and 42 are killed, and then resubmitted with `--array=17,42`, they 
reproduce exactly the slices they had originally, because the width comes from the manifest rather 
than from the size of the array.

## Run

Each task writes its own part file, so no two tasks write to the same file, and no locking is
needed:

```console
$ python sweep_demo.py run --run-dir runs/demo --task 1
[task 1/4] combinations 0..2 (3 assigned, 0 already done, 3 to run)
[task 1] 1/3 7789d6bcd687 in 0.0s
[task 1] 2/3 3e8101ffc006 in 0.0s
[task 1] 3/3 fcbd23e1d4ff in 0.0s
wrote runs/demo/parts/task-00001.jsonl
```

`--task` is for running manually. Under a scheduler it is read from the environment—`SLURM_ARRAY_TASK_ID`, 
and the SGE, PBS, and LSF equivalents.

If a task that has already finished is resubmitted, it does nothing:

```console
$ python sweep_demo.py run --run-dir runs/demo --task 1
[task 1/4] combinations 0..2 (3 assigned, 3 already done, 0 to run)
```

The ability to resume is per *combination*, not per task, so a task killed by the walltime keeps
everything it had finished. Part files are [JSON Lines](https://jsonlines.org) written one at a 
time and flushed. A truncated final line from a task killed mid-write is skipped on read rather 
than corrupting the output file.

## Status

```console
$ python sweep_demo.py status --run-dir runs/demo
  planned                12
  completed              3
  remaining              9
  percent                25.0
  mean_runtime_seconds   0.01
  total_compute_seconds  0.0
```

Standard library only (runs on a login node with nothing installed).

## Collect

```console
$ python sweep_demo.py collect --run-dir runs/demo --leading combination_id alpha beta objective
collected 12 combinations -> runs/demo/results.csv
combination_id  alpha  beta  objective  tolerance  seeds  task_index  runtime_seconds
  7789d6bcd687    0.1     1        4.1   0.000001      5           1            0.011
  3e8101ffc006    0.1     2        4.2   0.000001      5           1            0.013
  fcbd23e1d4ff    0.1     4        4.4   0.000001      5           1            0.011
  c15e73c315a4    0.1     8        4.8   0.000001      5           2            0.011
```

Duplicate `id`s—e.g., from a task that ran twice—are deduplicated. `--leading` names columns 
to put first and a name that is not a column is ignored.

:::{note} 
The parameters are recorded by the engine. Note `alpha`, `beta`, and `tolerance` in the table above even 
though `evaluate` returns only `objective` and `seeds`. The runner merges the combination's parameters 
into the record, so a table of results can be read on its own without joining it back to the manifest 
by `id`.
:::

## Sizing the array

```console
$ python sweep_demo.py estimate --run-dir runs/demo --samples 4
mean 0.0s/combination over 4 random samples (min 0.0, median 0.0, max 0.0)
estimated serial total: 0.0 compute-hours, measured alone on a node

No contention factor is set, so these numbers are optimistic: a real array puts
many tasks on one node, competing for memory bandwidth, and each combination takes
longer than it does alone. Measure yours by timing the same combinations both ways,
then set contention-factor under [tool.research-helpers.sweep].

per-task wall time:
   100 tasks -> ~1 combinations/task -> 0.00 h
   500 tasks -> ~1 combinations/task -> 0.00 h
  1000 tasks -> ~1 combinations/task -> 0.00 h
```

Samples are drawn at random, not strided. A strided sample through a grid whose first axis is
the expensive one gives a mean that is systematically wrong, and the error does not shrink
with more samples.

With a factor configured, the projection is included:

```text
projected in-array: ~0.0s/combination at 1.8x contention, ~0.0 compute-hours total
```

## Submitting

A template is included with the package:

```sh
cp "$(python -c 'from importlib.resources import files; print(files("research_helpers")/"templates"/"sweep.sbatch")')" .
```

It has an `EDIT THIS BLOCK` fence around the parts that should be customized (i.e., account, partition, module loads) and sets 
`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` to the cores the scheduler actually granted.

