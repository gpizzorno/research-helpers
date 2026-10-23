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
library-level = "WARNING"        # other libraries' loggers
colour        = "auto"

[tool.research-helpers.sweep]
runs-dir          = "runs"
contention-factor = 1.8          # no default is provided, has to be measured
max-array         = 1000

[tool.research-helpers.arxiv]
engine     = "xelatex"
texlive    = 2025
bbl-format = "3.3"

[tool.research-helpers.documents.note]
main = "tex/note/note.tex"       # additional document (besides paper)
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
| `manuscript` | bool | `true` | Whether the manuscript is part of this repository. See [without the manuscript](#without-the-manuscript). |

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
| `library-level` | str | `WARNING` | The level of every logger not obtained from `get_logger`, *i.e.*, those belonging to other libraries. Keeps their routine output out of the console and the file. See [Other libraries](guide/logging.md#other-libraries). |
| `colour` | `auto` \| `always` \| `never` | `auto` | `auto` uses colours only when stderr is a terminal, so redirected output stays clean. |

### `sweep`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `runs-dir` | path | `runs` | Location where a sweep's manifest, parts, and results are written. |
| `contention-factor` | float | *(unset)* | A value indicating how much slower a task runs when the node is full. |
| `max-array` | int | `1000` | The most elements one array should carry. Caps a sweep's planned width, and splits a [queue](guide/queues.md) across files. |

:::{note}
`contention-factor` is the ratio between a task's runtime alone on a node and its runtime with every 
core busy, and it depends on the specifics of the setup (*i.e.* the code, the node, and the scheduler). 
No default is provided since a wrong one would lead to incorrect wall-time estimates that either waste 
a queue slot or get the job killed before completion. Left unset, {py:func}`~research_helpers.sweep.estimate_runtime` 
reports its numbers as optimistic and lists instructions on how to measure the factor.
:::

### `arxiv`

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `engine` | str | `xelatex` | The engine you select on arXiv. Used to check for engine-specific hazards, e.g. microtype font expansion under XeTeX. |
| `texlive` | int | `2025` | The TeX Live year selected on arXiv. Used in diagnostic messages. |
| `bbl-format` | str | `3.3` | The *biblatex* `.bbl` format version that TeX Live year reads. |
| `markers` | list of str | `[]` | Text that must not reach a submission, such as `"[PAGE]"`. The check reports each one it finds outside a comment in an uploaded TeX file, the `.bbl` included. See [arXiv and Zenodo](guide/submission.md#what-the-check-finds). |

### `documents`

Further manuscripts beside the paper, one table each, named by the document: a technical note, a
supplement, a second paper. The paper itself is always configured under `[paper]`.

```toml
[tool.research-helpers.documents.note]
main = "tex/note/note.tex"
```

Each takes the same keys as `paper`. Only `main` is required, unless the document is configured
[without its manuscript](#without-the-manuscript), and the rest are derived from it:

| Key | Default |
| --- | --- |
| `tables-dir` | `tables/` beside `main` |
| `figures-dir` | `figures/` beside `main` |
| `bbl` | `out_dir/<stem of main>.bbl` beside `main` |
| `build-dir` | the paper's `build-dir`, then the document's name |
| `text-width-*`, `column-width-*` | the paper's |

`doctor` marks a value that follows from `main` as `[derived]`, and one taken from the paper as
`[inherited]`. See [several documents](guide/documents.md).

### Without the manuscript

A repository can publish a document's tables and figures without its source using `manuscript = false`:

```toml
[tool.research-helpers.paper]
manuscript = false
tables-dir = "build/tables"
figures-dir = "build/figures"
```

`--check` then compares every registered float with its installed copy, and reports an installed
file without an emitter. Those items that require a manuscript are reported as not checked:
whether the manuscript uses each float, whether it carries one written in by hand, and the numbers
its prose states. `main` and `bbl` are not used, and `doctor` shows them as `[no manuscript]`.

Without a manuscript `tables-dir` and `figures-dir` default to the build directory's `tables/` and `figures/`, 
and `--install` has nothing to copy. A document under `[documents]` can also have a `manuscript` key, and needs no 
`main` if it is set to `false`.

The setting is declared to ensure that a repository that does carry its manuscript still fails the check when the manuscript goes missing. See [publishing the floats without the paper](guide/generated-table.md#8-publishing-the-floats-without-the-paper).

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
  log.library_level        WARNING                       [default]
  log.colour               auto                          [default]

  sweep.runs_dir           runs                          [default]   MISSING
  sweep.contention_factor  None                          [default]
  sweep.max_array          1000                          [default]

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
