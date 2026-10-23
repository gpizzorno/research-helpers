# arXiv and Zenodo

The main goal of this workflow is to automate submission tasks and make the resulting packages 
reproducible, that is, something that compiles in another system (e.g., arXiv) or that has identical 
checksums for identical content (Zenodo).

## arXiv

`--dry-run` runs the inventory and the checks and writes nothing, so it is safe in CI, and it
exits with `1` if anything is wrong.

```bash
$ research-helpers arxiv --dry-run
  paper.tex                                         125.3 KB
  paper.bbl                                         341.2 KB
  tables/annotation-effort-efficiency.tex             1.2 KB
  tables/consistency.tex                              1.1 KB
  ...
  figures/pos-distribution.png                       83.3 KB

  18 files, 1.21 MB
  bbl format 3.3 (TeX Live 2025)

ready to upload: select xelatex and TeX Live 2025

(dry run, nothing written)
```

Omit `--dry-run` to write to the submission directory. Include `--tar` to pack it, and `--preview`
to compile it with the engine arXiv will use, so the output can be verified.

{py:func}`~research_helpers.arxiv.manifest` keys every file by the path it takes *inside* the
submission, relative to the manuscript's directory. So a table installed at `tex/tables/scores.tex`
and read as `\input{tables/scores}` is uploaded as `tables/scores.tex` and resolves identically on
arXiv.

From the tables and figures directories, only the files read by the manuscript are uploaded, *i.e.*, those
used by `\input` or `\includegraphics`, outside a comment. Files that the manuscript does
not read, such as a table left behind when its `\input` was removed, are listed in the report:

```bash
$ research-helpers arxiv --dry-run
  paper.tex                        0.3 KB
  paper.bbl                        0.1 KB
  tables/scores.tex                0.0 KB
  figures/learning-curve.png      16.3 KB

  4 files, 0.02 MB
  bbl format 3.3 (TeX Live 2025)
  not uploaded, since paper.tex does not read them: tables/ablation.tex

ready to upload: select xelatex and TeX Live 2025

(dry run, nothing written)
```

A float read in some other way, *e.g.,* through a macro, is also omitted, and `--preview`
shows that the submission cannot compile without it. To include them, write the reference out, 
or pass the file to {py:func}`~research_helpers.arxiv.manifest` in `extra`.

### A second document

A [second document](documents.md) is submitted with `--document` and its name. Its submission is
built in its own build directory, so the paper's is left as is:

```bash
$ research-helpers arxiv --document note --tar
  note.tex               0.1 KB
  note.bbl               0.1 KB
  tables/rates.tex       0.0 KB

  3 files, 0.00 MB
  bbl format 3.3 (TeX Live 2025)

ready to upload: select xelatex and TeX Live 2025

wrote build/note/arxiv/
packed build/note/arxiv.tar.gz (0.00 MB)
```

### What the check finds

{py:func}`~research_helpers.arxiv.check` returns every reason why the submission would be rejected 
or would fail to build:

**A filename arXiv will not take.** Only `[A-Za-z0-9_+,=.-]` are permitted.

**A missing or stale `.bbl`.** arXiv does not run `biber`, so an uploaded `.bbl` *is* the
bibliography.

**`microtype` font expansion under XeTeX.** `expansion=true` is a hard error under `xelatex` and
`xetex`, which have no font expansion.

**A marker left in the text.** A project can list text that must not reach a submission, such as
the placeholders it writes for a page number or a citation still to be found:

```toml
[tool.research-helpers.arxiv]
markers = ["[PAGE]", "[CITATION NEEDED]"]
```

Each is looked for in every TeX file uploaded, the `.bbl` included, outside comments:

```bash
$ research-helpers arxiv --dry-run
  paper.tex                        0.3 KB
  paper.bbl                        0.1 KB
  tables/scores.tex                0.0 KB
  figures/learning-curve.png      16.3 KB

  4 files, 0.02 MB
  bbl format 3.3 (TeX Live 2025)
  not uploaded, since paper.tex does not read them: tables/ablation.tex

1 problem(s):
  - marker [PAGE] left in paper.tex: line 4
```

No marker is looked for unless one is configured.

## Reproducible archives

{py:mod}`research_helpers.archive` writes tarballs that are byte-identical across runs and
machines. A tarball by default records `mtimes`, `uids`, `gids`, and the compressing machine's filename 
in the *gzip* header, and uses the order the filesystem returned. Two archives of identical content 
thus get different checksums.

{py:func}`~research_helpers.archive.write_archive` pins each of those: `mtime` to a fixed epoch, `uid` 
and `gid` to zero. It also normalizes modes, sorts members, sets `GNU_FORMAT`, and empties the gzip 
header's filename field.

```python
from research_helpers.archive import archive_directory, digest, write_checksums

archive = archive_directory('build/deposit.tar.gz', 'build/deposit')
write_checksums([archive], 'build/SHA256SUMS')
```

{py:func}`~research_helpers.archive.digest` always gives the same answer for the same content.
