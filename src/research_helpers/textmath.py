"""Set a float's inline maths as text, in the float's own typeface."""

# avoid ruff complaining about the glyphs
# ruff: noqa: RUF001, RUF002

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import NoReturn

__all__ = ['COMMANDS', 'DESIGNED_SCRIPT', 'PACKAGE', 'UnsupportedMathError', 'convert', 'to_text']

# the LaTeX package, without its '.sty'
PACKAGE = 'rhtextmath'

# every command defined by the package, which the output can use
COMMANDS = ('tmbar', 'tmmed', 'tmscripts', 'tmsub', 'tmsubx', 'tmsup', 'tmsupx', 'tmthick', 'tmthin')

# designed superiors and inferiors (OpenType 'sups' and 'subs')
DESIGNED_SCRIPT = frozenset('0123456789−+=()')


NUMBER = re.compile(r'\d+(?:\{,\}\d+)*(?:\.\d*)?|\.\d+')
COMMAND = re.compile(r'[A-Za-z]+')

GREEK_LOWER = {
    'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ϵ', 'varepsilon': 'ε', 'zeta': 'ζ',
    'eta': 'η', 'theta': 'θ', 'vartheta': 'ϑ', 'iota': 'ι', 'kappa': 'κ', 'lambda': 'λ', 'mu': 'μ', 'nu': 'ν',
    'xi': 'ξ', 'pi': 'π', 'varpi': 'ϖ', 'rho': 'ρ', 'varrho': 'ϱ', 'sigma': 'σ', 'varsigma': 'ς', 'tau': 'τ',
    'upsilon': 'υ', 'phi': 'ϕ', 'varphi': 'φ', 'chi': 'χ', 'psi': 'ψ', 'omega': 'ω',
}  # fmt: skip
GREEK_UPPER = {
    'Gamma': 'Γ', 'Delta': 'Δ', 'Theta': 'Θ', 'Lambda': 'Λ', 'Xi': 'Ξ', 'Pi': 'Π', 'Sigma': 'Σ',
    'Upsilon': 'Υ', 'Phi': 'Φ', 'Psi': 'Ψ', 'Omega': 'Ω',
}  # fmt: skip

# command -> (class, text). The classes are TeX's: ord, op, bin, rel, open, close, punct.
SYMBOLS: dict[str, tuple[str, str]] = {
    **{name: ('rel', glyph) for name, glyph in {
        'le': '≤', 'leq': '≤', 'ge': '≥', 'geq': '≥', 'ne': '≠', 'neq': '≠', 'approx': '≈', 'sim': '∼',
        'simeq': '≃', 'equiv': '≡', 'in': '∈', 'notin': '∉', 'propto': '∝', 'll': '≪', 'gg': '≫',
        'subset': '⊂', 'subseteq': '⊆', 'to': '→', 'rightarrow': '→', 'mid': '∣',
    }.items()},
    **{name: ('bin', glyph) for name, glyph in {
        'times': '×', 'cdot': '·', 'pm': '±', 'mp': '∓', 'div': '÷', 'ast': '∗', 'circ': '∘',
        'cup': '∪', 'cap': '∩', 'setminus': '∖',
    }.items()},
    **{name: ('ord', glyph) for name, glyph in {
        'infty': '∞', 'ldots': '…', 'dots': '…', 'cdots': '⋯', 'prime': '′', 'partial': '∂', 'ell': 'ℓ',
        'emptyset': '∅', 'vert': '|', 'lvert': '|', 'rvert': '|', 'Vert': '‖', 'lVert': '‖', 'rVert': '‖',
        '|': '‖', '%': '\\%', '#': '\\#', '&': '\\&', '$': '\\$', '_': '\\_',
    }.items()},
    'langle': ('open', '⟨'), 'rangle': ('close', '⟩'), '{': ('open', '\\{'), '}': ('close', '\\}'),
}  # fmt: skip
OPERATORS = frozenset({
    'arg', 'cos', 'det', 'exp', 'inf', 'lim', 'ln', 'log', 'max', 'min', 'sin', 'sup', 'tan',
})  # fmt: skip

# every command that is one atom: name -> (class, text, italic)
ATOMS: dict[str, tuple[str, str, bool]] = {
    **{name: ('ord', glyph, True) for name, glyph in GREEK_LOWER.items()},
    **{name: ('ord', glyph, False) for name, glyph in GREEK_UPPER.items()},
    **{name: (kind, glyph, False) for name, (kind, glyph) in SYMBOLS.items()},
    **{name: ('op', f'\\textup{{{name}}}', False) for name in OPERATORS},
}

# characters written directly: char -> (class, text)
CHARACTERS: dict[str, tuple[str, str]] = {
    '+': ('bin', '+'), '-': ('bin', '−'), '*': ('bin', '∗'), '=': ('rel', '='), '<': ('rel', '<'),
    '>': ('rel', '>'), ':': ('rel', ':'), '(': ('open', '('), '[': ('open', '['), ')': ('close', ')'),
    ']': ('close', ']'), '!': ('close', '!'), '?': ('close', '?'), '|': ('ord', '|'), '/': ('ord', '/'),
    '.': ('ord', '.'), ',': ('punct', ','), ';': ('punct', ';'), "'": ('ord', '′'),
    '−': ('bin', '−'), '×': ('bin', '×'), '·': ('bin', '·'), '±': ('bin', '±'), '≤': ('rel', '≤'),
    '≥': ('rel', '≥'), '≠': ('rel', '≠'), '≈': ('rel', '≈'), '∞': ('ord', '∞'), '…': ('ord', '…'),
}  # fmt: skip

# explicit spacing commands, written as text-mode spacing
SPACES = {
    ',': '\\tmthin{}', ':': '\\tmmed{}', '>': '\\tmmed{}', ';': '\\tmthick{}', ' ': '\\ ',
    'quad': '\\quad{}', 'qquad': '\\qquad{}',
}  # fmt: skip
# commands whose argument is text, set upright, italic, or bold
TEXT_COMMANDS = {
    'text': 'textup', 'textrm': 'textup', 'textup': 'textup', 'textnormal': 'textup', 'mathrm': 'textup',
    'textit': 'textit', 'mathit': 'textit', 'textbf': 'textbf', 'mathbf': 'textbf',
}  # fmt: skip
ACCENTS = {'bar': 'tmbar', 'overline': 'tmbar'}
# sizing commands that mean nothing in text: the delimiter after them is kept
IGNORED = frozenset({'left', 'right', 'big', 'Big', 'bigl', 'bigr', 'Bigl', 'Bigr', 'displaystyle', 'textstyle'})

# the space TeX puts between adjacent atoms: 0 none, 1 thin, 2 medium, 3 thick.
# a bracketed amount is not used
CLASSES = ('ord', 'op', 'bin', 'rel', 'open', 'close', 'punct')
SPACING_TABLE = """
         ord   op    bin   rel   open  close punct
ord      0     1     (2)   (3)   0     0     0
op       1     1     0     (3)   0     0     0
bin      (2)   (2)   0     0     (2)   0     0
rel      (3)   (3)   0     0     (3)   0     0
open     0     0     0     0     0     0     0
close    0     1     (2)   (3)   0     0     0
punct    (1)   (1)   0     (1)   (1)   (1)   (1)
"""
# ended by '{}' rather than a space, which would also swallow a space written after the maths
SPACE_COMMANDS = {1: '\\tmthin{}', 2: '\\tmmed{}', 3: '\\tmthick{}'}


def _spacing_table() -> dict[tuple[str, str], tuple[int, bool]]:
    """Read 'SPACING_TABLE' into (left, right) -> (amount)."""
    rows = [line.split() for line in SPACING_TABLE.strip().splitlines()[1:]]
    return {
        (row[0], right): (int(entry.strip('()')), not entry.startswith('('))
        for row in rows
        for right, entry in zip(CLASSES, row[1:], strict=True)
    }


SPACING = _spacing_table()


class UnsupportedMathError(ValueError):
    """Raised for maths outside the subset that can be set as text."""


@dataclass
class _Atom:
    """One of TeX's atoms: class, text, and scripts attached to it."""

    kind: str
    text: str
    italic: bool = False  # letters to be set in one \textit with their italic neighbours
    sub: str | None = None
    sup: str | None = None

    @property
    def scripted(self) -> bool:
        return self.sub is not None or self.sup is not None


@dataclass
class _Glue:
    """An explicit space, kept where it was written and ignored by the spacing between atoms."""

    text: str


Item = _Atom | _Glue


@dataclass
class _Parser:
    """Recursive descent over one expression."""

    expression: str
    position: int = 0
    items: list[Item] = field(default_factory=list)

    def fail(self, detail: str) -> NoReturn:
        """Raise the error for this expression."""
        msg = f'cannot set {self.expression!r} as text: {detail}'
        raise UnsupportedMathError(msg)

    def peek(self) -> str:
        """Return the next character, or '' at the end."""
        return self.expression[self.position : self.position + 1]

    def skip_spaces(self) -> None:
        """Skip whitespace, which TeX ignores in maths."""
        while self.peek().isspace():
            self.position += 1

    def parse(self, *, script: bool, group: bool = False) -> list[Item]:
        """Parse to the end of the expression or the group the parser is in."""
        items: list[Item] = []
        while True:
            self.skip_spaces()
            char = self.peek()
            if not char:
                if group:
                    self.fail('a group is not closed')
                return items
            if char == '}':
                if not group:
                    self.fail('a "}" closes no group')
                self.position += 1
                return items
            if char in '_^':
                if script:
                    self.fail('a script inside a script cannot be set as text')
                self.position += 1
                self.attach(items, char, self.argument(script=True))
                continue
            items.extend(self.item(script=script))

    def item(self, *, script: bool) -> list[Item]:
        """Parse one token, or one group."""
        number = NUMBER.match(self.expression, self.position)
        if number:
            self.position = number.end()
            return [_Atom('ord', number.group(0).replace('{,}', ','))]
        char = self.peek()
        self.position += 1
        if char == '{':
            return [_Atom('ord', render(self.parse(script=script, group=True), script=script))]
        if char == '\\':
            return self.command(script=script)
        if char == '~':
            return [_Glue('~')]
        return [self.character(char)]

    def character(self, char: str) -> _Atom:
        """Return the atom a character directly produces."""
        if (char.isascii() and char.isalpha()) or char in GREEK_LOWER.values():
            return _Atom('ord', char, italic=True)
        if char in GREEK_UPPER.values():
            return _Atom('ord', char)
        if char not in CHARACTERS:
            self.fail(f'{char!r} is not supported')
        return _Atom(*CHARACTERS[char])

    def command(self, *, script: bool) -> list[Item]:
        """Parse a command."""
        name = self.command_name()
        if name in ATOMS:
            kind, text, italic = ATOMS[name]
            return [_Atom(kind, text, italic=italic)]
        if name in SPACES:
            return [_Glue(SPACES[name])]
        if name in IGNORED:
            self.skip_spaces()
            if self.peek() == '.':  # the null delimiter of \left. or \right.
                self.position += 1
            return []
        return [self.with_argument(name, script=script)]

    def with_argument(self, name: str, *, script: bool) -> _Atom:
        """Return the atom produced by a command with an argument."""
        if name == 'operatorname':
            return _Atom('op', f'\\textup{{{self.raw_argument()}}}')
        if name in TEXT_COMMANDS:
            return _Atom('ord', f'\\{TEXT_COMMANDS[name]}{{{self.raw_argument()}}}')
        if name not in ACCENTS:
            self.fail(f'\\{name} is not supported')
        return _Atom('ord', f'\\{ACCENTS[name]}{{{render(self.argument(script=script), script=script)}}}')

    def command_name(self) -> str:
        """Read a command's name."""
        letters = COMMAND.match(self.expression, self.position)
        if letters:
            self.position = letters.end()
            return letters.group(0)
        char = self.peek()
        if not char:
            self.fail('it ends in a backslash')
        self.position += 1
        return char

    def argument(self, *, script: bool) -> list[Item]:
        """Parse one argument as maths."""
        self.skip_spaces()
        char = self.peek()
        if not char:
            self.fail('an argument is missing')
        if char == '{':
            self.position += 1
            return self.parse(script=script, group=True)
        if char.isdigit():  # TeX takes one token: x_10 is x_1 followed by 0
            self.position += 1
            return [_Atom('ord', char)]
        return self.item(script=script)

    def raw_argument(self) -> str:
        """Read one argument as text, without interpreting it."""
        self.skip_spaces()
        char = self.peek()
        if not char:
            self.fail('an argument is missing')
        if char != '{':
            self.position += 1
            return char
        depth, start = 0, self.position
        while self.position < len(self.expression):
            depth += {'{': 1, '}': -1}.get(self.expression[self.position], 0)
            self.position += 1
            if depth == 0:
                break
        else:
            self.fail('a group is not closed')
        return self.expression[start + 1 : self.position - 1]

    def attach(self, items: list[Item], which: str, script: list[Item]) -> None:
        """Attach a script to the atom before it, or to an empty one if there is none."""
        base = items[-1] if items and isinstance(items[-1], _Atom) else None
        if base is None:
            base = _Atom('ord', '')
            items.append(base)
        slot = 'sub' if which == '_' else 'sup'
        if getattr(base, slot) is not None:
            self.fail(f'a double {"subscript" if slot == "sub" else "superscript"}')
        setattr(base, slot, _script(render(script, script=True), slot))


def _script(text: str, slot: str) -> str:
    """Return a rendered script in the macro that sets it, using designed glyphs where possible, else scaled."""
    designed = bool(text) and set(text) <= DESIGNED_SCRIPT
    return f'\\tm{slot}{"" if designed else "x"}{{{text}}}'


def _classify(atoms: list[_Atom]) -> None:
    """Turn a binary operator with nothing to operate on into an ordinary atom."""
    for index, atom in enumerate(atoms):
        previous = atoms[index - 1] if index else None
        if atom.kind == 'bin' and (previous is None or previous.kind in {'bin', 'op', 'rel', 'open', 'punct'}):
            atom.kind = 'ord'
        if atom.kind in {'rel', 'close', 'punct'} and previous is not None and previous.kind == 'bin':
            previous.kind = 'ord'
    if atoms and atoms[-1].kind == 'bin':
        atoms[-1].kind = 'ord'


def _merge(items: list[Item]) -> list[Item]:
    r"""Join runs of italic letters into one atom, so that they share one \textit and kern as a word."""
    merged: list[Item] = []
    for item in items:
        last = merged[-1] if merged else None
        if isinstance(item, _Atom) and isinstance(last, _Atom) and item.italic and last.italic and not last.scripted:
            last.text += item.text
            last.sub, last.sup = item.sub, item.sup
            continue
        merged.append(item)
    return merged


def render(items: list[Item], *, script: bool) -> str:
    """Return parsed items as text, with TeX's spacing between atoms.

    Arguments:
        items: the list of parsed items.
        script: whether the items are part of a script, affecting spacing.

    Returns:
        The text-mode LaTeX.

    """
    _classify([item for item in items if isinstance(item, _Atom)])
    pieces: list[str] = []
    previous: _Atom | None = None
    for item in _merge(items):
        if isinstance(item, _Glue):
            pieces.append(item.text)
            continue
        if previous is not None:
            amount, everywhere = SPACING[previous.kind, item.kind]
            if amount and (everywhere or not script):
                pieces.append(SPACE_COMMANDS[amount])
        pieces.append(_body(item))
        previous = item
    return ''.join(pieces)


def _body(atom: _Atom) -> str:
    """Return one atom as text, scripts included."""
    text = f'\\textit{{{atom.text}}}' if atom.italic else atom.text
    if atom.sub is not None and atom.sup is not None:
        return f'{text}\\tmscripts{{{atom.sub}}}{{{atom.sup}}}'
    return text + (atom.sub or '') + (atom.sup or '')


def to_text(expression: str) -> str:
    r"""Rewrite one maths expression as text set by ``rhtextmath.sty``.

    The supported subset: Latin letters, numbers (with ``{,}`` as a thousands separator), Greek letters, the
    common relations (``= < > \le \ge \ne \approx \sim \in \propto``, and a few more), binary operators
    (``+ - \times \cdot \pm``), operator names (``\log \max \min \exp``, ``\operatorname{...}``), text
    (``\text \mathrm \mathit \mathbf``), one level of sub- and superscript, ``\bar``, absolute-value bars,
    brackets, and explicit spacing. ``\left`` and ``\right`` are dropped and their delimiters kept.

    Arguments:
        expression: the maths, without its delimiters, e.g. ``'Q_{ov}'`` or ``'9.8\times 10^{-4}'``.

    Returns:
        Text-mode LaTeX, e.g. ``'\textit{Q}\tmsubx{\textit{ov}}'`` or ``'9.8\tmmed{}×\tmmed{}10\tmsup{−4}'``.

    Raises:
        UnsupportedMathError: if the expression uses anything outside the subset.

    """
    return render(_Parser(expression).parse(script=False), script=False)


def convert(latex: str) -> str:
    r"""Rewrite every inline maths expression in a piece of LaTeX as text.

    Both ``\(...\)`` and ``$...$`` are converted. A backslash is read with the character after it, as TeX
    reads it, so an escaped ``\$`` or the ``\\`` of a line break before a parenthesis opens no maths. Display
    maths is left alone.

    Arguments:
        latex: a cell, a caption, or a whole float.

    Returns:
        The same LaTeX, with no inline maths left in it.

    Raises:
        UnsupportedMathError: if any expression uses anything outside the subset 'to_text' supports, or is not closed.

    """
    pieces: list[str] = []
    position = 0
    while position < len(latex):
        pair = latex[position : position + 2]
        if pair in {'\\(', '$$'} or latex[position] == '$':
            opening = pair if pair in {'\\(', '$$'} else '$'
            closing = {'\\(': '\\)', '$$': '$$', '$': '$'}[opening]
            start = position + len(opening)
            end = _closing(latex, start, closing)
            expression = latex[start:end]
            pieces.append(latex[position : end + len(closing)] if opening == '$$' else to_text(expression))
            position = end + len(closing)
        elif latex[position] == '\\':
            pieces.append(pair)  # a command's backslash, an escaped character, or a line break
            position += len(pair)
        else:
            pieces.append(latex[position])
            position += 1
    return ''.join(pieces)


def _closing(latex: str, start: int, delimiter: str) -> int:
    """Return the position where the maths expression starting at 'start' closes."""
    position = start
    while position < len(latex):
        if latex.startswith(delimiter, position):
            return position
        position += 2 if latex[position] == '\\' else 1
    msg = f'cannot set {latex[start:]!r} as text: the maths is not closed'
    raise UnsupportedMathError(msg)
