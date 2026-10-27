"""Maths set as text, in a float's own typeface."""

# ruff: noqa: RUF001

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from research_helpers.latex import packages
from research_helpers.textmath import COMMANDS, DESIGNED_SCRIPT, PACKAGE, UnsupportedMathError, convert, to_text

CONVERTED = [
    # variables italic, numbers and upper-case Greek upright, as TeX sets them
    ('k', r'\textit{k}'),
    (r'\mu', r'\textit{μ}'),
    (r'\Omega', 'Ω'),
    ('0.4627', '0.4627'),
    # a run of letters is one word in one \textit, so that it kerns as one
    ('EQ', r'\textit{EQ}'),
    # a relation takes a thick space either side, a binary operator a medium one
    (r'\mu \le 0.5', r'\textit{μ}\tmthick{}≤\tmthick{}0.5'),
    ('a - b', r'\textit{a}\tmmed{}−\tmmed{}\textit{b}'),
    # a sign takes none, and a minus is a minus
    ('-0.0046', '−0.0046'),
    ('+0.0783', '+0.0783'),
    (r'\ge 0.050', r'≥\tmthick{}0.050'),
    # an operator name is upright, and thinly spaced from its argument
    (r'\log n', r'\textup{log}\tmthin{}\textit{n}'),
    # digits and signs in a script come from the font's designed glyphs, anything else is scaled
    (r'9.8\times 10^{-4}', r'9.8\tmmed{}×\tmmed{}10\tmsup{−4}'),
    ('F_1', r'\textit{F}\tmsub{1}'),
    ('Q_{ov}', r'\textit{Q}\tmsubx{\textit{ov}}'),
    (r'\text{NMI}_{\max}', r'\textup{NMI}\tmsubx{\textup{max}}'),
    # no space around a relation inside a script, as in TeX
    (r'k_{\ge 5}', r'\textit{k}\tmsubx{≥5}'),
    # a script with no base, as after a letter written outside the maths
    ('_1', r'\tmsub{1}'),
    # both scripts on one base, stacked
    (r'\sigma_i^2', r'\textit{σ}\tmscripts{\tmsubx{\textit{i}}}{\tmsup{2}}'),
    # TeX takes one token as a script: x_10 is x_1 followed by 0
    ('x_10', r'\textit{x}\tmsub{1}0'),
    (r'n = 1{,}000', r'\textit{n}\tmthick{}=\tmthick{}1,000'),
    (r'|\Omega| \le 0.05', r'|Ω|\tmthick{}≤\tmthick{}0.05'),
    (r'\bar{\Omega}', r'\tmbar{Ω}'),
    (r'\left( x \right)', r'(\textit{x})'),
    (r'p\,q', r'\textit{p}\tmthin{}\textit{q}'),
    (r'\operatorname{rank} A', r'\textup{rank}\tmthin{}\textit{A}'),
]


@pytest.mark.parametrize(('expression', 'expected'), CONVERTED)
def test_maths_becomes_text(expression, expected):
    assert to_text(expression) == expected


def test_a_script_is_set_from_designed_glyphs_only_if_they_cover_all_of_it():
    assert to_text('10^{-24}') == r'10\tmsup{−24}'
    assert to_text('10^{-2.5}') == r'10\tmsupx{−2.5}'  # a decimal point is not among them
    assert set('0123456789−+=()') == DESIGNED_SCRIPT


@pytest.mark.parametrize(
    ('expression', 'reason'),
    [
        (r'\frac{a}{b}', r'\\frac is not supported'),
        (r'\sqrt{2}', r'\\sqrt is not supported'),
        (r'\mathcal{A}', r'\\mathcal is not supported'),
        ('x_{a_b}', 'a script inside a script'),
        ('x_1_2', 'a double subscript'),
        ('x^1^2', 'a double superscript'),
        ('{x', 'a group is not closed'),
        ('x}', 'closes no group'),
        ('x\\', 'ends in a backslash'),
        ('x_', 'an argument is missing'),
        ('@', "'@' is not supported"),
    ],
)
def test_maths_outside_the_subset_is_refused(expression, reason):
    with pytest.raises(UnsupportedMathError, match=reason):
        to_text(expression)


def test_the_refusal_names_the_expression():
    with pytest.raises(UnsupportedMathError, match=re.escape(r"cannot set '\\frac{a}{b}' as text")):
        to_text(r'\frac{a}{b}')


# --- converting LaTeX that holds maths ------------------------------------------------------------


def test_every_inline_expression_is_converted():
    caption = r'Peak \(k\) is the maximum of \(Q_{ov}\), and at $\mu \le 0.5$ it held.'

    assert convert(caption) == (
        r'Peak \textit{k} is the maximum of \textit{Q}\tmsubx{\textit{ov}}, '
        r'and at \textit{μ}\tmthick{}≤\tmthick{}0.5 it held.'
    )


def test_text_without_maths_is_untouched():
    assert convert('Excess over the planted cover.') == 'Excess over the planted cover.'


@pytest.mark.parametrize('latex', [r'costs \$5 and \$6', '$$x = 1$$', r'\[x = 1\]'])
def test_escaped_dollars_and_display_maths_are_left_alone(latex):
    assert convert(latex) == latex


def test_a_line_break_before_a_parenthesis_opens_no_maths():
    # read as '\\' and '(', as TeX reads it, not as a backslash and '\('
    assert convert(r'\shortstack{Enron\\(internal)} \(k\)') == r'\shortstack{Enron\\(internal)} \textit{k}'


def test_maths_that_is_not_closed_is_refused():
    with pytest.raises(UnsupportedMathError, match='the maths is not closed'):
        convert(r'at \(\mu \le 0.5')


def test_a_space_written_after_the_maths_survives():
    # a command ended by a space would swallow the one after it
    assert convert(r'\(x\,\) and') == r'\textit{x}\tmthin{} and'


# --- the LaTeX package -----------------------------------------------------------------------------


def test_the_package_defines_every_command_the_converter_writes():
    source = packages()[f'{PACKAGE}.sty']
    defined = set(re.findall(r'\\DeclareRobustCommand\s*\\(\w+)', source))
    written = {name for _, expected in CONVERTED for name in re.findall(r'\\(tm[a-z]+)', expected)}

    assert set(COMMANDS) <= defined
    assert written <= set(COMMANDS)


def test_the_package_names_itself():
    assert f'\\ProvidesPackage{{{PACKAGE}}}' in packages()[f'{PACKAGE}.sty']


FIRA_SANS = (
    shutil.which('kpsewhich')
    and subprocess.run(
        ['kpsewhich', 'FiraSans-Regular.otf'],
        capture_output=True,
        check=False,
    ).returncode
    == 0
)


@pytest.mark.skipif(not shutil.which('xelatex'), reason='needs xelatex')
@pytest.mark.parametrize(
    ('font', 'expressions'),
    [
        # Latin Modern, fontspec's default, has no designed superiors: the scaled fallback
        ('', [r'Q_{ov}', 'F_1', '10^{2}', 'x_i^2']),
        pytest.param(
            '\\usepackage[sfdefault]{FiraSans}',  # with designed superiors and inferiors, and Greek
            [r'9.8\times 10^{-4}', r'\mu \le 0.5', r'\text{NMI}_{\max}', r'\sigma_i^2', r'\bar{\Omega}'],
            marks=pytest.mark.skipif(not FIRA_SANS, reason='needs Fira Sans'),
        ),
    ],
)
def test_the_converted_maths_compiles(tmp_path, font, expressions):
    (tmp_path / f'{PACKAGE}.sty').write_text(packages()[f'{PACKAGE}.sty'], encoding='utf-8')
    body = ' \\par '.join(to_text(expression) for expression in expressions)
    document = f'\\documentclass{{article}}\\usepackage{{{PACKAGE}}}{font}\\begin{{document}}{body}\\end{{document}}\n'
    (tmp_path / 'test.tex').write_text(document, encoding='utf-8')

    result = subprocess.run(
        ['xelatex', '-interaction=nonstopmode', '-halt-on-error', 'test.tex'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    log = (tmp_path / 'test.log').read_text(encoding='utf-8', errors='replace')
    assert result.returncode == 0, log[-2000:]
    assert 'Missing character' not in log
