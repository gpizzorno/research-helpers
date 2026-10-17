"""Numbers stated in prose: the registry, the check against the document, and the audit."""

from __future__ import annotations

import pytest

from research_helpers.project import _load
from research_helpers.prose import (
    ProseNumber,
    ProseRegistry,
    audit,
    audit_report,
    normalise_prose,
)

PAPER = r"""\documentclass{article}
\usepackage{amsmath} % 12 in the preamble is not prose
\begin{document}
\begin{abstract}
OSLOM finds 143 communities on
average, of which 7.7 per cent are debris.
\end{abstract}

The founder-led cover has \(\Omega = 0.386\) at \(\mu = 0.5\), see Table~\ref{tab:shape}.
% OSLOM finds 999 communities on average
We ran 20 seeds \autocite[12]{key}, with \(6/7\) as the bound and 1,606 edges.
\[ k = 40 \]
\label{sec:9}
\end{document}
"""


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    monkeypatch.chdir(tmp_path)
    yield
    _load.cache_clear()


@pytest.fixture
def project(tmp_path):
    """Return a project whose paper is the fixture above, with one generated table."""
    (tmp_path / 'pyproject.toml').write_text('[tool.research-helpers.paper]\n', encoding='utf-8')
    (tmp_path / 'tex' / 'tables').mkdir(parents=True)
    (tmp_path / 'tex' / 'paper.tex').write_text(PAPER, encoding='utf-8')
    (tmp_path / 'tex' / 'tables' / 'shape.tex').write_text('0.386 & 1,606 \\label{tab:shape}', encoding='utf-8')
    _load.cache_clear()
    return tmp_path


def registry(**values):
    """Return a registry whose entries print what 'values' says, keyed by entry."""
    prose = ProseRegistry()
    prose.add(
        ProseNumber('mean-k', 'OSLOM finds {} communities on average', lambda: (values.get('mean-k', '143'),)),
        ProseNumber('debris', 'of which {} per cent are debris', lambda: (values.get('debris', '7.7'),)),
    )
    return prose


# --- entries --------------------------------------------------------------------------------------


def test_the_expected_fragment_is_the_template_filled_with_whitespace_collapsed():
    entry = ProseNumber('k', 'finds  {}\n communities', lambda: ('143',))

    assert entry.expected() == 'finds 143 communities'
    assert entry.placeholders == 1


def test_doubled_braces_are_literal_braces():
    entry = ProseNumber('q', r'\(Q_{{ov}} = {}\)', lambda: ('0.61',))

    assert entry.expected() == r'\(Q_{ov} = 0.61\)'
    assert entry.placeholders == 1


def test_a_template_may_format_raw_values():
    entry = ProseNumber('share', '{:.1f} per cent', lambda: (7.66,))

    assert entry.expected() == '7.7 per cent'


def test_too_few_or_too_many_values_is_refused():
    entry = ProseNumber('k', 'from {} to {}', lambda: ('1',))

    with pytest.raises(ValueError, match='1 value'):
        entry.expected()


def test_the_pattern_does_not_mistake_a_longer_word_for_the_sentence():
    entry = ProseNumber('k', 'found {} communities', lambda: ('3',))

    assert entry.pattern().search('the founder 3 communities') is None
    match = entry.pattern().search('it found 3\n  communities')
    assert match is not None
    assert match.group(1) == '3'


def test_the_pattern_stops_a_number_at_either_edge_at_the_next_space():
    leading = ProseNumber('a', '{} communities', lambda: ('3',))
    trailing = ProseNumber('b', 'it reaches {}', lambda: ('3',))

    first = leading.pattern().search('so there are 17 communities here')
    last = trailing.pattern().search('it reaches 0.614, then falls')
    assert first is not None
    assert last is not None
    assert first.group(1) == '17'
    assert last.group(1) == '0.614,'


def test_a_key_cannot_be_registered_twice():
    prose = registry()

    with pytest.raises(ValueError, match='already registered'):
        prose.add(ProseNumber('mean-k', 'x {}', lambda: ('1',)))


def test_register_returns_the_function_unchanged():
    prose = ProseRegistry()

    @prose.register('k', 'finds {} communities', source='runs/k.json', section='§2')
    def mean_k():
        return ('143',)

    assert mean_k() == ('143',)
    assert prose['k'].source == 'runs/k.json'
    assert prose['k'].section == '§2'
    assert 'k' in prose
    assert len(prose) == 1
    assert prose.documents == ['paper']


# --- the check ------------------------------------------------------------------------------------


@pytest.mark.usefixtures('project')
def test_a_registry_matching_its_document_is_current():
    found = registry().check()

    assert not found
    assert found.checked == 2
    assert 'OK: all 2 prose numbers are current' in registry().report(found)


@pytest.mark.usefixtures('project')
def test_a_changed_number_is_stale_and_the_report_shows_what_is_printed():
    prose = registry(**{'mean-k': '148.6'})

    found = prose.check()

    assert [mismatch.key for mismatch in found.stale] == ['mean-k']
    report = prose.report(found)
    assert 'prints     OSLOM finds 143 communities on average' in report
    assert 'data give  OSLOM finds 148.6 communities on average' in report
    assert 'correct the text' in report


@pytest.mark.usefixtures('project')
def test_a_sentence_that_no_longer_exists_is_reported_as_not_found():
    prose = ProseRegistry()
    prose.add(ProseNumber('hubs', 'the cover has {} hubs', lambda: ('3',)))

    found = prose.check()

    assert [mismatch.key for mismatch in found.vanished] == ['hubs']
    assert 'update the template' in prose.report(found)


@pytest.mark.usefixtures('project')
def test_a_commented_out_sentence_does_not_count():
    prose = ProseRegistry()
    prose.add(ProseNumber('old', 'OSLOM finds {} communities on average', lambda: ('999',)))

    assert [mismatch.key for mismatch in prose.check().stale] == ['old'], 'the 999 is in a comment'


@pytest.mark.usefixtures('project')
def test_an_entry_whose_data_is_missing_is_reported_not_raised():
    prose = registry()

    @prose.register('broken', 'founder-{}')
    def broken():
        msg = 'runs/y.json: run make y'
        raise FileNotFoundError(msg)

    found = prose.check()

    assert found.failed == [('broken', 'FileNotFoundError: runs/y.json: run make y')]
    assert 'produce the data' in prose.report(found)


@pytest.mark.usefixtures('project')
def test_a_known_discrepancy_that_is_still_wrong_is_open_not_a_failure():
    prose = registry(debris='7.9')
    prose.known_discrepancies['debris'] = 'the data give 7.9; the text is corrected in the next pass'

    found = prose.check()

    assert not found
    assert found.open_discrepancies == 1
    assert '1 known discrepancies still open' in prose.report(found)


@pytest.mark.usefixtures('project')
def test_a_known_discrepancy_corrected_in_the_text_must_leave_the_list():
    prose = registry()
    prose.known_discrepancies['debris'] = 'was 7.9'

    found = prose.check()

    assert found.fixed == ['debris']
    assert 'remove them from the known discrepancies' in prose.report(found)


@pytest.mark.usefixtures('project')
def test_a_known_discrepancy_whose_sentence_was_cut_would_track_nothing():
    prose = ProseRegistry(known_discrepancies={'hubs': 'was 4'})
    prose.add(ProseNumber('hubs', 'the cover has {} hubs', lambda: ('3',)))

    assert [mismatch.key for mismatch in prose.check().vanished] == ['hubs']


@pytest.mark.usefixtures('project')
def test_a_known_discrepancy_naming_no_entry_is_orphaned():
    prose = registry()
    prose.known_discrepancies['gone'] = 'renamed'

    assert prose.check().orphaned == ['gone']


def test_each_entry_is_checked_against_its_own_document(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\nmain = "paper.tex"\n'
        '[tool.research-helpers.documents.note]\nmain = "note/note.tex"\n',
        encoding='utf-8',
    )
    (tmp_path / 'note').mkdir()
    (tmp_path / 'paper.tex').write_text('the paper says 1\n', encoding='utf-8')
    (tmp_path / 'note' / 'note.tex').write_text('the note says 2\n', encoding='utf-8')
    _load.cache_clear()
    prose = ProseRegistry()
    prose.add(
        ProseNumber('p', 'the paper says {}', lambda: ('1',)),
        ProseNumber('n', 'the note says {}', lambda: ('2',), document='note'),
    )

    assert not prose.check()
    assert prose.check(document='note').checked == 1
    assert prose.documents == ['paper', 'note']


def test_an_explicit_path_overrides_the_wiring(tmp_path):
    manuscript = tmp_path / 'elsewhere.tex'
    manuscript.write_text('OSLOM finds 143 communities on average, of which 7.7 per cent are debris.', encoding='utf-8')

    assert not registry().check({'paper': manuscript})


def test_a_missing_manuscript_says_so():
    with pytest.raises(FileNotFoundError, match='nothing to check against'):
        registry().check()


@pytest.mark.usefixtures('project')
def test_an_unconfigured_document_says_how_to_configure_it():
    prose = ProseRegistry()
    prose.add(ProseNumber('n', 'says {}', lambda: ('2',), document='supplement'))

    with pytest.raises(KeyError, match=r'documents\.supplement'):
        prose.check()


# --- the command line -----------------------------------------------------------------------------


@pytest.mark.usefixtures('project')
def test_check_is_the_default_and_exits_nonzero_on_a_mismatch(capsys):
    assert registry().main([]) == 0
    assert registry(**{'mean-k': '1'}).main([]) == 1
    assert 'stale' in capsys.readouterr().out


@pytest.mark.usefixtures('project')
def test_list_shows_what_is_registered(capsys):
    assert registry().main(['--list']) == 0
    assert 'mean-k' in capsys.readouterr().out


def test_a_missing_manuscript_is_reported_without_a_traceback(capsys):
    assert registry().main([]) == 1
    printed = capsys.readouterr()
    assert printed.out == ''
    assert 'no manuscript at' in printed.err


@pytest.mark.usefixtures('project')
def test_an_unknown_document_is_reported_without_quotes_or_a_traceback(capsys):
    prose = ProseRegistry()
    prose.add(ProseNumber('n', 'says {}', lambda: ('2',), document='supplement'))

    assert prose.main([]) == 1
    assert capsys.readouterr().err.startswith("no document named 'supplement'")


def test_the_audit_is_written_where_asked(project, capsys):
    assert registry().main(['--audit', '--out', 'audit/paper.md']) == 0

    assert (project / 'audit' / 'paper.md').read_text(encoding='utf-8').startswith('# Prose-number audit: paper')
    assert 'wrote audit/paper.md' in capsys.readouterr().out


@pytest.mark.usefixtures('project')
def test_the_audit_prints_to_stdout_by_default(capsys):
    assert registry().main(['--audit']) == 0
    assert '## Untraced' in capsys.readouterr().out


# --- normalising ----------------------------------------------------------------------------------


def test_normalising_drops_comments_but_keeps_an_escaped_percent():
    assert normalise_prose('fell by 3\\% % a comment\nthen rose') == 'fell by 3\\% then rose'


# --- the audit ------------------------------------------------------------------------------------


def classified(text=PAPER, entries=(), **kwargs):
    """Return token to category for every token the audit finds."""
    return {occurrence.token: occurrence.category for occurrence in audit(text, entries, **kwargs)}


def test_numbers_outside_the_prose_are_skipped():
    tokens = classified()

    for skipped in ('12', '999', '40', '9'):  # preamble, comment and citation, display math, label
        assert skipped not in tokens, skipped


def test_registered_fragments_account_for_their_numbers():
    tokens = classified(entries=list(registry()))

    assert tokens['143'] == 'registered'
    assert tokens['7.7'] == 'registered'


def test_a_formula_constant_is_notation():
    assert classified()['6'] == 'notation'


def test_an_assignment_is_a_result_unless_its_symbol_is_declared_a_parameter():
    """A default that read every assignment as a parameter would hide results such as Omega = 0.386."""
    assert classified()['0.5'] == 'untraced'
    assert classified(parameter_symbols=[r'\mu'])['0.5'] == 'notation'


def test_a_number_in_a_table_the_paragraph_cites_is_carried_by_it(project):
    tokens = classified(tables_dir=project / 'tex' / 'tables')

    assert tokens['0.386'] == 'cited-float'
    assert tokens['1,606'] == 'other-float', 'the table carries it, but this paragraph does not cite it'


def test_an_untraced_number_is_what_is_left():
    tokens = classified(entries=list(registry()), tables_dir=None)

    assert tokens['20'] == 'untraced'
    assert tokens['0.386'] == 'untraced', 'with no tables to look in'


def test_the_report_puts_the_untraced_numbers_first_and_counts_every_category():
    report = audit_report(audit(PAPER, list(registry())), title='Audit')

    assert report.startswith('# Audit')
    assert report.index('## Untraced') < report.index('## Registered')
    assert '**2** registered' in report
    assert '| 11 | `20` |' in report


@pytest.mark.usefixtures('project')
def test_the_registry_audits_a_document_from_the_wiring():
    found = registry().audit()

    assert {o.token: o.category for o in found}['0.386'] == 'cited-float', 'tables come from the wiring'
