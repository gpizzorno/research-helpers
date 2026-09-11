# Research Helpers

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Language-Python-blue.svg)](https://www.python.org)
[![Tests](https://github.com/gpizzorno/research-helpers/actions/workflows/tests.yml/badge.svg)](https://github.com/gpizzorno/research-helpers/actions/workflows/tests.yml)
[![Documentation](https://img.shields.io/badge/Docs-latest-blue.svg)](https://gpizzorno.github.io/research-helpers/)

**Research Helpers** is a set of utilities for managing code-intensive research projects and their accompanying papers. 
Includes shared figure styling, LaTeX table generation and rendering, a build pipeline that keeps 
a paper's generated tables and figures from drifting out of date, submission packaging for [arXiv](https://arxiv.org)
and [Zenodo](https://zenodo.org), structured logging, and a parameter-sweep engine for [scheduler](https://slurm.schedmd.com/overview.html) job arrays.

[Read the documentation](https://gpizzorno.github.io/research-helpers/)

## Features

- **Generated Tables and Figures**: Build the paper's tables and figures from the repository's own data
- **Drift Detection**: Detect when the paper and the data differ
- **LaTeX Assembly**: Compose tables for LaTeX and also display them in Jupyter
- **Shared Figure Styling**: Consistent look across LaTeX and Jupyter
- **Submission Packaging**: Automatic preparation and pre-checking for arXiv and Zenodo
- **Parameter Sweeps**: Plan a grid once, run it as a scheduler job array, resume if necessary, and collect the results
- **Structured Logging**: Console and file output at separate levels, with progress bars and colour output

## Installation

The core package has no third-party dependencies. Capabilities are installed as extras:

```sh
pip install research-helpers[figures]   # matplotlib, seaborn
pip install research-helpers[latex]     # LaTeX table assembly and rendering (stdlib only)
pip install research-helpers[log]       # structlog, colorama, tqdm
pip install research-helpers[sweep]     # pandas, pyarrow (planning and running need neither)
```

Requires Python 3.11 or newer.

## Quick Start

### Wire up the project

A project's wiring—*i.e.*, where the paper lives, how wide it is, where runs are written—goes in the
`[tool.research-helpers]` section of the `pyproject.toml` file.

```toml
[tool.research-helpers.paper]
main = "tex/paper.tex"
tables-dir = "tex/tables"
figures-dir = "tex/figures"
text-width-pt = 468.0 # straight from \showthe\textwidth

[tool.research-helpers.figures]
profile = "print"
palette = "colorblind"
dpi = 300
```

`research-helpers doctor` shows every setting, the value in force, and where it came from.

Keys and values are described in the [configuration reference](https://gpizzorno.github.io/research-helpers/configuration.html).

### Generate a table from data

```python
import json

from research_helpers.build import TABLES, Registry
from research_helpers.latex import half_up, header, table

tables = Registry(TABLES)


@tables.register('tab:scores')
def scores() -> str:
    """Accuracy on the held-out set."""
    data = json.loads(SCORES_PATH.read_text())
    return table(
        spec='lr',
        header_rows=[[header('System'), header('Accuracy')]],
        body_rows=[[name.title(), half_up(v['accuracy'] * 100)] for name, v in data.items()],
        caption='Accuracy on the held-out set.',
        label='tab:scores',
    )


if __name__ == '__main__':
    raise SystemExit(tables.main())
```

The label names the file, so this is written to `scores.tex` and the paper reads it with
`\input{tables/scores}`:

```console
$ python -m demo.tables --install
wrote build/tables/scores.tex
installed tex/tables/scores.tex
```

### Check for drift

```console
$ python -m demo.tables --check
OK: all 1 tables in the paper are current
```

If the data is changed without rebuilding, the check fails:

```console
$ python -m demo.tables --check
stale, the paper is behind the data: tab:scores
to fix: rebuild and install the tables
$ echo $?
1
```

For a full example, see [adding a generated table](https://gpizzorno.github.io/research-helpers/guide/generated-table.html).

### Style a figure for the page

```python
import matplotlib.pyplot as plt

from research_helpers.figures import apply_style, save

apply_style(profile='print')  # \textwidth across, paper font sizes
fig, ax = plt.subplots()  # the profile's size is already in rcParams
ax.plot(iterations, accuracy, marker='o')
save(fig, 'tex/figures/learning-curve.png')
```

See details in the [figures guide](https://gpizzorno.github.io/research-helpers/guide/figures.html).

### Run a parameter sweep

```python
from research_helpers.sweep import Sweep

sweep = Sweep()


@sweep.context
def prepare(manifest, run_dir):
    """Loaded once per array task."""
    return load_corpus(manifest.metadata['corpus'])


@sweep.evaluate
def evaluate(params, corpus):
    """One parameter combination."""
    return {'f1': score(corpus, **params)}


if __name__ == '__main__':
    raise SystemExit(sweep.main())
```

```console
$ python sweep_demo.py plan --config sweep.toml --run-dir runs/demo --tasks 4
planned 12 combinations over 4 array tasks (~3 per task)
manifest: runs/demo/manifest.json

submit with:
  sbatch --array=1-4 <your sbatch script> runs/demo
```

The manifest is written once and the tasks read it, so re-submitting the two that were killed
reproduces exactly their original slices instead of repartitioning the grid. Resumption is per
combination, not per task, so a job that hits its walltime keeps everything it finished.
`status` and `run` need only the standard library, so nothing needs to be installed to run a 
progress check from a login node.

Full details are discussed in the [sweeps guide](https://gpizzorno.github.io/research-helpers/guide/sweeps.html).

### Package a submission

```console
$ research-helpers arxiv --dry-run
  paper.tex                       43.1 KB
  paper.bbl                       82.1 KB
  tables/scores.tex                0.3 KB
  figures/learning-curve.png      66.3 KB

  4 files, 0.19 MB
  bbl format 3.3 (TeX Live 2025)

ready to upload: select xelatex and TeX Live 2025

(dry run, nothing written)
```

The target files are keyed by the path they take *inside* the submission, so what resolves locally 
will also resolve at the destination. The checks cover filenames arXiv rejects, a `.bbl` that is missing, 
stale, or in a format the selected TeX Live will not read, and `microtype` font expansion under an engine 
that has none. `--tar` packs it reproducibly, so re-packing an unchanged submission gives an identical
file.

See the [submission guide](https://gpizzorno.github.io/research-helpers/guide/submission.html).

### Logging

```python
from research_helpers.log import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)

log.info('scoring', corpus='perseus', sentences=18_000)
```

```console
[INFO    ] 19:41:47 __main__ scoring (corpus=perseus, sentences=18000)
```

The console and the log file take separate levels. Colour is applied only when the stream is a terminal, 
so no escape codes are included in a redirected log.

Details in the [logging guide](https://gpizzorno.github.io/research-helpers/guide/logging.html).

## Documentation

The full documentation includes:

- **[Configuration](https://gpizzorno.github.io/research-helpers/configuration.html)**: Every section, key, type, and default, plus units and settings resolution
- **[Guides](https://gpizzorno.github.io/research-helpers/guide/index.html)**: Task-focused walkthroughs
  - [Adding a generated table](https://gpizzorno.github.io/research-helpers/guide/generated-table.html): Full table pipeline
  - [Figures](https://gpizzorno.github.io/research-helpers/guide/figures.html): Profiles, scoped styling, saving versus rendering
  - [LaTeX tables](https://gpizzorno.github.io/research-helpers/guide/tables.html): Assembling tables and reading them back
  - [Parameter sweeps](https://gpizzorno.github.io/research-helpers/guide/sweeps.html): Planning, running, resuming, and collecting
  - [arXiv and Zenodo](https://gpizzorno.github.io/research-helpers/guide/submission.html): Submission checks and reproducible archives
  - [Logging](https://gpizzorno.github.io/research-helpers/guide/logging.html): Setup, levels, colour, and progress bars
- **[API Reference](https://gpizzorno.github.io/research-helpers/api/index.html)**: Complete API documentation

## License

The project is licensed under the [MIT License](LICENSE), allowing free use, modification, and distribution.
