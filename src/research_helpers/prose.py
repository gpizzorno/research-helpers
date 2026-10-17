r"""Pin every number a document states in the prose to the data it comes from.

This module is a registry for typed numbers: each entry is a fragment of a sentence as the
document prints it, with '{}' where a number goes, and a function that computes the numbers
from the data. The check then reads the document and reports every fragment that no longer
says what the data contains.

    prose = ProseRegistry()

    @prose.register('mean-k', 'OSLOM finds {} communities on average', source='runs/oslom.json')
    def mean_k():
        return (f'{load_runs().mean_k:.1f}',)

An entry whose printed numbers are knowingly wrong, pending a correction to the text, is listed in
'known_discrepancies' with what the data contains. The check then requires that the sentence is still
there and still wrong. Once the text is corrected it fails until the entry leaves the list.

'audit' classifies every numeric token in a document's prose, to find the numbers that still need
an entry.
"""

from __future__ import annotations

import argparse
import bisect
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from string import Formatter
from typing import TYPE_CHECKING, Any, NamedTuple, TypeVar

from research_helpers.project import PAPER_DOCUMENT, current_project

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator, Mapping, Sequence

ValuesT = TypeVar('ValuesT', bound='Callable[[], Sequence[Any]]')

__all__ = [
    'Mismatch',
    'Occurrence',
    'ProseCheck',
    'ProseNumber',
    'ProseRegistry',
    'audit',
    'audit_report',
    'normalise_prose',
]

# a LaTeX comment: a '%' not escaped as '\%'
COMMENT = re.compile(r'(?<!\\)%.*')

# a numeric token: 1,234 or 1\,234 (thousands), or an integer or decimal, not part of a longer word
NUMBER = re.compile(r'(?<![\w.])(\d{1,3}(?:,\d{3})+|\d{1,3}(?:\\,\d{3})+|\d+(?:\.\d+)?)(?!\w)')

# commands whose arguments are addresses or names, never prose numbers
SKIPPED_COMMANDS = (
    'autocite',
    'textcite',
    'parencite',
    'cite',
    'citep',
    'citet',
    'label',
    'ref',
    'eqref',
    'cref',
    'Cref',
    'autoref',
    'input',
    'include',
    'includegraphics',
    'url',
    'href',
    'begin',
    'end',
    'hspace',
    'vspace',
    'footnotetext',
)

# display-math environments
DISPLAY_MATH = (
    r'\\\[.*?\\\]',
    r'\\begin\{align\*?\}.*?\\end\{align\*?\}',
    r'\\begin\{equation\*?\}.*?\\end\{equation\*?\}',
)

# an inline formula holding one of these computes something
FORMULA_MARKS = ('/', '\\binom', '\\times', '\\sum', '\\frac', '\\cdot', '\\in')

# the relations by which an inline formula sets a parameter to a value
RELATIONS = r'(=|\\le|\\leq|\\ge|\\geq|<|>|\\in)'

# the order in which an audit reports
CATEGORIES = {
    'untraced': 'Untraced',
    'other-float': 'In a float the paragraph does not cite',
    'cited-float': 'In a float the paragraph cites',
    'notation': 'A parameter or a formula constant',
    'registered': 'Registered',
}

# a token this short is too common to say anything by appearing in an uncited float
SHORTEST_TELLING_TOKEN = 4

# how much text either side of a token an audit shows
CONTEXT_BEFORE, CONTEXT_AFTER = 70, 50


def normalise_prose(text: str) -> str:
    """Return a manuscript as the registry matches against it: comments removed, whitespace collapsed.

    A sentence that has been commented out no longer counts as printed.
    """
    uncommented = '\n'.join(COMMENT.sub('', line) for line in text.splitlines())
    return ' '.join(uncommented.split())


def _fields(template: str) -> list[tuple[str, bool]]:
    """Split a template into its literal stretches, each followed by whether a number comes after it."""
    return [(literal, name is not None) for literal, name, _spec, _conversion in Formatter().parse(template)]


def _flexible(literal: str) -> str:
    """Return a pattern matching 'literal' with any run of whitespace where it has whitespace.

    Whitespace at either end is kept, so 'found ' does not match the start of 'founder'.
    """
    pieces = [re.escape(piece) for piece in literal.split()]
    if not pieces:
        return r'\s+' if literal else ''
    lead = r'\s+' if literal[0].isspace() else ''
    trail = r'\s+' if literal[-1].isspace() else ''
    return lead + r'\s+'.join(pieces) + trail


@dataclass(frozen=True)
class ProseNumber:
    r"""One fragment of a sentence as the document prints it, and how to compute its numbers.

    'template' is the fragment with '{}' where each number goes and doubled braces for literal
    ones, so '\(Q_{{ov}} = {}\)'. Whitespace is immaterial: the fragment and the document are
    both compared with every run of whitespace collapsed to one space.
    """

    key: str
    template: str
    values: Callable[[], Sequence[Any]]  # the numbers, formatted as printed, one per '{}'
    source: str = ''  # where the numbers come from, for whoever has to fix a mismatch
    section: str = ''  # where the sentence is, likewise
    document: str = PAPER_DOCUMENT  # the document that prints it

    @property
    def placeholders(self) -> int:
        """Return the count of numbers the template takes."""
        return sum(follows for _literal, follows in _fields(self.template))

    def expected(self) -> str:
        """Return the fragment with the numbers from the data.

        Raises:
            ValueError: if the values do not fill the template exactly.

        """
        values = tuple(self.values())
        if len(values) != self.placeholders:
            msg = f'{self.key}: {len(values)} value(s) for {self.placeholders} placeholder(s)'
            raise ValueError(msg)
        return ' '.join(self.template.format(*values).split())

    def pattern(self) -> re.Pattern[str]:
        """Return a pattern matching the fragment whatever numbers it carries.

        Used to find what the document prints when it does not print what the data contains. A number
        is matched as a run without whitespace, so a sentence that now says something else entirely
        does not pass for the same sentence with different numbers.
        """
        fields = _fields(self.template)
        parts = []
        for position, (literal, follows) in enumerate(fields):
            parts.append(_flexible(literal))
            if follows:
                # a number with fixed text after it stops at that text; a number at either edge of
                # the template has nothing to stop it but the next space
                interior = position < len(fields) - 1 and (position > 0 or bool(literal))
                parts.append(r'(\S+?)' if interior else r'(\S+)')
        return re.compile(''.join(parts))

    def longest_literal(self) -> str:
        """Return the longest stretch of fixed text, which must appear for the sentence to count as there."""
        return max((' '.join(literal.split()) for literal, _follows in _fields(self.template)), key=len)


class Mismatch(NamedTuple):
    """A fragment the document does not print as is in the data."""

    key: str
    section: str
    expected: str
    printed: str | None  # what the document prints in its place, or None if the sentence is gone


class ProseCheck(NamedTuple):
    """What a check of the registry against its documents found."""

    checked: int  # entries compared
    stale: list[Mismatch]  # the sentence is there, the numbers are not the data's
    vanished: list[Mismatch]  # the sentence is no longer in the document at all
    fixed: list[str]  # known discrepancies the text now corrects; remove them from the list
    orphaned: list[str]  # known discrepancies that name no entry
    failed: list[tuple[str, str]]  # entries whose numbers could not be computed, with why
    open_discrepancies: int  # known discrepancies still standing, as expected

    def __bool__(self) -> bool:
        """Report whether anything needs attention."""
        return bool(self.stale or self.vanished or self.fixed or self.orphaned or self.failed)


@dataclass
class Occurrence:
    """One numeric token in a document's prose, and what accounts for it."""

    line: int
    token: str
    context: str
    category: str  # a key of 'CATEGORIES'
    detail: str = ''  # the registry key, the kind of formula, or the floats carrying it
    start: int = field(default=0, repr=False)


class ProseRegistry:
    """The numbers a project's documents state in prose, and their checks."""

    def __init__(
        self,
        *,
        known_discrepancies: Mapping[str, str] | None = None,
        untraced: Mapping[str, str] | None = None,
        parameter_symbols: Collection[str] = (),
    ) -> None:
        r"""Create an empty registry.

        Arguments:
            known_discrepancies: entry key to what the data contains, for each sentence knowingly wrong
                pending a correction to the text.
            untraced: numbers in the prose with no source to compute them from, by reason.
            parameter_symbols: inline-math symbols whose assignment sets a parameter rather than
                reports a result, e.g. '\mu' for '\(\mu = 0.4\)'.

        """
        self._entries: dict[str, ProseNumber] = {}
        self.known_discrepancies = dict(known_discrepancies or {})
        self.untraced = dict(untraced or {})
        self.parameter_symbols = tuple(parameter_symbols)

    def add(self, *entries: ProseNumber) -> None:
        """Register entries built directly.

        Raises:
            ValueError: if a key is already registered.

        """
        for entry in entries:
            if entry.key in self._entries:
                msg = f'{entry.key!r} is already registered'
                raise ValueError(msg)
            self._entries[entry.key] = entry

    def register(
        self,
        key: str,
        template: str,
        *,
        source: str = '',
        section: str = '',
        document: str = PAPER_DOCUMENT,
    ) -> Callable[[ValuesT], ValuesT]:
        """Register the decorated function that computes the numbers of a fragment.

        Arguments:
            key: a short, unique name for the entry.
            template: the fragment as printed, '{}' for each number.
            source: where the numbers come from.
            section: where the sentence is.
            document: the document.

        Returns:
            The decorator, which returns the function unchanged.

        """

        def decorator(values: ValuesT) -> ValuesT:
            self.add(ProseNumber(key, template, values, source=source, section=section, document=document))
            return values

        return decorator

    def __len__(self) -> int:
        """Return how many entries are registered."""
        return len(self._entries)

    def __iter__(self) -> Iterator[ProseNumber]:
        """Iterate the entries in registration order."""
        return iter(self._entries.values())

    def __contains__(self, key: object) -> bool:
        """Report whether 'key' is registered."""
        return key in self._entries

    def __getitem__(self, key: str) -> ProseNumber:
        """Return one entry by key."""
        return self._entries[key]

    @property
    def documents(self) -> list[str]:
        """Return the documents the entries name, in the order first named."""
        return list(dict.fromkeys(entry.document for entry in self))

    def check(
        self,
        paths: Mapping[str, Path | str] | None = None,
        *,
        document: str | None = None,
    ) -> ProseCheck:
        """Compare every entry against the document that prints it.

        Arguments:
            paths: document name to manuscript, for any document not to be taken from the project's wiring.
            document: check only the entries this document prints.

        Returns:
            What was found or falsy when every entry holds.

        Raises:
            FileNotFoundError: if a manuscript does not exist.
            KeyError: if an entry names a document the project does not configure.

        """
        entries = [entry for entry in self if document is None or entry.document == document]
        texts = _read_documents(dict.fromkeys(entry.document for entry in entries), paths or {})

        stale, vanished, fixed, failed = [], [], [], []
        open_discrepancies = 0
        for entry in entries:
            text = texts[entry.document]
            try:
                expected = entry.expected()
            except Exception as error:  # noqa: BLE001
                failed.append((entry.key, f'{type(error).__name__}: {error}'))
                continue

            printed = entry.pattern().search(text)
            if entry.key in self.known_discrepancies:
                if expected in text:
                    fixed.append(entry.key)
                elif printed is None and entry.longest_literal() not in text:
                    vanished.append(Mismatch(entry.key, entry.section, expected, None))
                else:
                    open_discrepancies += 1
                continue

            if expected in text:
                continue
            if printed is None:
                vanished.append(Mismatch(entry.key, entry.section, expected, None))
            else:
                stale.append(Mismatch(entry.key, entry.section, expected, printed.group(0)))

        orphaned = sorted(set(self.known_discrepancies) - set(self._entries))
        return ProseCheck(
            checked=len(entries),
            stale=stale,
            vanished=vanished,
            fixed=fixed,
            orphaned=orphaned,
            failed=failed,
            open_discrepancies=open_discrepancies,
        )

    def report(self, found: ProseCheck) -> str:
        """Return a description of what the check found."""
        noted = f' ({found.open_discrepancies} known discrepancies still open)' if found.open_discrepancies else ''
        if not found:
            return f'OK: all {found.checked} prose numbers are current{noted}\n'
        lines = [*_problems(found), f'{found.checked} checked{noted}. To fix: ' + ', then '.join(_remedies(found))]
        return '\n'.join(lines) + '\n'

    def audit(self, document: str = PAPER_DOCUMENT, path: Path | str | None = None) -> list[Occurrence]:
        """Classify every numeric token in a document's prose.

        Arguments:
            document: target document.
            path: its manuscript, if not to be taken from the project's wiring.

        Returns:
            Every token, in document order.

        """
        settings = current_project().document(document)
        manuscript = Path(path) if path is not None else settings.main
        return audit(
            manuscript.read_text(encoding='utf-8'),
            [entry for entry in self if entry.document == document],
            tables_dir=settings.tables_dir,
            parameter_symbols=self.parameter_symbols,
        )

    def main(self, argv: list[str] | None = None) -> int:
        """Run the prose command line.

        Arguments:
            argv: command line arguments, or None to read 'sys.argv'.

        Returns:
            A process exit status: 0 on success, 1 if the check found anything.

        """
        parser = argparse.ArgumentParser(description='Check the numbers stated in the prose against the data.')
        parser.add_argument('--list', action='store_true', help='list what is registered')
        parser.add_argument('--document', default=None, help='only this document (default: every one)')
        parser.add_argument('--audit', action='store_true', help="classify every number in a document's prose")
        parser.add_argument('--out', type=Path, default=None, help='write the audit here rather than to stdout')
        args = parser.parse_args(argv)

        if args.list:
            width = max((len(entry.key) for entry in self), default=0)
            for entry in self:
                if args.document in (None, entry.document):
                    where = f'{entry.document} {entry.section}'.strip()
                    print(f'  {entry.key:<{width}}  {where:<24}  {entry.source}')
            return 0

        if args.audit:
            name = args.document or PAPER_DOCUMENT
            try:
                found = self.audit(name)
            except (FileNotFoundError, KeyError) as error:
                print(_message(error), file=sys.stderr)
                return 1
            markdown = audit_report(found, title=f'Prose-number audit: {name}')
            if args.out is None:
                print(markdown, end='')
            else:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(markdown, encoding='utf-8')
                print(f'wrote {args.out}')
            return 0

        try:
            result = self.check(document=args.document)
        except (FileNotFoundError, KeyError) as error:
            print(_message(error), file=sys.stderr)
            return 1
        print(self.report(result), end='')
        return 1 if result else 0


def _problems(found: ProseCheck) -> list[str]:
    """Describe each thing a check found."""
    lines = []
    for mismatch in found.stale:
        where = f' [{mismatch.section}]' if mismatch.section else ''
        lines += [
            f'stale{where} {mismatch.key}:',
            f'    prints     {mismatch.printed}',
            f'    data contains  {mismatch.expected}',
        ]
    for mismatch in found.vanished:
        where = f' [{mismatch.section}]' if mismatch.section else ''
        lines.append(f'not found{where} {mismatch.key}: {mismatch.expected}')
    lines += [f'could not compute {key}: {reason}' for key, reason in found.failed]
    if found.fixed:
        lines.append(f'corrected in the text, still listed as known discrepancies: {", ".join(found.fixed)}')
    if found.orphaned:
        lines.append(f'known discrepancies naming no entry: {", ".join(found.orphaned)}')
    return lines


def _remedies(found: ProseCheck) -> list[str]:
    """Return what to do, only for what a check actually found."""
    remedies = []
    if found.stale:
        remedies.append('correct the text, or list the entry as a known discrepancy')
    if found.vanished:
        remedies.append('update the template to the sentence as it now reads, or remove the entry')
    if found.failed:
        remedies.append('produce the data the entry reads')
    if found.fixed or found.orphaned:
        remedies.append('remove them from the known discrepancies')
    return remedies


def _message(error: Exception) -> str:
    """Return an error's message without the quotes."""
    return error.args[0] if error.args else str(error)


def _read_documents(names: Mapping[str, None], paths: Mapping[str, Path | str]) -> dict[str, str]:
    """Read and normalise each named document, from 'paths' or else the project's wiring."""
    texts = {}
    for name in names:
        path = Path(paths[name]) if name in paths else current_project().document(name).main
        if not path.exists():
            msg = f'no manuscript at {path} for the document {name!r}, so there is nothing to check against'
            raise FileNotFoundError(msg)
        texts[name] = normalise_prose(path.read_text(encoding='utf-8'))
    return texts


def _not_prose(text: str) -> Iterator[tuple[int, int]]:
    """Yield the spans of a manuscript that are not prose."""
    yield from (match.span() for match in COMMENT.finditer(text))
    for command in SKIPPED_COMMANDS:
        yield from (match.span() for match in re.finditer(r'\\' + command + r'\*?(\[[^\]]*\])*\{[^}]*\}', text))
    # \autocites[pre][post]{key}[pre][post]{key}...: every bracket and brace of the chain
    yield from (match.span() for match in re.finditer(r'\\autocites(\s*(\[[^\]]*\])*\s*\{[^}]*\})+', text))
    for pattern in DISPLAY_MATH:
        yield from (match.span() for match in re.finditer(pattern, text, re.DOTALL))
    # a formula's own constants: superscripts, subscripts, fraction and root arguments
    formula = r'(\^|_)\{?-?\d+\}?|\\frac\{[^}]*\}\{[^}]*\}|\\sqrt\{[^}]*\}'
    yield from (match.span() for match in re.finditer(formula, text))
    # the preamble: prose starts at the abstract, or else at the document's body
    for opening in ('\\begin{abstract}', '\\begin{document}'):
        if opening in text:
            yield 0, text.index(opening)
            return


def _masked(text: str) -> str:
    """Blank every span of a manuscript that is not prose, preserving offsets and line breaks."""
    out = list(text)
    for start, end in _not_prose(text):
        for position in range(start, end):
            if out[position] != '\n':
                out[position] = ' '
    return ''.join(out)


def _inline_kind(text: str, start: int, parameter: re.Pattern[str] | None) -> str | None:
    """Return 'parameter' or 'formula' for a token inside an inline formula, else None."""
    opening, closing = text.rfind('\\(', 0, start), text.find('\\)', start)
    if opening < 0 or closing < 0 or text.rfind('\\)', opening, start) >= 0:
        return None
    if parameter is not None and parameter.match(text[opening:start]):
        return 'parameter'
    span = text[opening:closing]
    return 'formula' if any(mark in span for mark in FORMULA_MARKS) else None


def _parameter_pattern(symbols: Collection[str]) -> re.Pattern[str] | None:
    """Match an inline formula, up to a number, that assigns a declared parameter symbol."""
    if not symbols:
        return None
    alternatives = '|'.join(re.escape(symbol) for symbol in sorted(symbols, key=len, reverse=True))
    return re.compile(r'^\\\(\s*(' + alternatives + r')\s*' + RELATIONS + r'\s*\[?\s*$')


def _registered_spans(text: str, entries: Sequence[ProseNumber]) -> list[tuple[int, int, str]]:
    """Return where each registered fragment sits in the raw text."""
    spans = []
    for entry in entries:
        # the template's own spaces, made flexible, also match the raw text's line breaks
        spans += [(match.start(), match.end(), entry.key) for match in entry.pattern().finditer(text)]
    return spans


def audit(
    text: str,
    entries: Sequence[ProseNumber] = (),
    *,
    tables_dir: Path | str | None = None,
    parameter_symbols: Collection[str] = (),
) -> list[Occurrence]:
    r"""Classify every numeric token in a manuscript's prose.

    Each token falls in the first category that accounts for it:

    1. **registered**: it lies inside a fragment one of the entries describes.
    2. **notation**: it is a constant of an inline formula, or a parameter's value in one that
       assigns a declared parameter symbol. Not a result.
    3. **cited-float**: it appears in a generated table the same paragraph cites, which carries it.
    4. **other-float**: it appears in a generated table the paragraph does not cite.
    5. **untraced**: none of the above. These are the numbers to pin.

    Numbers in the preamble, comments, display math, citations, labels, references and the
    arguments of '\input' and '\includegraphics' are not prose and are skipped.

    Arguments:
        text: the manuscript, as written.
        entries: the registry entries for this manuscript.
        tables_dir: where its generated tables are, named by label without the 'tab:' prefix.
        parameter_symbols: see 'ProseRegistry'.

    Returns:
        Every token, in document order.

    """
    masked = _masked(text)
    parameter = _parameter_pattern(parameter_symbols)
    directory = Path(tables_dir) if tables_dir is not None else None
    tables = (
        {path.stem: path.read_text(encoding='utf-8') for path in directory.glob('*.tex')}
        if directory is not None and directory.is_dir()
        else {}
    )
    spans = _registered_spans(text, entries)
    paragraph_breaks = [match.start() for match in re.finditer(r'\n[ \t]*\n', masked)]

    found = []
    for match in NUMBER.finditer(masked):
        start, end = match.span()
        token = match.group(1)
        index = bisect.bisect_left(paragraph_breaks, start)
        opening = paragraph_breaks[index - 1] if index else 0
        closing = paragraph_breaks[index] if index < len(paragraph_breaks) else len(text)
        paragraph = text[opening:closing]
        cited = re.findall(r'\\(?:ref|cref|Cref|autoref)\{tab:([^}]+)\}', paragraph)

        category, detail = 'untraced', ''
        keys = [key for low, high, key in spans if low <= start < high]
        kind = _inline_kind(text, start, parameter)
        carrying = [name for name in cited if token in tables.get(name, '')]
        elsewhere = [
            name
            for name, body in tables.items()
            if name not in cited and len(token) >= SHORTEST_TELLING_TOKEN and token in body
        ]
        if keys:
            category, detail = 'registered', ', '.join(keys)
        elif kind:
            category, detail = 'notation', kind
        elif carrying:
            category, detail = 'cited-float', ', '.join(carrying)
        elif elsewhere:
            category, detail = 'other-float', ', '.join(elsewhere)

        found.append(
            Occurrence(
                line=text.count('\n', 0, start) + 1,
                token=token,
                context=' '.join(text[max(0, start - CONTEXT_BEFORE) : end + CONTEXT_AFTER].split()),
                category=category,
                detail=detail,
                start=start,
            ),
        )
    return found


def audit_report(occurrences: Sequence[Occurrence], *, title: str = 'Prose-number audit') -> str:
    """Render an audit as Markdown, untraced numbers first.

    Arguments:
        occurrences: what 'audit' found.
        title: the heading.

    Returns:
        The report.

    """
    by_category: dict[str, list[Occurrence]] = {category: [] for category in CATEGORIES}
    for occurrence in occurrences:
        by_category[occurrence.category].append(occurrence)

    counts = ', '.join(f'**{len(by_category[c])}** {CATEGORIES[c].lower()}' for c in CATEGORIES)
    lines = [f'# {title}', '', f'{len(occurrences)} numeric tokens in the prose: {counts}.', '']
    for category, heading in CATEGORIES.items():
        lines += [f'## {heading}', '']
        if not by_category[category]:
            lines += ['None.', '']
            continue
        lines += ['| Line | Token | Detail | Context |', '|---|---|---|---|']
        lines += [
            f'| {o.line} | `{o.token}` | {o.detail} | {o.context.replace("|", "/")} |' for o in by_category[category]
        ]
        lines.append('')
    return '\n'.join(lines)
