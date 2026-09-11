# Configuration

A project's wiring goes in the `[tool.research-helpers]` section in the `pyproject.toml` file. 
No keys are required—defaults are provided out-of-the-box—so a new project can be started with
minimal or no configuration.

The keys are written in kebab-case and map to the snake_case attribute of the same name, so
`tables-dir` in TOML is `paper.tables_dir` in Python. An unknown key raises a
{py:class}`~research_helpers.project.ConfigWarning` and is ignored, as does a key with the wrong
value type or with a value outside the allowed set.

:::{note}
Wiring lives in `pyproject.toml` because that file is *also* the project-root marker. 
Finding the configuration and finding the root are therefore one operation, and every 
path in the configuration is resolved relative to the directory containing it.
:::

## Three layers of resolution

Each layer overrides the one before it:

1. **Package defaults:** everything works with no configuration at all.
2. **`[tool.research-helpers]`:** a project's wiring, read once per root and cached.
3. **Explicit keyword arguments:** always take precedence.

A value of `None` in an override is read as *not specified at this layer*, so a function may forward its own
optional arguments straight through to {py:func}`~research_helpers.project.resolve` without
filtering them first:

```python
def save_something(path, *, dpi=None):
    settings = resolve(current_project().figures, dpi=dpi)   # dpi=None leaves the project's value
```

Every entry point is fully callable with plain arguments and no project file.

## Complete example

```toml
[tool.research-helpers.paper]
main            = "tex/paper.tex"
tables-dir      = "tex/tables"
figures-dir     = "tex/figures"
bbl             = "tex/out_dir/paper.bbl"
build-dir       = "build"
text-width-in   = 6.45           # \textwidth: letterpaper, 73pt margins
column-width-in = 3.04           # \columnwidth

[tool.research-helpers.figures]
profile = "print"
palette = "colorblind"
font    = "TeX Gyre Pagella"
dpi     = 300

[tool.research-helpers.log]
directory     = "data/logs"      # omit for console output only
console-level = "INFO"
file-level    = "DEBUG"
colour        = "auto"

[tool.research-helpers.sweep]
runs-dir          = "runs"
contention-factor = 1.8          # no default is provided, has to be measured

[tool.research-helpers.arxiv]
engine     = "xelatex"
texlive    = 2025
bbl-format = "3.3"
```

## Subsections

### `paper`

Describes the document's geometry and the locations of its different components. All paths are relative to the project root.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `main` | path | `tex/paper.tex` | The manuscript. |
| `tables-dir` | path | `tex/tables` | Location of generated `.tex` tables. |
| `figures-dir` | path | `tex/figures` | Location of generated `.png` figures. |
| `bbl` | path | `tex/out_dir/paper.bbl` | The *biblatex* file. |
| `build-dir` | path | `build` | Scratch space for generated artefacts. |
| `text-width-in` | float | `6.45` | `\textwidth`. |
| `column-width-in` | float | `3.04` | `\columnwidth`. |

:::{note}
Both figures *and* tables are laid out against the document's width, so a figure or a table is
authored at the size it will be printed rather than scaled afterwards.

To find the real values, put `\showthe\textwidth` and `\showthe\columnwidth` in your document and
read them off the log. They come out in points, which you can write down as they are (see
[Units](#units) below).
:::

### Units

Any length may be written in inches, millimetres, centimetres, or TeX points, by changing the key's
suffix. These four all set the same field to the same value:

```toml
text-width-in = 6.4757
text-width-mm = 164.48
text-width-cm = 16.448
text-width-pt = 468.0
```

| Suffix | Unit | In one inch |
| --- | --- | --- |
| `-in` | inch | 1 |
| `-mm` | millimetre | 25.4 |
| `-cm` | centimetre | 2.54 |
| `-pt` | TeX point | 72.27 |

`-pt` is the default unit LaTeX uses, i.e., the one `\showthe\textwidth` prints.

Settings are stored in inches internally, because that is the unit `matplotlib` figure sizes use. 
`research-helpers doctor` shows the converted value.

### `figures`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `profile` | `screen` \| `print` | `screen` | `screen` is large and legible in a notebook. `print` is sized for the paper. |
| `palette` | str | `husl` | Any *seaborn* palette name. |
| `font` | str | `DejaVu Sans` | A *matplotlib* family name. |
| `dpi` | int | `150` | Used for saving figures. On-screen display is separate and fixed. |
| `print-height-in` | float | `3.2` | Height of a `print` profile figure. |

### `log`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `directory` | path | *(unset)* | Location where log files should be written. Omit it for console output only. |
| `console-level` | str | `INFO` | Any level name accepted by the standard library, including custom ones. |
| `file-level` | str | `DEBUG` | Same as above. Usually more verbose than the console. |
| `colour` | `auto` \| `always` \| `never` | `auto` | `auto` uses colours only when stderr is a terminal, so redirected output stays clean. |

### `sweep`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `runs-dir` | path | `runs` | Location where a sweep's manifest, parts, and results are written. |
| `contention-factor` | float | *(unset)* | A value indicating how much slower a task runs when the node is full. |

:::{note}
`contention-factor` is the ratio between a task's runtime alone on a node and its runtime with every 
core busy, and it depends on the specifics of the setup (*i.e.* the code, the node, and the scheduler). 
No default is provided since a wrong one would lead to incorrect walltime estimates that either waste 
a queue slot or get the job killed before completion. Left unset, {py:func}`~research_helpers.sweep.estimate_runtime` 
reports its numbers as optimistic and lists instructions on how to measure the factor.
:::

### `arxiv`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `engine` | str | `xelatex` | The engine you select on arXiv. Used to check for engine-specific hazards, e.g. microtype font expansion under XeTeX. |
| `texlive` | int | `2025` | The TeX Live year selected on arXiv. Used in diagnostic messages. |
| `bbl-format` | str | `3.3` | The *biblatex* `.bbl` format version that TeX Live year reads. |

## Checking settings resolution

The `doctor` utility can be used to check settings resolution:

```sh
research-helpers doctor
```

It prints every setting, the value in force, where it came from, and flags any configured 
path that does not exist:

```text
root       /Users/john/my-project
pyproject  pyproject.toml

  paper.main               tex/paper.tex                 [pyproject]
  paper.tables_dir         tex/tables                    [pyproject]
  paper.figures_dir        tex/figures                   [pyproject]
  paper.bbl                tex/out_dir/paper.bbl         [pyproject]
  paper.build_dir          build                         [pyproject]
  paper.text_width_in      6.48                          [pyproject]
  paper.column_width_in    3.04                          [pyproject]

  figures.profile          screen                        [pyproject]
  figures.palette          husl                          [pyproject]
  figures.font             DejaVu Sans                   [default]
  figures.dpi              300                           [pyproject]
  figures.print_height_in  3.2                           [default]

  log.directory            None                          [default]
  log.console_level        INFO                          [default]
  log.file_level           DEBUG                         [default]
  log.colour               auto                          [default]

  sweep.runs_dir           runs                          [default]   MISSING
  sweep.contention_factor  None                          [default]

  arxiv.engine             xelatex                       [pyproject]
  arxiv.texlive            2025                          [pyproject]
  arxiv.bbl_format         3.3                           [pyproject]
```

Checking `[default]` versus `[pyproject]` is useful when trying to troubleshoot keys,
for example when a setting appears to have no effect—usually a typo in the key name, which also
produces a warning you can see with `python -W always::UserWarning -c 'import ...'`.

`MISSING` indicates a path that is configured but does not exist. In the example above, `runs` is 
simply a directory that sweeps have not created yet. The same value on `paper.main` would mean that 
the manuscript path is wrong.

## Overriding the root

{py:func}`~research_helpers.project.find_project_root` searches upward for `pyproject.toml` or
`.git`. Set `RESEARCH_HELPERS_ROOT` to skip the search—necessary in a scheduler job whose
working directory is outside the tree:

```bash
export RESEARCH_HELPERS_ROOT=/scratch/$USER/my-project
```

If no root is found, {py:func}`~research_helpers.project.current_project` returns a project
carrying pure defaults rather than raising an exception so, for example, a Jupyter notebook 
in a scratch directory still works.

## Reading settings

Settings can be easily read by any code in the project:

```python
from research_helpers.project import current_project

paper = current_project().paper
width = paper.text_width_in
```

{py:func}`~research_helpers.project.current_project` caches per root, so calling it in a loop is
free.
