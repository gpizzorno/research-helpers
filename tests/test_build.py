"""The artefact registry, the build/install pipeline, and the checks."""

from __future__ import annotations

import pytest

from research_helpers.build import FIGURES, TABLES, Document, Drift, Registry
from research_helpers.project import PaperSettings, _load
from research_helpers.prose import ProseNumber, ProseRegistry

PAPER = r"""
\documentclass{article}
\begin{document}

Scores are in Table~\ref{tab:scores}.
\input{tables/scores}

\begin{figure}
  \includegraphics[width=\textwidth]{figures/curve}
  \caption{A curve.}
  \label{fig:curve}
\end{figure}

\end{document}
"""

SCORES = '\\begin{table}[H]\n \\centering\n Model & F1 \\\\\n \\label{tab:scores}\n\\end{table}\n'
CURVE = b'\x89PNG\r\n\x1a\n fake image bytes'


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
def tables():
    """Return a registry with one table emitter."""
    registry = Registry(TABLES)

    @registry.register('tab:scores')
    def scores() -> str:
        """Model scores."""
        return SCORES

    return registry


@pytest.fixture
def figures():
    """Return a registry with one figure emitter."""
    registry = Registry(FIGURES)

    @registry.register('fig:curve')
    def curve() -> bytes:
        return CURVE

    return registry


@pytest.fixture
def paper(tmp_path):
    """Return a written-out paper, and the directory it reads artefacts from."""
    manuscript = tmp_path / 'paper.tex'
    manuscript.write_text(PAPER, encoding='utf-8')
    return manuscript


# --- registration -----------------------------------------------------------------------------


def test_an_emitter_stays_callable_after_registration(tables):
    assert tables['tab:scores'].emitter() == SCORES


def test_the_description_falls_back_to_the_docstring(tables):
    assert tables['tab:scores'].description == 'Model scores.'


def test_metadata_is_kept_for_the_project_to_use():
    registry = Registry(TABLES)

    @registry.register('tab:x', description='A table', wide=True, source='corpus.json')
    def emit() -> str:
        return ''

    assert registry['tab:x'].metadata == {'wide': True, 'source': 'corpus.json'}
    assert registry['tab:x'].description == 'A table'


def test_a_label_must_carry_the_kinds_prefix():
    registry = Registry(TABLES)

    with pytest.raises(ValueError, match="must start with 'tab:'"):

        @registry.register('scores')
        def emit() -> str:
            return ''


def test_a_label_cannot_be_registered_twice(tables):
    with pytest.raises(ValueError, match='already registered'):

        @tables.register('tab:scores')
        def emit() -> str:
            return ''


def test_a_registry_reports_its_contents(tables):
    assert len(tables) == 1
    assert tables.labels == ['tab:scores']
    assert 'tab:scores' in tables
    assert [a.label for a in tables] == ['tab:scores']


# --- building and installing ------------------------------------------------------------------


def test_the_filename_is_the_label_without_its_prefix(tables, tmp_path):
    written = tables.write_all(tmp_path / 'build')

    assert [p.name for p in written] == ['scores.tex']
    assert written[0].read_text(encoding='utf-8') == SCORES


def test_a_binary_kind_is_written_as_bytes(figures, tmp_path):
    written = figures.write_all(tmp_path / 'build')

    assert written[0].name == 'curve.png'
    assert written[0].read_bytes() == CURVE


def test_install_copies_the_built_artefacts(tables, tmp_path):
    tables.write_all(tmp_path / 'build')

    copied = tables.install(tmp_path / 'tex' / 'tables', source=tmp_path / 'build')

    assert copied[0].read_text(encoding='utf-8') == SCORES


def test_installing_before_building_says_so(tables, tmp_path):
    with pytest.raises(FileNotFoundError, match='Build the tables'):
        tables.install(tmp_path / 'tex', source=tmp_path / 'build')


# --- drift: the three ways a paper and its emitters disagree ------------------------------------


def test_no_drift_when_the_paper_is_current(tables, paper, tmp_path):
    installed = tmp_path / 'tables'
    tables.write_all(tmp_path / 'build')
    tables.install(installed, source=tmp_path / 'build')

    found = tables.drift(paper, installed)

    assert found == Drift(stale=[], missing=[], ungenerated=[])
    assert not found
    assert 'OK' in tables.report(found)


def test_stale_when_the_installed_copy_is_behind_the_emitter(tables, paper, tmp_path):
    installed = tmp_path / 'tables'
    installed.mkdir()
    (installed / 'scores.tex').write_text('an older table\n', encoding='utf-8')

    found = tables.drift(paper, installed)

    assert found.stale == ['tab:scores']
    assert found.missing == []
    assert bool(found)
    assert 'the paper is behind the data' in tables.report(found)


def test_stale_when_nothing_is_installed_at_all(tables, paper, tmp_path):
    found = tables.drift(paper, tmp_path / 'nothing')

    assert found.stale == ['tab:scores']


def test_missing_when_the_paper_never_pulls_the_artefact_in(paper, tmp_path):
    registry = Registry(TABLES)

    @registry.register('tab:unused')
    def unused() -> str:
        return 'x'

    found = registry.drift(paper, tmp_path / 'tables')

    assert found.missing == ['tab:unused']
    assert found.stale == []
    assert 'never used by the paper' in registry.report(found)


def test_ungenerated_when_a_table_is_written_into_the_paper_by_hand(tables, tmp_path):
    manuscript = tmp_path / 'paper.tex'
    manuscript.write_text(
        PAPER + '\n\\begin{table}\n  Hand typed & 0.42 \\\\\n  \\label{tab:by-hand}\n\\end{table}\n',
        encoding='utf-8',
    )
    installed = tmp_path / 'tables'
    tables.write_all(tmp_path / 'build')
    tables.install(installed, source=tmp_path / 'build')

    found = tables.drift(manuscript, installed)

    assert found.ungenerated == ['tab:by-hand']
    assert found.stale == []
    assert 'with no emitter' in tables.report(found)


def test_all_three_kinds_of_drift_are_reported_together(tmp_path):
    registry = Registry(TABLES)

    @registry.register('tab:scores')
    def scores() -> str:
        return 'changed\n'

    @registry.register('tab:unused')
    def unused() -> str:
        return 'x'

    manuscript = tmp_path / 'paper.tex'
    manuscript.write_text(
        PAPER + '\n\\begin{table}\n  \\label{tab:by-hand}\n\\end{table}\n',
        encoding='utf-8',
    )
    installed = tmp_path / 'tables'
    installed.mkdir()
    (installed / 'scores.tex').write_text('older\n', encoding='utf-8')

    found = registry.drift(manuscript, installed)

    assert found == Drift(stale=['tab:scores'], missing=['tab:unused'], ungenerated=['tab:by-hand'])


def test_an_empty_registry_finds_only_what_the_paper_carries_by_hand(paper, tmp_path):
    registry = Registry(TABLES)

    found = registry.drift(paper, tmp_path / 'tables')

    assert found == Drift(stale=[], missing=[], ungenerated=[])
    assert 'all 0 tables' in registry.report(found)


def test_a_paper_that_pulls_nothing_in_makes_everything_missing(tables, tmp_path):
    manuscript = tmp_path / 'paper.tex'
    manuscript.write_text('\\documentclass{article}\n\\begin{document}\nProse.\n\\end{document}\n', encoding='utf-8')

    found = tables.drift(manuscript, tmp_path / 'tables')

    assert found.missing == ['tab:scores']
    assert found.ungenerated == []


# --- figures differ from tables in more than extension ------------------------------------------


def test_a_correctly_included_figure_is_not_reported_as_hand_written(figures, paper, tmp_path):
    """The float around a figure is always written by the author; only the image is generated."""
    installed = tmp_path / 'figures'
    figures.write_all(tmp_path / 'build')
    figures.install(installed, source=tmp_path / 'build')

    found = figures.drift(paper, installed)

    assert found.ungenerated == [], 'the figure float wraps a generated image, so it is not hand-made'
    assert not found


def test_a_figure_drawn_inline_has_no_emitter_behind_it(figures, tmp_path):
    manuscript = tmp_path / 'paper.tex'
    manuscript.write_text(
        PAPER + '\n\\begin{figure}\n  \\begin{tikzpicture}\\end{tikzpicture}\n  \\label{fig:drawn}\n\\end{figure}\n',
        encoding='utf-8',
    )
    installed = tmp_path / 'figures'
    figures.write_all(tmp_path / 'build')
    figures.install(installed, source=tmp_path / 'build')

    found = figures.drift(manuscript, installed)

    assert found.ungenerated == ['fig:drawn']


def test_a_figure_is_compared_by_bytes(figures, paper, tmp_path):
    installed = tmp_path / 'figures'
    installed.mkdir()
    (installed / 'curve.png').write_bytes(CURVE[:-1])

    assert figures.drift(paper, installed).stale == ['fig:curve']


def test_the_reference_may_carry_the_extension(figures, tmp_path):
    manuscript = tmp_path / 'paper.tex'
    manuscript.write_text('\\includegraphics{figures/curve.png}\n', encoding='utf-8')
    installed = tmp_path / 'figures'
    figures.write_all(tmp_path / 'build')
    figures.install(installed, source=tmp_path / 'build')

    assert figures.drift(manuscript, installed).missing == []


# --- the command line -------------------------------------------------------------------------


def test_check_exits_nonzero_when_the_paper_has_drifted(tables, paper, tmp_path, monkeypatch, capsys):
    _configure(tmp_path, paper, monkeypatch)

    assert tables.main(['--check']) == 1
    assert 'stale' in capsys.readouterr().out


def test_check_exits_zero_when_the_paper_is_current(tables, paper, tmp_path, monkeypatch, capsys):
    root = _configure(tmp_path, paper, monkeypatch)
    tables.main([])
    tables.main(['--install'])
    _load.cache_clear()

    assert tables.main(['--check']) == 0
    assert 'OK' in capsys.readouterr().out
    assert (root / 'tex' / 'tables' / 'scores.tex').exists()


def test_list_shows_what_is_registered(tables, capsys):
    assert tables.main(['--list']) == 0
    assert 'tab:scores' in capsys.readouterr().out


def _configure(tmp_path, paper, monkeypatch):
    """Make a project whose settings point at the fixtures, and work from it."""
    root = tmp_path / 'project'
    root.mkdir()
    (root / 'pyproject.toml').write_text(
        f'[tool.research-helpers.paper]\nmain = "{paper}"\ntables-dir = "tex/tables"\nbuild-dir = "build"\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    _load.cache_clear()
    return root


def test_the_remedy_names_only_what_actually_drifted(tables):
    assert 'rebuild' in tables.report(Drift(stale=['tab:a'], missing=[], ungenerated=[]))
    assert 'edit the paper' not in tables.report(Drift(stale=['tab:a'], missing=[], ungenerated=[]))

    hand_written = Drift(stale=[], missing=[], ungenerated=['tab:b'])
    assert 'edit the paper' in tables.report(hand_written)
    assert 'rebuild' not in tables.report(hand_written)


def test_output_paths_are_relative_to_the_project(tables, paper, tmp_path, monkeypatch, capsys):
    _configure(tmp_path, paper, monkeypatch)

    tables.main([])

    assert 'wrote build/tables/scores.tex' in capsys.readouterr().out


def test_check_without_a_manuscript_explains_rather_than_tracing_back(tmp_path, monkeypatch):
    """A public companion repository generates artefacts but carries no paper."""
    (tmp_path / 'pyproject.toml').write_text('[tool.research-helpers.paper]\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    _load.cache_clear()
    registry = Registry(TABLES)

    with pytest.raises(FileNotFoundError, match='nothing to check against'):
        registry.drift()


def test_the_command_line_reports_a_missing_manuscript_without_a_traceback(tmp_path, monkeypatch, capsys):
    (tmp_path / 'pyproject.toml').write_text('[tool.research-helpers.paper]\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    _load.cache_clear()
    registry = Registry(TABLES)

    status = registry.main(['--check'])

    printed = capsys.readouterr()
    assert status == 1
    assert printed.out == ''
    assert 'no manuscript at' in printed.err
    assert 'paper.main' in printed.err, 'the message should name the setting to fix'


# --- documents: one manuscript and everything it carries ----------------------------------------

NOTE = r"""
\documentclass{article}
\begin{document}
The note's scores are in Table~\ref{tab:scores}.
\input{tables/scores}
It finds 143 communities.
\end{document}
"""


def _two_documents(tmp_path, monkeypatch):
    """Make a project with a paper and a note, each its own manuscript, and work from it."""
    root = tmp_path / 'project'
    (root / 'tex' / 'note').mkdir(parents=True)
    (root / 'tex' / 'paper.tex').write_text(PAPER, encoding='utf-8')
    (root / 'tex' / 'note' / 'note.tex').write_text(NOTE, encoding='utf-8')
    (root / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\n[tool.research-helpers.documents.note]\nmain = "tex/note/note.tex"\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(root)
    _load.cache_clear()
    return root


def test_a_document_builds_and_installs_into_its_own_directories(tables, tmp_path, monkeypatch):
    root = _two_documents(tmp_path, monkeypatch)
    note = Document('note', tables)

    built = note.write_all()
    installed = note.install()

    assert built == [root / 'build' / 'note' / 'tables' / 'scores.tex']
    assert installed == [root / 'tex' / 'note' / 'tables' / 'scores.tex']
    assert not (root / 'tex' / 'tables').exists(), "nothing lands in the paper's directory"


def test_the_paper_document_uses_the_same_directories_as_a_bare_registry(tables, tmp_path, monkeypatch):
    root = _two_documents(tmp_path, monkeypatch)

    assert Document('paper', tables).build_dir(tables) == tables.build_dir() == root / 'build' / 'tables'
    assert Document('paper', tables).install_dir(tables) == tables.install_dir() == root / 'tex' / 'tables'


def test_a_document_reports_drift_in_its_own_name(tables, tmp_path, monkeypatch, capsys):
    _two_documents(tmp_path, monkeypatch)
    note = Document('note', tables)

    assert note.main(['--check']) == 1
    assert 'stale, the note is behind the data: tab:scores' in capsys.readouterr().out

    note.main(['--install'])
    assert note.main(['--check']) == 0
    assert 'OK: all 1 tables in the note are current' in capsys.readouterr().out


def test_a_document_checks_its_prose_with_its_floats(tables, tmp_path, monkeypatch, capsys):
    _two_documents(tmp_path, monkeypatch)
    prose = ProseRegistry()
    prose.add(
        ProseNumber('k', 'It finds {} communities', lambda: ('148',), document='note'),
        ProseNumber('p', 'not in the note {}', lambda: ('1',)),
    )
    note = Document('note', tables, prose=prose)
    note.main(['--install'])
    capsys.readouterr()

    assert note.main(['--check']) == 1
    printed = capsys.readouterr().out
    assert 'OK: all 1 tables in the note are current' in printed
    assert 'prints     It finds 143 communities' in printed
    assert '1 checked' in printed, "the paper's entry is not the note's to check"


def test_a_document_lists_every_kind_and_its_prose(tables, figures, capsys):
    prose = ProseRegistry()
    prose.add(ProseNumber('k', 'finds {}', lambda: ('1',), section='§2'))

    assert Document('paper', tables, figures, prose=prose).main(['--list']) == 0

    printed = capsys.readouterr().out
    assert printed.index('tables:') < printed.index('tab:scores') < printed.index('figures:')
    assert 'fig:curve' in printed
    assert 'prose:' in printed
    assert '§2' in printed


def test_two_registries_of_one_kind_would_share_a_directory():
    with pytest.raises(ValueError, match='more than one registry of tables'):
        Document('paper', Registry(TABLES), Registry(TABLES))


def test_a_document_with_no_manuscript_names_the_setting_that_locates_it(tables, tmp_path, monkeypatch, capsys):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.documents.note]\nmain = "tex/note/missing.tex"\n',
        encoding='utf-8',
    )
    monkeypatch.chdir(tmp_path)
    _load.cache_clear()

    assert Document('note', tables).main(['--check']) == 1
    assert 'documents.note.main' in capsys.readouterr().err


def test_an_unconfigured_document_says_how_to_configure_it(tables, capsys):
    assert Document('supplement', tables).main(['--check']) == 1
    assert '[tool.research-helpers.documents.supplement]' in capsys.readouterr().err


def test_explicit_settings_need_no_wiring(tables, paper, tmp_path):
    settings = PaperSettings(main=paper, tables_dir=tmp_path / 'tables', build_dir=tmp_path / 'build')
    document = Document('paper', tables, settings=settings)
    document.write_all()
    document.install()

    assert not document.drift()['tables']
