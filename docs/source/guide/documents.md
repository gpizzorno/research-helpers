# Several documents

A project sometimes carries more than one manuscript: a paper and a technical note, a paper and its
supplement, or one paper split into two. Each needs its own generated tables and figures, installed
where *it* reads them and checked against *its* source.

## Configure the second document

```toml
[tool.research-helpers.paper]
main = "tex/paper.tex"

[tool.research-helpers.documents.note]
main = "tex/note/note.tex"
```

`main` is the only key a document needs. Other settings are derived from it unless they are explicitly set:

| Key | Default |
| --- | --- |
| `tables-dir` | `tables/` beside the manuscript |
| `figures-dir` | `figures/` beside the manuscript |
| `bbl` | `out_dir/<stem>.bbl` beside the manuscript |
| `build-dir` | the paper's build directory, then the document's name |
| `text-width-*`, `column-width-*` | the paper's geometry: a second document set in the same class has the same parameters |

Any of them can be set, exactly as under `[paper]`. `research-helpers doctor` shows where each value
came from:

```text
  documents.note.main             tex/note/note.tex             [pyproject]
  documents.note.tables_dir       tex/note/tables               [derived]
  documents.note.figures_dir      tex/note/figures              [derived]   MISSING
  documents.note.bbl              tex/note/out_dir/note.bbl     [derived]   MISSING
  documents.note.build_dir        build/note                    [derived]
  documents.note.text_width_in    6.45                          [inherited]
  documents.note.column_width_in  3.04                          [inherited]
```

## One `Document` per manuscript

{py:class}`~research_helpers.build.Document` groups a manuscript's registries, and optionally its
[prose numbers](prose.md), so that one command builds, installs, and checks all of it:

```python
"""The paper and the note."""

import sys

from research_helpers.build import TABLES, Document, Registry

from report.prose import prose

tables = Registry(TABLES)
note_tables = Registry(TABLES)


@tables.register('tab:shape')
@note_tables.register('tab:shape')
def shape() -> str:
    """Cover shape."""
    return '\\begin{table}[t]\n0.386 & 7.72 \\\\\n\\label{tab:shape}\n\\end{table}\n'


paper = Document('paper', tables, prose=prose)
note = Document('note', note_tables, prose=prose)

if __name__ == '__main__':
    document = {'paper': paper, 'note': note}[sys.argv.pop(1)]
    raise SystemExit(document.main())
```

Each document has its own registries. A float carried by two documents has to be registered in both. The decorator 
returns the emitter unchanged, so multiple registrations do not conflict. Similarly, since a document only checks the entries 
it prints, the prose registry can be shared.

```bash
$ python -m report.documents note --install
wrote build/note/tables/shape.tex
installed tex/note/tables/shape.tex

$ python -m report.documents note --check
OK: all 1 tables in the note are current
OK: all 1 prose numbers are current

$ python -m report.documents paper --check
OK: all 1 tables in the paper are current
stale [abstract] mean-k:
    prints     OSLOM finds 143 communities on average
    data give  OSLOM finds 148.6 communities on average
2 checked. To fix: correct the text, or list the entry as a known discrepancy
```

`--check` exits with `1` if anything the document carries has drifted. `--list` shows what is registered,
by kind.

A project with a single paper can keep calling each registry's own `main()`, or wrap them in
`Document('paper', ...)` for one command over tables, figures, and prose together. The paper's
`Document` builds and installs into the same directories a bare registry does.
