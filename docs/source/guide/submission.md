# arXiv and Zenodo

The main goal of this workflow is to automate submission tasks and make the resulting packages 
reproducible, that is, something that compiles in another system (e.g., arXiv) or that has identical 
checksums for identical content (Zenodo).

## arXiv

`--dry-run` runs the inventory and the checks and writes nothing, so it is safe in CI, and it
exits with `1` if anything is wrong.

```console
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

### Testing with `--check`

{py:func}`~research_helpers.arxiv.check` returns every reason why the submission would be rejected 
or would fail to build:

**A filename arXiv will not take.** Only `[A-Za-z0-9_+,=.-]` are permitted.

**A missing or stale `.bbl`.** arXiv does not run `biber`, so an uploaded `.bbl` *is* the
bibliography.

**`microtype` font expansion under XeTeX.** `expansion=true` is a hard error under `xelatex` and
`xetex`, which have no font expansion.

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
