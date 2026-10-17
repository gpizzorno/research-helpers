# Numbers in the prose

This {py:mod}`research_helpers.prose` module is a registry for typed numbers. Each number the prose 
states is registered as the fragment of the sentence that carries it, with `{}` where the number goes, 
together with a function that computes the number from the data. The check reads the document and 
reports every fragment that no longer says what the data contains.

## Register a sentence

```python
"""Every number the documents state in prose."""

from research_helpers.prose import ProseRegistry

from report import sources

prose = ProseRegistry()


@prose.register('mean-k', 'OSLOM finds {} communities on average', section='abstract', source='runs/oslom.json')
def mean_k():
    return (f"{sources.oslom()['mean_k']:.1f}",)


@prose.register('debris', 'of which {} per cent are debris', section='abstract', source='runs/oslom.json')
def debris():
    return (f"{sources.oslom()['debris_pct']:.1f}",)


if __name__ == '__main__':
    raise SystemExit(prose.main())
```

The function returns the numbers *as printed*, formatted, one per `{}`. The template is the
fragment as it appears in the `.tex` source, so LaTeX goes in as written, and a literal brace is
doubled: `'\\(Q_{{ov}} = {}\\)'`. Whitespace does not matter: the template and the document are
both compared with every run of whitespace collapsed to one space, so a sentence that wraps across
lines in the source still matches.

`source` and `section` indicate where the number comes from, and where the sentence is.

:::{note}
Keep every file read in one module, as `report.sources` does here, and have the registry call it
rather than opening files itself. This ensures that a missing result fails with the name of 
whatever produces it.
:::

## Check

```bash
$ python -m report.prose
stale [abstract] mean-k:
    prints         OSLOM finds 143 communities on average
    data contains  OSLOM finds 148.6 communities on average
3 checked. To fix: correct the text, or list the entry as a known discrepancy
```

The `check` is the default action, and it exits with 1 when it finds anything, so it can gate CI alongside
the table and figure checks. A stale entry shows what the document prints in place of what the data
constains. Other things it reports:

- **not found:** the sentence itself is no longer in the document: it was rewritten, moved, or cut.
  Update the template to the sentence as it now reads, or remove the entry.
- **could not compute:** the entry's function raised, usually because the result it reads has not
  been produced. The check continues with the other entries.

A sentence that has been commented out does not count as printed.

## Known discrepancies

Sometimes the text is knowingly wrong for a while, *e.g.*, while a re-run is checked before the prose
is revised. List those entries, with what the data contains:

```python
prose.known_discrepancies['debris'] = 'the data contains 7.9; corrected in the next revision'
```

The check then requires two things of such an entry: the sentence must still be there, and it must 
still be wrong: once the text is corrected, the check fails until the entry leaves the list (to 
prevent a list of discrepancies outliving the discrepancies themselves).

`untraced` is the companion list, for numbers that have no source to compute them from (a value
quoted from the literature, a figure from a catalogue), and it is not checked.

## Find untracked values

```bash
$ python -m report.prose --audit
# Prose-number audit: paper

4 numeric tokens in the prose: **1** untraced, **0** in a float the paragraph does not cite, **0** in a float the paragraph cites, **1** a parameter or a formula constant, **2** registered.

## Untraced

| Line | Token | Detail | Context |
|---|---|---|---|
| 8 | `20` |  | which 7.7 per cent are debris. \end{abstract} Covers were drawn over 20 seeds at \(\mu = 0.4\), see Table~\ref{tab:shape} |
```

The audit classifies every numeric token in the body of the document, from the abstract on, and
lists untracked ones first. Each token falls in the first category that applies:

1. **Registered:** it sits inside a registered fragment.
2. **A parameter or a formula constant:** it is a constant of an inline formula (`\(6/7\)`), or the
   value of a declared parameter (`\(\mu = 0.4\)`). Not a result.
3. **In a float the paragraph cites:** a generated table the same paragraph refers to carries it.
4. **In a float the paragraph does not cite:** some generated table carries it, but this paragraph
   does not point there. Worth a look.
5. **Untraced:** everything else. These are the numbers to register.

Numbers in the preamble, comments, display math, citations, labels, and references are skipped.
`--out audit.md` writes the report to a file instead of printing it.

An assignment in inline math reads as a *result* unless its symbol is declared a parameter. 
Declare the symbols that set up an experiment rather than report on it:

```python
prose = ProseRegistry(parameter_symbols=[r'\mu', r'\tau'])
```

## In a test suite

`--check` is enough for CI. To see one failure per sentence in `pytest` instead, parametrize over the
registry:

```python
import pytest

from report.prose import prose


@pytest.fixture(scope='module')
def found():
    return prose.check()


@pytest.mark.parametrize('entry', list(prose), ids=lambda entry: entry.key)
def test_the_prose_states_what_the_data_contains(entry, found):
    mismatched = {mismatch.key: mismatch for mismatch in found.stale + found.vanished}
    assert entry.key not in mismatched, mismatched.get(entry.key)
```

## More than one document

Each entry names the document that prints it, `paper` by default. A sentence repeated by
another document has to be registered once for each:

```python
@prose.register('mean-k-note', 'OSLOM finds {} communities on average', document='note')
def mean_k_note():
    return mean_k()
```

Documents other than the paper are configured under `[tool.research-helpers.documents]`, see
[several documents](documents.md).
