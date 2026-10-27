# Research Helpers Documentation

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Language-Python-blue.svg)](https://www.python.org)
[![Tests](https://github.com/gpizzorno/research-helpers/actions/workflows/tests.yml/badge.svg)](https://github.com/gpizzorno/research-helpers/actions/workflows/tests.yml)

A set of utilities for managing code-intensive research projects and their accompanying papers. 
Includes shared figure styling, LaTeX table generation and rendering, a build pipeline that keeps 
a paper's generated tables and figures from drifting out of date, submission packaging for [arXiv](https://arxiv.org)
and [Zenodo](https://zenodo.org), structured logging, and a parameter-sweep engine for [scheduler](https://slurm.schedmd.com/overview.html) job arrays.

## Install

The core package has no third-party dependencies. Specifically, **the code path that runs on a cluster only depends on the standard library**. 
Planning a sweep, running an array task, checking its status, sizing the array and computing a confidence interval all work on a node
with nothing but Python on it. Everything that needs a library is a capability, installed as an extra:

```sh
pip install research-helpers[figures]   # matplotlib, seaborn
pip install research-helpers[latex]     # LaTeX table assembly and rendering (stdlib only)
pip install research-helpers[log]       # structlog, colorama, tqdm
pip install research-helpers[sweep]     # pandas, pyarrow (planning, running, and intervals need neither)
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
