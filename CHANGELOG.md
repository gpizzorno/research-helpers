# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-09-15

### Added

- **`sweep`: resubmission guidance.** `status` on an unfinished run now names the array indices that
  still hold work, collapsed into the syntax `--array` takes, alongside the width the run was planned
  at. New: `missing_task_indices` and `array_spec`.
- **`sweep`: artefacts.** An evaluation can return output too large for a results row under a key named 
  by `artefact_key`, and it is written to `artefacts/<combination_id>.json` instead of into the row. 
  The key is declared on the sweep so the manifest records that the run kept them. New: `read_artefact` 
  and `artefact_path`.
- **`sweep`: tuple parameters.** `tuple_params` declares parameters whose values are tuples rather
  than lists, so the type survives the round trip through the manifest's JSON. New: `restore_tuples`.
- **`sweep`: YAML configs.** `read_config` reads `.yaml` and `.yml` through `pyyaml` where it is
  installed.
- **`sweep`: default column order.** `collect_results` without `leading` now leads with the run's own
  configuration, read from the manifest. Manifests record `constants` for this. Previously the caller 
  had to name the columns or read an unordered table.
- **`sweep`: confidence intervals.** `aggregate_runs` combines several runs of one grid into a table
  carrying, per metric, a mean, a Student's *t* interval and a standard error.
- **`sweep.stats`**: `confidence_interval` and `student_t_quantile`, with **no dependencies**. The
  quantile is computed in the package—regularized incomplete beta by continued fraction, inverted by
  bisection. Tested against `scipy.stats.t.ppf`: worst relative error 2e-11 across the confidence 
  levels an interval reaches. `scipy` is in the `dev` extra as a test oracle and is not a runtime 
  dependency.
- **`job.sbatch`** template for single jobs (i.e. not grids).
- **`diagnose-env.sbatch`** template: captures the batch environment before and after activation, to
  tell an inherited `CONDA_PREFIX` apart from an environment that is genuinely incomplete.

### Changed

- **`sweep`: a missing Parquet engine is no longer a warning.** `collect_results` checks for one
  rather than catching the failure.
- **`sweep.sbatch`** now names both causes of a missing interpreter in its failure message, points at
  `diagnose-env.sbatch`, mentions `status` for the resubmission range, and honours `SWEEP_TASKS` for
  a deliberate re-partition.

## [1.0.0] — 2026-09-11

First public release.

The package was generalized out of three research projects that had each grown their own copy of
the same utilities.

### The idea

`research-helpers` reads a project's **wiring**—*i.e., where the paper lives, how wide it is, where
sweep runs are written—and nothing else. Research parameters stay in the project that owns
them. This wiring lives in one `[tool.research-helpers]` section of a project's `pyproject.toml`, 
which is also the project-root marker, so finding the configuration and finding the root are one
operation. Every setting has a working default, and every entry point is callable with plain
arguments and no project file at all.

### Added

- **`build`** — a registry of generated artefacts with three-way drift detection: a table the
  paper is behind on, one that is generated but never pulled in, and one typed by hand with no
  emitter behind it. `--check` exits non-zero, so "every number in the paper is generated from
  data in the repository, and is current" becomes a build status.
- **`latex`** — table assembly with the conventions a paper needs: half-up rounding, escaping 
  for text arriving from data, en-dashes for ranges, em-dashes for empty cells.
- **`display`** — parse a generated `.tex` table back into rows, spans and alignment, for reading
  in a notebook or asserting on in a test.
- **`figures`** — one matplotlib look across a project, and a `print` profile that sizes a figure
  to the document it is going into, so it renders in the paper at 1:1 with body-text-sized labels.
- **`arxiv`** — inventory a submission keyed by the paths it takes *inside* the upload, and check
  it against the engine and TeX Live year it will build under: filenames arXiv rejects, a `.bbl`
  that is missing, stale or in the wrong `biblatex` format, and `microtype` font expansion under an
  engine that has none.
- **`archive`** — byte-reproducible tarballs. Pinned `mtimes`, `uid`, and `gid`, normalised modes,
  sorted members, and an emptied gzip filename field, so a published checksum means something.
- **`sweep`** — plan a parameter grid once, run it as a scheduler job array, resume what was
  killed, collect the parts into one table. Resumption is per combination rather than per task,
  the manifest is written once so a sparse resubmission reproduces its original slices, and
  planning, running and status need only the standard library.
- **`log`** — *structlog* over the standard library, with separate console and file levels, colour
  only when the stream is a terminal, and progress bars that do not fight the log.
- **`research-helpers` CLI** — `doctor` prints every setting, the value in force and where it came
  from; `arxiv` assembles, checks, packs and previews a submission.
- Lengths may be written in inches, millimetres, centimetres, or TeX points by changing a key's
  suffix: `text-width-pt = 468.0` is what `\showthe\textwidth` prints, copied across with no
  arithmetic in between.
- Full documentation at <https://gpizzorno.github.io/research-helpers/>.

### Notes for packagers

- Requires Python 3.11 or newer.
- **The core package has no third-party dependencies.** Capabilities are opt-in extras:
  `figures` (matplotlib, seaborn), `log` (structlog, colorama, tqdm), `sweep` (pandas, pyarrow),
  and `latex`, which is standard library only and exists, so the capability is discoverable.
  Importing `research_helpers` pulls in none of them.
- The package ships a `py.typed` marker, so annotations are visible to type checkers.

### Verified

- 276 tests, 97% coverage, run against Python 3.11, 3.12, and 3.13 in CI.
- The documentation builds with warnings as errors.

[1.0.0]: https://github.com/gpizzorno/research-helpers/releases/tag/v1.0.0
