# Cluster jobs

Three `sbatch` templates ship with the package. Copy one out with:

```sh
cp "$(python -c 'from importlib.resources import files; print(files("research_helpers")/"templates"/"sweep.sbatch")')" .
```

| Template | Description |
| --- | --- |
| `sweep.sbatch` | Runs one array task per slice of a planned grid. See [parameter sweeps](sweeps.md). |
| `job.sbatch` | Runs one script as a single job. |
| `diagnose-env.sbatch` | Diagnostics for when a job cannot find the interpreter. |

Each has an `EDIT THIS BLOCK` fence around the parts that require configuration—account, partition, module
loads, environment name.

## What the templates handle

**Thread oversubscription.** Every template sets `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`,
`MKL_NUM_THREADS`, and `NUMEXPR_NUM_THREADS` to the cores the scheduler granted. Without
this, a task granted one core still sees the whole node through BLAS and spawns a thread per core.

**The interpreter.** They call `$CONDA_PREFIX/bin/python` by absolute path rather than trusting
`PATH`. This prevents a common occurrence where after an apparently successful activation the 
`PATH` is wrong and `python` falls through to the base install leading to failed jobs at the 
first third-party import.

## Single jobs

Used to do work that is not a grid: a diagnostic battery over a whole dataset, a one-off scaling 
measurement, a build step too large for a login node. Each job has its own arguments and writes its 
own single output file, so there is nothing for a manifest to describe.

```sh
sbatch job.sbatch scripts/evaluate.py --preset full --out runs/full.json
sbatch -t 0-12:00 --mem-per-cpu=32G job.sbatch scripts/evaluate.py --out runs/big.json
```

Resources are overridden at submit time, so one template covers jobs of any size.

:::{note}
The template also has a commented block for checking the environment *before* the work starts.
:::

## Resubmitting

`sweep.sbatch` takes a sparse array, and slices come from the manifest rather than from the width of
the array submitted, so resubmitting two killed tasks reproduces exactly the slices they had:

```sh
sbatch --array=17,42 sweep.sbatch runs/my-sweep
```

`status` prints that range already collapsed. See [status](sweeps.md#status).
