"""LaTeX table assembly."""

from __future__ import annotations

from typing import Any

import pytest

from research_helpers.latex import bare, dash_range, half_up, header, table
from research_helpers.project import _load


def minimal(**overrides: Any) -> str:
    """Return the smallest complete table, with 'overrides' passed to 'table'."""
    arguments: dict[str, Any] = {
        'spec': 'lr',
        'header_rows': [['Model', 'F1']],
        'body_rows': [['ITTB', '.82']],
        'caption': 'A caption.',
        'label': 'tab:example',
    }
    return table(**{**arguments, **overrides})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Geometry is read from the enclosing project. Give the tests a known, empty one."""
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    workdir = tmp_path / 'nowhere'
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    yield
    _load.cache_clear()


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Return a project declaring a column width, having chdir'd into it."""
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\ncolumn-width-in = 2.5\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    _load.cache_clear()
    return root


# --- structure --------------------------------------------------------------------------------


def test_the_float_is_complete_and_in_order():
    latex = minimal()

    assert latex == (
        '\\begin{table}[H]\n'
        ' \\centering\n'
        ' \\sffamily\\footnotesize\n'
        ' \\begin{tabulary}{\\textwidth}{lr}\n'
        '  \\toprule\n'
        '  Model & F1 \\\\\n'
        '  \\midrule\n'
        '  ITTB & .82 \\\\\n'
        '  \\bottomrule\n'
        '  \\end{tabulary}\n'
        '  \\caption{A caption.}\n'
        '  \\label{tab:example}  % chktex 24\n'
        '\\end{table}\n'
    )


def test_a_wide_table_spans_both_columns_and_floats():
    latex = minimal(wide=True)

    assert '\\begin{table*}[t]' in latex
    assert '\\end{table*}' in latex


def test_the_prologue_follows_the_first_header_row_only():
    latex = table(
        spec='lrr',
        header_rows=[['', 'Group'], ['Model', 'A', 'B']],
        body_rows=[['x', '1', '2']],
        caption='c',
        label='tab:t',
        prologue=['\\cmidrule{2-3}'],
    )
    lines = [line.strip() for line in latex.splitlines()]

    assert lines.index('\\cmidrule{2-3}') == lines.index('& Group \\\\') + 1
    assert lines.index('Model & A & B \\\\') > lines.index('\\cmidrule{2-3}')


def test_a_bare_rule_row_gets_no_row_terminator():
    latex = table(
        spec='l',
        header_rows=[['h']],
        body_rows=[['a'], ['\\midrule'], ['b']],
        caption='c',
        label='tab:t',
    )

    assert '  \\midrule\n  b \\\\' in latex
    assert '\\midrule \\\\' not in latex


def test_setup_and_style_land_inside_the_float():
    latex = minimal(setup='\\setlength{\\tabcolsep}{3pt}', style='\\rmfamily\\small')

    assert ' \\rmfamily\\small\n' in latex
    assert ' \\setlength{\\tabcolsep}{3pt}\n' in latex
    assert latex.index('\\setlength') > latex.index('\\rmfamily')


def test_the_chktex_suppression_can_be_turned_off():
    assert '  \\label{tab:example}\n' in minimal(chktex=False)


def test_a_table_must_have_a_label():
    with pytest.raises(ValueError, match='needs a label'):
        minimal(label='')


# --- width and geometry -----------------------------------------------------------------------


def test_tabulary_always_takes_the_full_text_width():
    assert '\\begin{tabulary}{\\textwidth}' in minimal(environment='tabulary')


def test_a_narrow_tabularx_takes_the_document_column_width(configured):  # noqa: ARG001
    assert '\\begin{tabularx}{2.5in}' in minimal(environment='tabularx')


def test_a_wide_tabularx_takes_the_full_text_width(configured):  # noqa: ARG001
    assert '\\begin{tabularx}{\\textwidth}' in minimal(environment='tabularx', wide=True)


def test_the_column_width_can_be_overridden_per_call(configured):  # noqa: ARG001
    assert '\\begin{tabularx}{1.5in}' in minimal(environment='tabularx', column_width_in=1.5)


def test_an_explicit_width_wins():
    assert '\\begin{tabularx}{0.8\\linewidth}' in minimal(environment='tabularx', width='0.8\\linewidth')


def test_an_environment_without_a_width_argument_gets_none():
    latex = minimal(environment='tabular')

    assert '\\begin{tabular}{lr}' in latex


# --- formatting helpers -----------------------------------------------------------------------


def test_header_emphasises_and_sizes():
    assert header('Model') == '\\scriptsize\\textbf{Model}'


def test_a_short_header_is_padded_so_its_column_does_not_collapse():
    assert header('UAS', expand='~~') == '\\scriptsize\\textbf{~~UAS~~}'
    assert header('Sentences', expand='~~') == '\\scriptsize\\textbf{Sentences}'


def test_the_header_size_can_be_changed():
    assert header('Model', size='footnotesize') == '\\footnotesize\\textbf{Model}'


@pytest.mark.parametrize(
    ('value', 'expected'),
    [(0.125, '0.13'), (0.135, '0.14'), (2.5, '2.50'), (-0.125, '-0.13'), (0.824, '0.82')],
)
def test_half_up_rounds_away_from_zero(value, expected):
    assert half_up(value) == expected


def test_half_up_differs_from_python_rounding_where_it_matters():
    assert half_up(0.125) == '0.13'
    assert f'{0.125:.2f}' == '0.12', 'python rounds halves to even, which reads as an error'


@pytest.mark.parametrize(
    ('text', 'expected'),
    [('0.82', '.82'), ('0.82 & 0.91', '.82 & .91'), ('10.5', '10.5'), ('0.0', '.0')],
)
def test_bare_drops_the_leading_zero(text, expected):
    assert bare(text) == expected


def test_dash_range_typesets_a_span():
    assert dash_range('1337-1362') == '1337--1362'
