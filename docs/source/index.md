# Research Helpers Documentation

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Language-Python-blue.svg)](https://www.python.org)
[![Tests](https://github.com/gpizzorno/research-helpers/actions/workflows/tests.yml/badge.svg)](https://github.com/gpizzorno/research-helpers/actions/workflows/tests.yml)

A set of utilities for managing code-intensive research projects and their accompanying papers. 
Includes shared figure styling, LaTeX table generation and rendering, a build pipeline that keeps 
a paper's generated tables and figures from drifting out of date, submission packaging for [arXiv](https://arxiv.org)
and [Zenodo](https://zenodo.org), structured logging, and a parameter-sweep engine for [scheduler](https://slurm.schedmd.com/overview.html) job arrays.

## Install

The core package has no third-party dependencies. Additional capabilities are installed as extras:

```sh
pip install research-helpers[figures]   # matplotlib, seaborn
pip install research-helpers[latex]     # LaTeX table assembly and rendering (stdlib only)
pip install research-helpers[log]       # structlog, colorama, tqdm
pip install research-helpers[sweep]     # pandas, pyarrow (planning and running need neither)
```

Requires Python 3.11 or newer ({py:mod}`tomllib` is needed to read the project's wiring).

## Where to start

- **Wiring up a project** — [Configuration](configuration.md) includes the full reference for `[tool.research-helpers]`.
- **See it work** — [Adding a generated table](guide/generated-table.md) takes one table from a JSON file to a drift check in CI.

```{toctree}
:maxdepth: 2
:caption: Documentation

configuration
guide/index
api/index
```
