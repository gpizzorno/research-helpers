# Adding a generated table

This is a description of the full pipeline for a small sample table (from a JSON file in the repository) 
to a CI check that fails when the paper falls behind the data.

The project is laid out as follows:

```text
pyproject.toml
data/scores.json
src/paperdemo/tables.py
tex/paper.tex
tex/tables/
```

## 1. Wire the project

Since the paper's location is different from the default, it needs to be added to `pyproject.toml`. 
Everything else is using defaults.

```toml
[tool.research-helpers.paper]
main = "tex/paper.tex"
```

## 2. Write the emitter

An emitter is a function that returns LaTeX. It takes no arguments and reads whatever it needs
from the repository, keeping the results reproducible.

```python
"""LaTeX emitter for the paper's tables."""

from __future__ import annotations

import json
from pathlib import Path

from research_helpers.build import TABLES, Registry
from research_helpers.latex import half_up, header, table

tables = Registry(TABLES)

DATA = Path(__file__).resolve().parents[2] / 'data' / 'scores.json'


@tables.register('tab:scores')
def scores() -> str:
    """Accuracy and F1 for the baseline and our system."""
    data = json.loads(DATA.read_text())
    rows = [
        [name.title(), half_up(values['accuracy'] * 100), half_up(values['f1'] * 100)]
        for name, values in data.items()
    ]
    return table(
        spec='lrr',
        header_rows=[[header('System'), header('Accuracy'), header('F1')]],
        body_rows=rows,
        caption='Performance on the held-out set, in percent.',
        label='tab:scores',
    )


if __name__ == '__main__':
    raise SystemExit(tables.main())
```

Three things to note:

`@tables.register('tab:scores')`
: The label is the identity of the table. The filename is the label with the `tab:` prefix
  removed, so this one is written to `scores.tex` and the paper reads it as
  `\input{tables/scores}`.

The docstring
: It becomes the description in `--list`. There is no other place to write down what a table is.

{py:func}`~research_helpers.latex.half_up`
: This function rounds half to up, as opposed to Python that rounds half to even, i.e. `round(0.685, 2)` 
yields `0.68`, while `half_up(0.685, 2)` yields `0.69`.

:::{warning}
The `if __name__ == '__main__'` block must be kept at the *bottom* of the module. Emitters below 
it are never registered when the module is run with `-m`, because `main()` executes before the
interpreter reaches them.
:::

## 3. Reference the table from the paper

```latex
Our system improves over the baseline (Table~\ref{tab:scores}).
\input{tables/scores}
```

## 4. Build the table

```bash
$ python -m paperdemo.tables --list
  tab:scores  Accuracy and F1 for the baseline and our system.

$ python -m paperdemo.tables
wrote build/tables/scores.tex
```

The table is saved to the build directory first, so it can be checked before it
goes anywhere near the paper:

```latex
\begin{table}[H]
 \centering
 \sffamily\footnotesize
 \begin{tabulary}{\textwidth}{lrr}
  \toprule
  \scriptsize\textbf{System} & \scriptsize\textbf{Accuracy} & \scriptsize\textbf{F1} \\
  \midrule
  Baseline & 71.23 & 68.90 \\
  Ours & 84.56 & 82.01 \\
  \bottomrule
  \end{tabulary}
  \caption{Performance on the held-out set, in percent.}
  \label{tab:scores}  % chktex 24
\end{table}
```

At this point the check would already fail, because the paper does not have this table yet:

```bash
$ python -m paperdemo.tables --check
stale, the paper is behind the data: tab:scores
to fix: rebuild and install the tables
$ echo $?
1
```

## 5. Install the table

```bash
$ python -m paperdemo.tables --install
wrote build/tables/scores.tex
installed tex/tables/scores.tex

$ python -m paperdemo.tables --check
OK: all 1 tables in the paper are current
```

## 6. Scenarios covered by the check

**The data changes, but the paper is not rebuilt.** This is the main failure mode the pipeline is 
designed to prevent—i.e., the PDF keeps compiling cleanly but also keeps showing superceded numbers.

```bash
$ # data/scores.json is updated: ours.accuracy 0.8456 -> 0.8712
$ python -m paperdemo.tables --check
stale, the paper is behind the data: tab:scores
```

**A table is generated but never used.** For example, a `tab:ablation` emitter is registered but the
`\input` is never added to the paper:

```bash
$ python -m paperdemo.tables --check
emitted but never used by the paper: tab:ablation
```

**A table is typed by hand.** For example, a `table` float is added to the paper with its own `tabular` 
in it:

```bash
$ python -m paperdemo.tables --check
written into the paper by hand, with no emitter: tab:corpus
to fix: edit the paper
```

A hand-typed table is treated as a set of numbers that lack a connection back to the data. 
It cannot go stale, because nothing checks it.

## 7. The check can be used in CI

```yaml
- name: The paper's tables are current
  run: python -m paperdemo.tables --check
```

`--check` exits with `1` if it detects any drift.

## 8. Publishing the floats without the paper

A repository can publish the tables and figures without the paper's source by setting `manuscript` to
`false` in `pyproject.toml`:

```toml
[tool.research-helpers.paper]
manuscript = false
```

The tables are then read from where the build directory, so there is nothing to install:

```bash
$ python -m paperdemo.tables --install
wrote build/tables/scores.tex
nothing to install: the tables are read from where they are built
```

The check compares each table with its copy in `build/tables`, and states the items it could not check
without the paper:

```bash
$ python -m paperdemo.tables --check
OK: all 1 tables match their copies in build/tables
not checked without the manuscript: whether the paper uses each one and whether it carries any written in by hand
```

A copy that no longer renders from the data is stale, as before:

```bash
$ # data/scores.json is updated: ours.accuracy 0.8456 -> 0.8712
$ python -m paperdemo.tables --check
stale, build/tables is behind the data: tab:scores
to fix: rebuild and install the tables
not checked without the manuscript: whether the paper uses each one and whether it carries any written in by hand
```

And a file without an emitter, such as one left behind when its emitter was removed, is
still reported:

```bash
$ python -m paperdemo.tables --check
in build/tables with no emitter: tab:ablation
to fix: delete the files without an emitter
not checked without the manuscript: whether the paper uses each one and whether it carries any written in by hand
```

The mode is explicitly declared to ensure that a repository that carries a paper
keeps the default, so its check still fails if the paper goes missing.

## Figures work the same way

Figures work the same way, only using bytes instead of strings. The keyword to use with 
{py:func}`~research_helpers.figures.render` is `FIGURES` instead of `TABLES`, and the labels
should be registered under `fig:`:

```python
from research_helpers.build import FIGURES, Registry
from research_helpers.figures import apply_style, render

figures = Registry(FIGURES)


@figures.register('fig:learning-curve')
def learning_curve() -> bytes:
    """Accuracy against training iteration."""
    apply_style(profile='print')
    fig, ax = plt.subplots()
    ...
    return render(fig)
```

Byte-comparison drift detection works on the binary artefact because {py:func}`~research_helpers.figures.render` 
returns the same bytes {py:func}`~research_helpers.figures.save` would write.

The one distinction with tables is that a `figure` float in the paper with no emitter is **not** reported.

This is because paper will often contain figures that were drawn, photographed, or
taken from other sources and the noise generated by flagging them risks rendering the check
useless.
