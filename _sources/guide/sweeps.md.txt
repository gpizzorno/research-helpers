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

`grid` is swept over, while `constants` are passed to every combination unchanged. TOML, JSON, and
YAML are all accepted.

:::{note}
`constants` are part of a combination's identity. Two sweeps over the same grid
with different constants produce different `combination_id`s and cannot collide in a shared
results table.
:::

Two further keys change how a run is recorded rather than what it sweeps:

```toml
tuple_params = ["window"]
artefact_key = "cover"
```

`tuple_params` names parameters whose values are tuples rather than lists. JSON has no tuple, so
without this an evaluation receives a `list` where the planning process passed a `tuple`. 
Declaring a parameter does not change any `combination_id`, so it can be added to a sweep 
that is already part-way through.

`artefact_key` is described under [artefacts](#artefacts).

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

Results are converted to JSON-compatible formats before they are written. Numpy scalars are unwrapped, 
and tuples and sets are recorded as lists, through nested containers:

```python
@sweep.evaluate
def evaluate(params, data):
    return {'f1': np.float64(0.83), 'window': (4, 12)}   # recorded as 0.83 and [4, 12]
```

The conversion function is available as `jsonable` for writing files alongside the parts:

```python
from research_helpers.sweep import jsonable
```

## Status

```console
$ python sweep_demo.py status --run-dir runs/demo
  planned                12
  completed              3
  remaining              9
  percent                25.0
  mean_runtime_seconds   0.01
  total_compute_seconds  0.0
  manifest_n_tasks       4
  unfinished_tasks       2-4

Resubmit the unfinished slices; resuming skips what is already recorded:
  sbatch --array=2-4 <your sbatch script> runs/demo

The range comes from the MANIFEST (n_tasks=4), not from the
config. If the config's task cap changed after this run was planned the two disagree,
and the plan must be re-run to adopt the new value.
```

Standard library only (runs on a login node without anything installed).

An unfinished run names the array indices still holding work, collapsed into the syntax `--array`
takes. A task counts as unfinished if *any* combination in its slice is missing, so a task
killed by the walltime part-way through comes back and resumes where it stopped.

The width matters as much as the range. Slices come from the manifest, not from the width of the
array submitted, so an array narrower than the manifest plans leaves the tail simply unrun: nothing
fails anywhere, and the sweep stops short. That is what happens when a config's `max_tasks` changes
*after* a run directory was planned, which is why `status` prints the width the run actually holds.

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
to put first and a name that is not a column is ignored. Without it the table leads with the run's
own configuration, taken from the manifest: the `id`, then the constants, then the swept
parameters, followed by the measurements.

:::{note} 
The parameters are recorded by the engine. Note `alpha`, `beta`, and `tolerance` in the table above even 
though `evaluate` returns only `objective` and `seeds`. The runner merges the combination's parameters 
into the record, so a table of results can be read on its own without joining it back to the manifest 
by `id`.
:::

## Artefacts

Some evaluations produce objects too large for a results row—*e.g.*, a community cover, a fitted model, or a
per-item prediction dump. Returning this from `evaluate` puts it in the row, where it makes the table
unreadable and the CSV huge.

If the name of the key it comes back under is provided, the engine moves it out of the row:

```toml
artefact_key = "cover"
```

```python
@sweep.evaluate
def evaluate(params, graph):
    cover = detect(graph, **params)
    return {'n_communities': len(cover), 'modularity': score(graph, cover), 'cover': cover}
```

The row keeps `n_communities` and `modularity`, the cover is written to
`runs/demo/artefacts/<combination_id>.json` and read back with `read_artefact`:

```python
from research_helpers.sweep import read_artefact

cover = read_artefact('runs/demo', '7789d6bcd687')
```

The key is declared on the sweep config rather than passed at run time, so the manifest records that
the run kept them (otherwise a run with no artefacts is indistinguishable from one whose
artefacts were never written). `--artefact-key` overrides it for a single task.

## Aggregating several runs

A benchmark is usually one draw from a family—a subsample of a graph, a synthetic instance, a
split—and the draws differ from each other more than the parameters do. To run the same grid over 
several independent draws and aggregate use:

```python
from research_helpers.sweep import aggregate_runs

frame = aggregate_runs(['runs/sub01', 'runs/sub02', 'runs/sub03', 'runs/sub04', 'runs/sub05'])
```

```text
   alpha  beta  n_runs  objective_mean  objective_ci  objective_sem
     0.1     1       5           4.118         0.214          0.077
     0.1     2       5           4.232         0.187          0.067
```

Each metric gets a mean, the half-width of a 95% interval, and the standard error. The interval uses
Student's *t* rather than the normal approximation (aggregation is over a handful of runs
and at that size the normal understates it). A single run reports `NaN`.

Metrics default to every numeric column that is not a grouping column or engine book-keeping. A
metric missing from one run of several—a measurement added part-way through a series—aggregates over
the runs that have it rather than voiding the row.

Unlike `aggregate_runs`, which needs the `sweep` extra for pandas, the statistic behind it does not:

```python
from research_helpers.sweep import confidence_interval

mean, half_width, error = confidence_interval([0.82, 0.79, 0.88, 0.81, 0.85])
```

`confidence_interval` only requires the standard library, so it works in the same places `plan`, 
`run`, and `status` do. The Student's *t* quantile it needs is computed in the package rather, 
see {mod}`research_helpers.sweep.stats` for details on its accuracy and limits.

## Sizing the array

```console
$ python sweep_demo.py estimate --run-dir runs/demo --samples 4
mean 12.4s/combination over 4 random samples (min 9.8, median 12.1, max 15.6)
  95% confidence interval on the mean: 8.7s to 16.1s
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

The interval shows how well this sample pins the mean, and narrows as `--samples` rises. 
The spread shows how much the grid varies around that mean. A wide spread means 
that no single number describes the grid, regardless of how many samples are taken.

With a factor configured, the projection is included:

```text
projected in-array: ~0.0s/combination at 1.8x contention, ~0.0 compute-hours total
```

## Submitting

Templates for `sbatch` ship with the package, along with the environment diagnostic for when a job
fails before it reaches the code. See [cluster jobs](cluster.md).
