"""Assemble LaTeX tables from data, so a paper's numbers are generated rather than typed."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from research_helpers.project import current_project, resolve

__all__ = [
    'EM_DASH',
    'bare',
    'dash_range',
    'half_up',
    'header',
    'table',
]

EM_DASH = '—'  # for empty cells

# environments taking a width argument before the column spec
SIZED_ENVIRONMENTS = ('tabulary', 'tabularx', 'tabular*')

DEFAULT_ENVIRONMENT = 'tabulary'
DEFAULT_STYLE = '\\sffamily\\footnotesize'
DEFAULT_HEADER_SIZE = 'scriptsize'
FULL_WIDTH = '\\textwidth'

# a float that must not move unless it spans both columns
NARROW_POSITION = 'H'
WIDE_POSITION = 't'

# chktex warning 24 fires on the space LaTeX ignores after \label
CHKTEX_SUPPRESSION = '% chktex 24'

# a header cell shorter than this collapses to its content width
SHORT_HEADER = 5

BARE_ZERO = re.compile(r'(?<![\d.])0\.')


def table(  # noqa: PLR0913
    *,
    spec: str,
    header_rows: list[list[str]],
    body_rows: list[list[str]],
    caption: str,
    label: str,
    wide: bool = False,
    prologue: list[str] | None = None,
    environment: str = DEFAULT_ENVIRONMENT,
    width: str | None = None,
    column_width_in: float | None = None,
    setup: str | None = None,
    style: str = DEFAULT_STYLE,
    chktex: bool = True,
) -> str:
    r"""Assemble one table as a LaTeX float.

    Arguments:
        spec: column specification, e.g. 'LRRCC' for tabulary or 'Xllrr' for tabularx.
        header_rows: one list of already-formatted cells per header line.
        body_rows: the data rows, cells already formatted as strings.
        caption: caption text, as LaTeX.
        label: the '\\label' value, e.g. 'tab:morph-curve'. Also the table's identity.
        wide: use 'table*', spanning both columns.
        prologue: raw lines inserted after the first header row, e.g. a '\\cmidrule'.
        environment: the tabular environment, e.g. 'tabulary', 'tabularx' or 'tabular'.
        width: explicit width for the environments that take one. Defaults to '\\textwidth' or column width.
        column_width_in: overrides the project's '\\columnwidth' for this call.
        setup: raw commands emitted inside the float, before the tabular begins.
        style: font commands applied inside the float.
        chktex: emit the chktex suppression comment after the label.

    Returns:
        The complete float, ending in a newline.

    """
    if not label:
        msg = 'a table needs a label: it is the name of the file written and what the paper inputs'
        raise ValueError(msg)

    float_environment = 'table*' if wide else 'table'
    position = WIDE_POSITION if wide else NARROW_POSITION

    if width is None:
        geometry = resolve(current_project().paper, column_width_in=column_width_in)
        narrow = not wide and environment != DEFAULT_ENVIRONMENT
        width = f'{geometry.column_width_in}in' if narrow else FULL_WIDTH
    sizing = f'{{{width}}}' if environment in SIZED_ENVIRONMENTS else ''

    lines = [
        f'\\begin{{{float_environment}}}[{position}]',
        ' \\centering',
        f' {style}',
        *([f' {setup}'] if setup else []),
        f' \\begin{{{environment}}}{sizing}{{{spec}}}',
        '  \\toprule',
    ]
    for index, row in enumerate(header_rows):
        lines.append('  ' + ' & '.join(row) + ' \\\\')
        if prologue and index == 0:
            lines += ['  ' + line for line in prologue]
    lines.append('  \\midrule')
    for row in body_rows:
        bare_rule = len(row) == 1 and row[0].strip() in {'\\midrule', '\\bottomrule', '\\toprule'}
        lines.append('  ' + ' & '.join(row) + ('' if bare_rule else ' \\\\'))
    lines += [
        '  \\bottomrule',
        f'  \\end{{{environment}}}',
        f'  \\caption{{{caption}}}',
        f'  \\label{{{label}}}' + (f'  {CHKTEX_SUPPRESSION}' if chktex else ''),
        f'\\end{{{float_environment}}}',
    ]
    return '\n'.join(lines) + '\n'


def header(text: str, expand: str | None = None, size: str = DEFAULT_HEADER_SIZE) -> str:
    r"""Format a header cell.

    Arguments:
        text: the heading.
        expand: padding placed either side of a heading shorter than 'SHORT_HEADER' characters, e.g. '~' or '~~~~'.
        size: the size command applied, without its backslash.

    Returns:
        The cell, as LaTeX.

    """
    padded = f'{expand}{text}{expand}' if expand and len(text) < SHORT_HEADER else text
    return f'\\{size}\\textbf{{{padded}}}'


def half_up(value: float, places: int = 2) -> str:
    """Round half away from zero, the way a reader expects and 'format' does not.

    Arguments:
        value: the number to round.
        places: decimal places to keep.

    Returns:
        The rounded number, as a string with exactly 'places' decimals.

    """
    quantum = Decimal(1).scaleb(-places)
    return str(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def bare(text: str) -> str:
    """Drop the leading zero from every number in 'text'.

    Arguments:
        text: formatted text, e.g. '0.82'.

    Returns:
        The text with leading zeroes removed, e.g. '.82'.

    """
    return BARE_ZERO.sub('.', text)


def dash_range(text: str, dash: str = '--') -> str:
    """Typeset a range with an en-dash.

    Arguments:
        text: a range written with a hyphen, e.g. '1337-1362'.
        dash: what to replace the hyphen with, e.g. '--' (an en-dash in LaTeX).

    Returns:
        The range, typeset.

    """
    return text.replace('-', dash)
