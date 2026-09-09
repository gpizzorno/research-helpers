"""Render a LaTeX table for reading, rather than typesetting it."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ['SYMBOLS', 'Row', 'Table', 'parse', 'show']

# environments that take a width argument before the column specification
SIZED = re.compile(
    r'\\begin\{(tabulary|tabularx|tabular\*)\}\{[^}]*\}\{([^}]*)\}(.*?)\\end\{\1\}',
    re.S,
)
# and those that do not
PLAIN = re.compile(
    r'\\begin\{(tabular|longtable)\}(?:\[[^\]]*\])?\{([^}]*)\}(.*?)\\end\{\1\}',
    re.S,
)

CAPTION = re.compile(r'\\caption\{(.*)\}\s*\\label', re.S)
LABEL = re.compile(r'\\label\{([^}]*)\}')
MULTICOLUMN = re.compile(r'\\multicolumn\{(\d+)\}\{([^}]*)\}\{(.*)\}', re.S)
# '&' separates columns, but '\&' is a literal ampersand and must not split the row
CELL_SEPARATOR = re.compile(r'(?<!\\)&')

# rules and colour commands
RULES = re.compile(r'\\(?:top|mid|bottom)rule|\\cmidrule(?:\([lr]+\))?\{[\d-]+\}|\\rowcolor\{[^}]*\}')
BREAKING = re.compile(r'\\midrule|\\bottomrule')

# size and font commands, dropped along with their effect
SIZES = re.compile(r'\\(?:scriptsize|footnotesize|normalsize|small|sffamily|rmfamily|centering)')
# wrappers whose braced argument is kept
WRAPPERS = re.compile(r'\\(?:textbf|emph|textit|texttt|normalsize|small)\{([^{}]*)\}')
SUBSCRIPT = re.compile(r'\$s_\{(\d+)\}\$')
SETLENGTH = re.compile(r'\\setlength\{[^}]*\}\{[^}]*\}')
REF = re.compile(r'\\ref\{(?:tab|sec|fig|eq):([^}]*)\}')
MATH = re.compile(r'\$([^$]*)\$')

# how many times to unwrap nested \textbf{\emph{...}} before giving up
UNWRAP_PASSES = 3

SYMBOLS: Mapping[str, str] = {
    r'$\le$': '\u2264',
    r'$\ge$': '\u2265',
    r'$\pm$': '\u00b1',
    r'$\times$': '\u00d7',
    r'$\Delta$': '\u0394',
    r'$R^2$': 'R\u00b2',
    r'\%': '%',
    r'\&': '&',
    r'\_': '_',
    r'\$': '$',
    '---': '\u2014',
    '--': '\u2013',
    '~': ' ',
}

STYLE = """<style>
.paper-table{border-collapse:collapse;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",
sans-serif;font-size:13px;margin:0.5em 0;line-height:1.5}
.paper-table th,.paper-table td{padding:3px 10px;border:none}
.paper-table thead tr:first-child th{border-top:1.5px solid currentColor}
.paper-table thead tr:last-child th{border-bottom:1px solid currentColor}
.paper-table tbody tr:last-child td{border-bottom:1.5px solid currentColor}
.paper-table tr.rule td{border-top:1px solid currentColor}
.paper-table tr.shaded{background:rgba(128,128,128,0.15)}
.paper-table th{font-weight:600;text-align:center}
.paper-table .l{text-align:left}.paper-table .r{text-align:right}.paper-table .c{text-align:center}
.paper-caption{font-size:12px;opacity:0.75;max-width:46em;margin:0.4em 0 1.2em;line-height:1.5}
.paper-caption b{opacity:0.9}
</style>"""

ALIGNMENTS = {'L': 'l', 'X': 'l', 'l': 'l', 'R': 'r', 'r': 'r', 'C': 'c', 'c': 'c'}


def _clean(cell: str, symbols: Mapping[str, str], strip: Iterable[re.Pattern[str]]) -> str:
    """Strip the typesetting from a cell and return the text."""
    text = RULES.sub('', SETLENGTH.sub('', cell))
    for pattern in strip:
        text = pattern.sub('', text)
    text = SUBSCRIPT.sub(r's\1', text)

    for _ in range(UNWRAP_PASSES):
        replaced = WRAPPERS.sub(r'\1', text)
        if replaced == text:
            break
        text = replaced
    text = SIZES.sub('', text)
    text = REF.sub(lambda match: f'“{match.group(1).replace("-", " ")}”', text)
    for source, target in symbols.items():
        text = text.replace(source, target)
    # anything left in maths mode is plain enough to read unwrapped
    text = MATH.sub(r'\1', text)
    return re.sub(r'\s+', ' ', text.replace('\\\\', '')).strip()


def _alignments(spec: str) -> list[str]:
    """Map a tabular column spec onto CSS classes."""
    return [ALIGNMENTS[char] for char in spec if char in ALIGNMENTS]


@dataclass
class Row:
    """A rendered row."""

    cells: list[tuple[str, int]]  # each cell as (text, colspan)
    rule: bool = False  # a horizontal rule sits above this row
    shaded: bool = False  # the row carried \rowcolor, i.e. the paper highlights it


@dataclass(repr=False)
class Table:
    """A parsed table, rendered as HTML in Jupyter and as text elsewhere."""

    header: list[Row]
    body: list[Row]
    align: list[str]
    caption: str = ''
    label: str = ''
    latex: str = field(default='', repr=False)

    @property
    def columns(self) -> int:
        """Return the column count of the widest row."""
        return max((sum(span for _, span in row.cells) for row in self.header + self.body), default=0)

    def _class(self, index: int) -> str:
        return self.align[index] if index < len(self.align) else 'l'

    def _repr_html_(self) -> str:
        """Render for Jupyter."""
        parts = [STYLE, '<table class="paper-table">']
        if self.header:
            parts.append('<thead>')
            for row in self.header:
                parts.append('<tr>')
                column = 0
                for text, span in row.cells:
                    span_attr = f' colspan="{span}"' if span > 1 else ''
                    parts.append(f'<th{span_attr} class="{self._class(column)}">{html.escape(text)}</th>')
                    column += span
                parts.append('</tr>')
            parts.append('</thead>')

        parts.append('<tbody>')
        for row in self.body:
            classes = ' '.join(c for c in ('rule' if row.rule else '', 'shaded' if row.shaded else '') if c)
            parts.append(f'<tr class="{classes}">' if classes else '<tr>')
            column = 0
            for text, span in row.cells:
                span_attr = f' colspan="{span}"' if span > 1 else ''
                parts.append(f'<td{span_attr} class="{self._class(column)}">{html.escape(text)}</td>')
                column += span
            parts.append('</tr>')
        parts += ['</tbody>', '</table>']

        if self.caption:
            number = self.label.removeprefix('tab:').replace('-', ' ')
            parts.append(f'<div class="paper-caption"><b>{html.escape(number)}.</b> {html.escape(self.caption)}</div>')
        return ''.join(parts)

    def _grid(self) -> list[list[str]]:
        """Expand every row to one entry per column."""
        width = self.columns
        grid = []
        for row in self.header + self.body:
            line: list[str] = []
            for text, span in row.cells:
                line += [text, *([''] * (span - 1))]
            grid.append((line + [''] * width)[:width])
        return grid

    def __str__(self) -> str:
        """Render for a terminal, as aligned plain text."""
        grid = self._grid()
        if not grid:
            return ''
        widths = [max(len(line[column]) for line in grid) for column in range(self.columns)]

        lines = []
        for position, (row, line) in enumerate(zip(self.header + self.body, grid, strict=True)):
            cells = [
                text.rjust(widths[column]) if self._class(column) == 'r' else text.ljust(widths[column])
                for column, text in enumerate(line)
            ]
            if position and (row.rule or position == len(self.header)):
                lines.append('-' * (sum(widths) + 2 * (len(widths) - 1)))
            lines.append('  '.join(cells).rstrip())
        return '\n'.join(lines)

    def __repr__(self) -> str:
        """Show the table."""
        return self.__str__()


def parse(
    latex: str,
    *,
    symbols: Mapping[str, str] | None = None,
    strip: Iterable[str] | None = None,
) -> Table:
    """Parse a LaTeX table into rows.

    Arguments:
        latex: a float or bare tabular environment ('tabulary', 'tabularx', 'tabular*', 'tabular', or 'longtable').
        symbols: replacements merged over 'SYMBOLS', for a project's own macros.
        strip: extra regular expressions removed from every cell before anything else.

    Returns:
        The parsed table.

    Raises:
        ValueError: if no recognised tabular environment is present.

    """
    found = SIZED.search(latex) or PLAIN.search(latex)
    if not found:
        msg = 'no tabulary, tabularx, tabular*, tabular, or longtable environment found.'
        raise ValueError(msg)

    spec, body = found.group(2), found.group(3)
    replacements = {**SYMBOLS, **(symbols or {})}
    patterns = [re.compile(pattern) for pattern in (strip or ())]

    header: list[Row] = []
    rows: list[Row] = []
    in_header = True
    pending_rule = False

    for chunk in body.split('\\\\'):
        if not chunk.strip():
            continue
        # a bare rule is written without a row terminator
        stripped = RULES.sub('', SETLENGTH.sub('', chunk)).strip()
        breaks = bool(BREAKING.search(chunk))
        if not stripped:
            pending_rule |= breaks
            continue

        if in_header and breaks:
            # the rule closing the header is a separator
            in_header = False
            breaks = False

        row = Row(cells=[], rule=pending_rule or breaks, shaded='\\rowcolor' in chunk)
        pending_rule = False
        for cell in CELL_SEPARATOR.split(chunk):
            span = MULTICOLUMN.search(cell)
            row.cells.append(
                (_clean(span.group(3), replacements, patterns), int(span.group(1)))
                if span
                else (_clean(cell, replacements, patterns), 1),
            )

        (header if in_header else rows).append(row)

    caption = CAPTION.search(latex)
    label = LABEL.search(latex)
    return Table(
        header=header,
        body=rows,
        align=_alignments(spec),
        caption=_clean(caption.group(1), replacements, patterns) if caption else '',
        label=label.group(1) if label else '',
        latex=latex,
    )


def show(
    latex: str,
    *,
    symbols: Mapping[str, str] | None = None,
    strip: Iterable[str] | None = None,
) -> Table:
    """Return a table in a form Jupyter renders and 'print' formats."""
    return parse(latex, symbols=symbols, strip=strip)
