# LaTeX tables

The {py:mod}`research_helpers.latex` module assembles tables, while {py:mod}`research_helpers.display` reads them
back. Neither needs anything outside the standard library.

## Assembling

{py:func}`~research_helpers.latex.table` is keyword-only:

```python
from research_helpers.latex import bare, dash_range, half_up, header, table

table(
    spec='lrr',
    header_rows=[[header('System'), header('Accuracy'), header('F1')]],
    body_rows=[['Baseline', '71.23', '68.90'], ['Ours', '84.56', '82.01']],
    caption='Performance on the held-out set, in percent.',
    label='tab:scores',
)
```

`spec`
: The column specification, one character per column, as `tabular` takes it.

`wide=True`
: Emits `table*` instead of `table`, e.g., for a two-column document where the table spans both.

`environment`
: `tabulary` by default, which sizes columns to their content within a given width. Anything in
  `SIZED_ENVIRONMENTS` takes a width argument,
  `tabular` does not, and the width is left off.

`prologue` / `setup`
: LaTeX inserted before the environment and inside it. For things like a `\sisetup`,
  or a `\renewcommand{\arraystretch}`.

## The helpers

{py:func}`~research_helpers.latex.half_up`
: Python's {py:func}`round` rounds half to *even*: `round(0.685, 2)` is `0.68` and
  `round(0.675, 2)` is `0.68` as well. `half_up` rounds half to *up*, `half_up(0.685, 2)` 
  yields `0.69`.

{py:func}`~research_helpers.latex.header`
: Wraps a heading in the size and weight the table style uses, and can expand it across columns.

{py:func}`~research_helpers.latex.bare`
: Escapes LaTeX's special characters, for text arriving from data.

{py:func}`~research_helpers.latex.dash_range`
: Turns `1990-2000` into `1990--2000` (i.e. using an en-dash).

`EM_DASH`
: For use on empty cells.

## Reading a table back

{py:func}`~research_helpers.display.show` parses the `.tex` file of a generated table 
and renders it as a table readable in a notebook:

```python
from pathlib import Path
from research_helpers.display import show

show(Path('tex/tables/scores.tex').read_text())
```

{py:func}`~research_helpers.display.parse` returns the
{py:class}`~research_helpers.display.Table` without displaying it (useful for tests), since it 
includes cells, spans, alignment, rules, caption, and label as data.

```python
parsed = parse(latex)
assert parsed.columns() == 3
assert parsed.body[1].cells[0][0] == 'Ours'
```

`symbols` substitutes LaTeX commands for characters when rendering (`\textdagger` → `†`), and
`strip` removes commands whose output does not matter for reading.
