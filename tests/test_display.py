"""Reading a LaTeX table back for display."""

from __future__ import annotations

import pytest

from research_helpers.display import parse, show
from research_helpers.latex import header, table
from research_helpers.project import _load


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    workdir = tmp_path / 'nowhere'
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    yield
    _load.cache_clear()


@pytest.fixture
def round_trip():
    """Return a table built by this package, parsed back."""
    return parse(
        table(
            spec='Xrr',
            header_rows=[[header('Model'), header('UAS', expand='~~'), header('LAS', expand='~~')]],
            body_rows=[['ITTB', '.82', '.79'], ['Perseus', '.91', '.88']],
            caption='Scores on the gold standard, F1.',
            label='tab:scores',
            environment='tabularx',
        ),
    )


# --- the round trip ---------------------------------------------------------------------------


def test_the_header_and_body_survive_the_round_trip(round_trip):
    assert [text for text, _ in round_trip.header[0].cells] == ['Model', 'UAS', 'LAS']
    assert [text for text, _ in round_trip.body[0].cells] == ['ITTB', '.82', '.79']
    assert len(round_trip.body) == 2


def test_the_caption_and_label_survive_the_round_trip(round_trip):
    assert round_trip.caption == 'Scores on the gold standard, F1.'
    assert round_trip.label == 'tab:scores'


def test_the_column_alignment_survives_the_round_trip(round_trip):
    assert round_trip.align == ['l', 'r', 'r'], 'X is a left-aligned stretchy column'


def test_the_padding_added_for_narrow_columns_is_not_shown(round_trip):
    """'header(expand=...)' pads with '~', which is a space in LaTeX and must not be read back."""
    assert [text for text, _ in round_trip.header[0].cells] == ['Model', 'UAS', 'LAS']


def test_it_renders_as_html_for_jupyter(round_trip):
    rendered = round_trip._repr_html_()

    assert '<table class="paper-table">' in rendered
    assert '<th class="l">Model</th>' in rendered
    assert '<td class="r">.82</td>' in rendered
    assert 'Scores on the gold standard' in rendered


def test_it_renders_as_aligned_text_for_a_terminal(round_trip):
    lines = str(round_trip).splitlines()

    assert lines[0].split() == ['Model', 'UAS', 'LAS']
    assert set(lines[1]) == {'-'}, 'a rule separates the header from the body'
    assert lines[2].startswith('ITTB')
    # right-aligned columns line up
    assert lines[2].index('.82') == lines[3].index('.91')


def test_the_original_latex_is_kept(round_trip):
    assert round_trip.latex.startswith('\\begin{table}')


def test_columns_counts_the_widest_row(round_trip):
    assert round_trip.columns == 3


# --- features of real tables ------------------------------------------------------------------


def test_a_multicolumn_header_keeps_its_span():
    parsed = parse(
        table(
            spec='lrrrr',
            header_rows=[
                ['', '\\multicolumn{2}{c}{Morphological}', '\\multicolumn{2}{c}{Syntactic}'],
                ['Model', 'UPOS', 'XPOS', 'UAS', 'LAS'],
            ],
            body_rows=[['a', '1', '2', '3', '4']],
            caption='c',
            label='tab:span',
        ),
    )

    assert parsed.header[0].cells == [('', 1), ('Morphological', 2), ('Syntactic', 2)]
    assert parsed.columns == 5


def test_a_multicolumn_is_padded_out_in_the_text_rendering():
    parsed = parse(
        table(
            spec='lrr',
            header_rows=[['', '\\multicolumn{2}{c}{Both}'], ['Model', 'A', 'B']],
            body_rows=[['x', '1', '2']],
            caption='c',
            label='tab:span',
        ),
    )

    assert len(parsed._grid()[0]) == 3  # noqa: SLF001


def test_a_shaded_row_is_marked_and_rendered():
    parsed = parse(
        table(
            spec='lr',
            header_rows=[['Model', 'F1']],
            body_rows=[['a', '.1'], ['\\rowcolor{gray!20} b', '.9']],
            caption='c',
            label='tab:shaded',
        ),
    )

    assert not parsed.body[0].shaded
    assert parsed.body[1].shaded
    assert parsed.body[1].cells[0][0] == 'b', 'the colour command itself is not text'
    assert 'shaded' in parsed._repr_html_()


def test_an_interior_rule_marks_the_row_beneath_it():
    parsed = parse(
        table(
            spec='lr',
            header_rows=[['Model', 'F1']],
            body_rows=[['a', '.1'], ['\\midrule'], ['b', '.9']],
            caption='c',
            label='tab:ruled',
        ),
    )

    assert parsed.body[1].rule
    assert 'rule' in parsed._repr_html_()


# --- tables this package did not generate -------------------------------------------------------

PLAIN_TABULAR = r"""
\begin{table}
  \centering
  \begin{tabular}{lcr}
    \toprule
    Corpus & Genre & Tokens \\
    \midrule
    Perseus & verse & 1{,}200 \\
    PROIEL & prose & 3{,}400 \\
    \bottomrule
  \end{tabular}
  \caption{Sizes.}
  \label{tab:sizes}
\end{table}
"""

LONGTABLE = r"""
\begin{longtable}{ll}
  \toprule
  Key & Value \\
  \midrule
  alpha & one \\
  beta & two \\
  \bottomrule
\end{longtable}
"""


def test_a_hand_written_tabular_is_read():
    parsed = parse(PLAIN_TABULAR)

    assert [text for text, _ in parsed.header[0].cells] == ['Corpus', 'Genre', 'Tokens']
    assert parsed.align == ['l', 'c', 'r']
    assert parsed.caption == 'Sizes.'
    assert parsed.label == 'tab:sizes'
    assert len(parsed.body) == 2


def test_a_longtable_is_read():
    parsed = parse(LONGTABLE)

    assert [text for text, _ in parsed.header[0].cells] == ['Key', 'Value']
    assert len(parsed.body) == 2


def test_something_that_is_not_a_table_is_rejected():
    with pytest.raises(ValueError, match='no tabulary'):
        parse('\\begin{figure}\\includegraphics{x}\\end{figure}')


# --- cleaning ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('cell', 'expected'),
    [
        (r'\textbf{Bold}', 'Bold'),
        (r'\textbf{\emph{Nested}}', 'Nested'),
        (r'50\%', '50%'),
        (r'Smith \& Jones', 'Smith & Jones'),
        (r'$\le$ 5', '≤ 5'),
        (r'$R^2$', 'R²'),
        ('1337--1362', '1337\u20131362'),
        (r'\scriptsize\textbf{UAS}', 'UAS'),
        (r'$s_{9}$', 's9'),
    ],
)
def test_typesetting_is_stripped_from_cells(cell, expected):
    parsed = parse(f'\\begin{{tabular}}{{l}}\n{cell} \\\\\n\\end{{tabular}}')

    assert parsed.header[0].cells[0][0] == expected


def test_a_project_can_add_its_own_symbols():
    parsed = parse(
        '\\begin{tabular}{l}\n\\euro 40 \\\\\n\\end{tabular}',
        symbols={'\\euro': '€'},
    )

    assert parsed.header[0].cells[0][0] == '€ 40'


def test_a_project_can_strip_its_own_commands():
    parsed = parse(
        '\\begin{tabular}{l}\n\\anonymised{Smith} Jones \\\\\n\\end{tabular}',
        strip=[r'\\anonymised\{[^}]*\}'],
    )

    assert parsed.header[0].cells[0][0] == 'Jones'


def test_show_is_parse():
    assert str(show(PLAIN_TABULAR)) == str(parse(PLAIN_TABULAR))


def test_an_escaped_ampersand_does_not_split_the_row():
    r"""'\&' is a literal ampersand; only a bare '&' separates columns."""
    parsed = parse('\\begin{tabular}{ll}\nSmith \\& Jones & 12 \\\\\n\\end{tabular}')

    assert parsed.header[0].cells == [('Smith & Jones', 1), ('12', 1)]
