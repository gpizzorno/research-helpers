# Many sweeps through few arrays

A [sweep](sweeps.md) is one run directory, one manifest, and one array. This approach doesn't necessarily 
scale well to a full campaign that may contain hundreds of them, since one array per sweep can quickly 
reach the scheduler's per-user job limit.

{py:mod}`research_helpers.sweep.queue` decouples sweeps from arrays. The unit of work becomes a *slice* 
of a sweep (*i.e.*, what a single array task effectively runs). A *queue* is a text file of such units, 
and each element of one array runs a block of them, in sequence. Nothing about a sweep changes: every 
slice still writes its own part file into its own run directory, resuming still skips finished combinations, 
and `status` and `collect` read each run directory as normal.

The commands below are on every {py:class}`~research_helpers.sweep.Sweep`'s command line, so the
`sweep_demo.py` from the [sweeps guide](sweeps.md) has them already.

## Plan the campaign

A *plan list* names each sweep's config and run directory, one tab-separated pair per line, with
blank lines and `#` comments allowed:

```text
configs/g01-fast.toml	runs/g01-fast
configs/g01-slow.toml	runs/g01-slow
configs/g02-fast.toml	runs/g02-fast
...
```

`plan-list` plans all of them in one process.

```bash
$ python sweep_demo.py plan-list --list PLAN.tsv
planned 6 sweeps: 24 combinations in 12 slices
queue them with the queue command, rather than submitting one array per sweep
```

## Write the queue

```bash
$ python sweep_demo.py queue --run-dir 'runs/*' --where method=slow --out queues/slow --per-task 3
3 sweeps, 6 units, 3 per array element, 1 queue file(s)

submit with:
  sbatch --array=1-2 <your queue script> queues/slow.01.units 3
```

Each line of the file is one unit, a run directory, and a slice index:

```bash
$ head -3 queues/slow.01.units
runs/g01-slow	1
runs/g01-slow	2
runs/g02-slow	1
```

- **Naming sweeps.** `--run-dir` takes paths and quoted globs, expanded by the command rather than
  the shell, so thousands of run directories can fit in a single argument. `--list` takes plan lists instead.
- **Splitting a campaign.** Slices of different kinds can differ in cost by an order of magnitude, so
  queue them separately, each with its own block size and wall-time. `--where KEY=VALUE` keeps the
  sweeps whose manifest records that value, in its `metadata` or its `constants`, and
  `--where-not KEY=VALUE` drops them. Both repeat.
- **Block size.** `--per-task` is how many units each element runs. It is part of the queue: element
  *i* runs lines (*i* − 1)·K + 1 to *i*·K, so submit with the same number `queue` printed.
- **Array width.** A queue longer than one array allows is split across several files, each printed
  with its own `sbatch` line. The width comes from `max-array` under
  [`[tool.research-helpers.sweep]`](../configuration.md#sweep), 1,000 by default, or `--max-array`.
- **Mixing.** `--shuffle SEED` puts the units in a seeded random order, so each element's block is
  a sample of the whole campaign. Element wall-times then gather around the mean instead of
  inheriting the slowest sweep's. The same seed always gives the same queue.

## Run it

Copy `queue.sbatch` out of the package ([cluster jobs](cluster.md)), set its `SWEEP_MODULE`, and
submit the line `queue` printed. Each element calls `run-units`, which runs its block:

```bash
$ python sweep_demo.py run-units --units queues/slow.01.units --per-task 3 --element 1
element 1: 3 unit(s) from queues/slow.01.units

=== runs/g01-slow task 1 ===
[task 1/2] combinations 0..1 (2 assigned, 0 already done, 2 to run)
[task 1] 1/2 5024202ad27b in 0.0s
[task 1] 2/2 7bc25422bde8 in 0.0s
wrote runs/g01-slow/parts/task-00001.jsonl
...
```

Under the scheduler the element comes from `SLURM_ARRAY_TASK_ID`, as a task's index does for
`run`. A unit that raises is reported and the rest of the block still runs. The element then 
exits non-zero, which the scheduler records as a failure.

The `@sweep.context` factory runs once per *unit*, never once per element to avoid a shared 
context carrying one slice's state into another's results.

## Resume

`status` takes globs too, and reports one line per sweep:

```bash
$ python sweep_demo.py status --run-dir 'runs/*-slow'
  runs/g01-slow  4/4  100.0%
  runs/g02-slow  2/4   50.0%  unfinished slices 2
  runs/g03-slow  0/4    0.0%  unfinished slices 1-2

1 of 3 sweeps finished
queue the unfinished slices with queue --pending, under a new --out
```

`--pending` queues only the slices that still hold an unfinished combination. Each unit names a slice
by the index its manifest planned, so nothing is re-partitioned and the resumed queue runs exactly
the slices that are missing.

```bash
$ python sweep_demo.py queue --run-dir 'runs/*-slow' --out queues/slow_r1 --per-task 3 --pending
3 sweeps, 3 pending units, 3 per array element, 1 queue file(s)

submit with:
  sbatch --array=1-1 <your queue script> queues/slow_r1.01.units 3
```

:::{warning}
Write a resumed queue under a **new** stem, and only once the old array has finished. An element
reads its block from the file when it *starts*, so rewriting a queue that still has pending elements
hands them another queue's blocks, meaning that some slices would run twice, while others would never run. 
`queue` refuses to overwrite an existing queue unless given `--force`:

```bash
$ python sweep_demo.py queue --run-dir 'runs/*-slow' --out queues/slow --per-task 3
queues/slow.01.units exists. Give this queue a new stem (e.g. slow_r1), or rewrite it with --force (force=True) only once no array is still reading it
```
:::

`collect` over many sweeps collects each one, and exits non-zero if any has no results yet.

## Elements that ran twice

When a node stops answering, a scheduler can re-queue an element while the original is still running.
The block then runs twice, from two nodes, both appending to the same part files, and on network
storage that leaves runs of NUL bytes and lines spliced together. The damage is not confined to the
lines `collect` reports as malformed since a valid line written after the NULs is linked to them, and a
resumed task appends its new line to the damaged file, also linked, so the slice never
finishes.

Both array templates set `--no-requeue` to prevent this. If it happens anyway, set the elements'
results aside whole, part files and artefacts, and queue them again:

```bash
$ python sweep_demo.py quarantine --units queues/slow.01.units --per-task 3 --elements 1
1 element(s) of queues/slow.01.units: 3 units, 3 part files, 0 damaged part files, 0 artefacts
nothing changed. With --apply, the part files and artefacts are renamed *.quarantined
```

Without `--apply`, the command only counts. With `--apply`, every file is renamed with a `.quarantined` 
suffix and `queue --pending` then finds the slices missing. Recomputing them reproduces the lost results 
only as far as the evaluation is deterministic, so rerun them on the same kind of node as the rest of 
the campaign.
