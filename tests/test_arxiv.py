"""Assemble an arXiv submission."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from research_helpers.arxiv import bbl_format, build, check, manifest, pack, preview, report, unused
from research_helpers.project import _load

PAPER = r"""
\documentclass{article}
\usepackage[expansion=false]{microtype}
\begin{document}
\input{tables/scores}
\includegraphics{figures/curve}
\end{document}
"""

BBL = '% $ biblatex bbl format version 3.3 $\n\\begin{thebibliography}\n\\end{thebibliography}\n'


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Return a laid-out project: a manuscript, a generated table and figure, and a .bbl."""
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    root = tmp_path / 'project'
    (root / 'tex' / 'tables').mkdir(parents=True)
    (root / 'tex' / 'figures').mkdir(parents=True)
    (root / 'tex' / 'out_dir').mkdir(parents=True)

    (root / 'pyproject.toml').write_text('[tool.research-helpers.arxiv]\nengine = "xelatex"\n', encoding='utf-8')
    (root / 'tex' / 'paper.tex').write_text(PAPER, encoding='utf-8')
    (root / 'tex' / 'tables' / 'scores.tex').write_text('a table\n', encoding='utf-8')
    (root / 'tex' / 'figures' / 'curve.png').write_bytes(b'\x89PNG image')
    (root / 'tex' / 'out_dir' / 'paper.bbl').write_text(BBL, encoding='utf-8')

    monkeypatch.chdir(root)
    _load.cache_clear()
    yield root
    _load.cache_clear()


# Mtimes are set explicitly rather than by touching in order. Unlike macOS, Linux takes inode
# timestamps from a coarse clock updated once per timer tick, so two writes a few hundred
# microseconds apart get byte-identical mtimes and the comparison under test never fires
MTIME = 1_700_000_000


def _set_mtimes(root, *, bbl_offset):
    """Place the .bbl 'bbl_offset' seconds either side of the manuscript."""
    paper = root / 'tex' / 'paper.tex'
    bbl = root / 'tex' / 'out_dir' / 'paper.bbl'
    os.utime(paper, (MTIME, MTIME))
    os.utime(bbl, (MTIME + bbl_offset, MTIME + bbl_offset))


def _touch_bbl_after_paper(root):
    """Make the .bbl newer than the manuscript, as a real build would leave it."""
    _set_mtimes(root, bbl_offset=10)


def _leave_the_bbl_stale(root):
    """Make the .bbl older than the manuscript, as editing citations would leave it."""
    _set_mtimes(root, bbl_offset=-10)


# --- the manifest -----------------------------------------------------------------------------


@pytest.mark.usefixtures('project')
def test_the_manifest_is_named_relative_to_the_manuscript():
    # arXiv resolves \input{tables/scores} against the main file, so the layout must match
    files = manifest()

    assert set(files) == {'paper.tex', 'paper.bbl', 'tables/scores.tex', 'figures/curve.png'}


def test_the_manifest_takes_extra_files(project):
    (project / 'sty').mkdir()
    (project / 'sty' / 'house.cls').write_text('x', encoding='utf-8')

    files = manifest(extra={'house.cls': project / 'sty' / 'house.cls'})

    assert files['house.cls'].name == 'house.cls'


def test_the_manifest_ignores_build_leftovers(project):
    (project / 'tex' / 'tables' / 'scores.aux').write_text('x', encoding='utf-8')

    assert 'tables/scores.aux' not in manifest()


def test_the_manifest_uploads_only_the_floats_the_manuscript_reads(project):
    (project / 'tex' / 'tables' / 'retired.tex').write_text('a table nothing inputs', encoding='utf-8')
    (project / 'tex' / 'figures' / 'retired.png').write_bytes(b'\x89PNG a figure nothing includes')

    files = manifest()

    assert set(files) == {'paper.tex', 'paper.bbl', 'tables/scores.tex', 'figures/curve.png'}
    assert unused(files) == ['tables/retired.tex', 'figures/retired.png']


def test_a_float_read_only_in_a_comment_is_not_uploaded(project):
    (project / 'tex' / 'tables' / 'retired.tex').write_text('a table', encoding='utf-8')
    paper = project / 'tex' / 'paper.tex'
    paper.write_text(paper.read_text(encoding='utf-8') + '% \\input{tables/retired}\n', encoding='utf-8')

    assert 'tables/retired.tex' not in manifest()


def test_a_reference_names_its_file_with_or_without_the_extension(project):
    paper = project / 'tex' / 'paper.tex'
    paper.write_text(
        paper.read_text(encoding='utf-8').replace('figures/curve}', 'figures/curve.png}'),
        encoding='utf-8',
    )

    assert manifest()['figures/curve.png'] == project / 'tex' / 'figures' / 'curve.png'


def test_an_option_holding_brackets_does_not_hide_a_figure(project):
    paper = project / 'tex' / 'paper.tex'
    text = paper.read_text(encoding='utf-8')
    paper.write_text(text.replace('\\includegraphics{', '\\includegraphics[alt={a [dashed] line}]{'), encoding='utf-8')

    assert 'figures/curve.png' in manifest()


def test_a_reference_with_no_file_behind_it_is_reported_missing(project):
    paper = project / 'tex' / 'paper.tex'
    paper.write_text(paper.read_text(encoding='utf-8') + '\\input{tables/absent}\n', encoding='utf-8')
    _touch_bbl_after_paper(project)

    files = manifest()

    assert 'missing: tables/absent' in check(files)


def test_a_second_document_is_submitted_from_its_own_settings(project):
    note = project / 'tex' / 'note'
    for directory in ('tables', 'figures', 'out_dir'):
        (note / directory).mkdir(parents=True)
    (note / 'note.tex').write_text('\\begin{document}\n\\input{tables/rates}\n\\end{document}\n', encoding='utf-8')
    (note / 'tables' / 'rates.tex').write_text('a table\n', encoding='utf-8')
    (note / 'out_dir' / 'note.bbl').write_text(BBL, encoding='utf-8')
    os.utime(note / 'note.tex', (MTIME, MTIME))
    os.utime(note / 'out_dir' / 'note.bbl', (MTIME + 10, MTIME + 10))
    pyproject = project / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text(encoding='utf-8') + '[tool.research-helpers.documents.note]\nmain = "tex/note/note.tex"\n',
        encoding='utf-8',
    )
    _load.cache_clear()

    files = manifest(document='note')

    assert files == {
        'note.tex': note / 'note.tex',
        'note.bbl': note / 'out_dir' / 'note.bbl',
        'tables/rates.tex': note / 'tables' / 'rates.tex',
    }
    assert check(files, document='note') == []


@pytest.mark.usefixtures('project')
def test_an_unconfigured_document_says_how_to_configure_it():
    with pytest.raises(KeyError, match=r'\[tool\.research-helpers\.documents\.supplement\]'):
        manifest(document='supplement')


def test_the_preview_compiles_the_documents_own_manuscript(project, monkeypatch):
    commands = []

    def fake_engine(command, *, cwd, **_):
        commands.append(command)
        (Path(cwd) / 'paper.pdf').write_bytes(b'%PDF')

    # the real preview shells out to xelatex, which a test machine need not have
    monkeypatch.setattr(subprocess, 'run', fake_engine)
    build(manifest(), project / 'dist')

    pdf = preview(project / 'dist', project / 'compiled', passes=2)

    assert commands == [['xelatex', '-interaction=nonstopmode', 'paper.tex']] * 2
    assert pdf == project / 'compiled' / 'paper.pdf'


# --- markers --------------------------------------------------------------------------------------


def _mark(project, *, markers):
    """Configure the markers, and leave one in the manuscript, one in its comments and one in the .bbl."""
    (project / 'pyproject.toml').write_text(
        '[tool.research-helpers.arxiv]\nengine = "xelatex"\nmarkers = [' + ', '.join(f'"{m}"' for m in markers) + ']\n',
        encoding='utf-8',
    )
    paper = project / 'tex' / 'paper.tex'
    text = paper.read_text(encoding='utf-8')
    paper.write_text(
        text.replace('\\end{document}', 'As shown [PAGE]. % [CITATION NEEDED] here is a note\n\\end{document}'),
        encoding='utf-8',
    )
    bbl = project / 'tex' / 'out_dir' / 'paper.bbl'
    bbl.write_text(BBL + '\\field{eprint}{[ID]}\n', encoding='utf-8')
    _touch_bbl_after_paper(project)
    _load.cache_clear()


def test_a_marker_left_in_the_upload_is_reported_with_its_lines(project):
    _mark(project, markers=['[PAGE]', '[ID]', '[CITATION NEEDED]'])
    lines = (project / 'tex' / 'paper.tex').read_text(encoding='utf-8').splitlines()
    page = next(number for number, line in enumerate(lines, start=1) if '[PAGE]' in line)

    problems = check(manifest())

    assert problems == [f'marker [PAGE] left in paper.tex: line {page}', 'marker [ID] left in paper.bbl: line 4']


def test_no_marker_is_looked_for_unless_one_is_configured(project):
    _mark(project, markers=[])

    assert check(manifest()) == []


def test_markers_given_to_the_check_replace_the_projects(project):
    _mark(project, markers=['[ID]'])

    assert check(manifest(), markers=['As shown']) == [
        f'marker As shown left in paper.tex: line {_line_of(project, "As shown")}',
    ]


def test_a_marker_is_not_looked_for_in_an_image(project):
    (project / 'tex' / 'figures' / 'curve.png').write_bytes(b'\x89PNG [ID]')
    _mark(project, markers=['[ID]'])
    (project / 'tex' / 'out_dir' / 'paper.bbl').write_text(BBL, encoding='utf-8')
    _touch_bbl_after_paper(project)

    assert check(manifest()) == []


def test_a_marker_on_many_lines_names_the_first_few_and_the_count(project):
    _mark(project, markers=['[ID]'])
    (project / 'tex' / 'out_dir' / 'paper.bbl').write_text(BBL + '[ID]\n' * 12, encoding='utf-8')
    _touch_bbl_after_paper(project)

    assert check(manifest()) == [
        'marker [ID] left in paper.bbl: lines 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, ... (12 in all)',
    ]


def _line_of(project, text):
    """Return the line of the manuscript that first holds the text."""
    lines = (project / 'tex' / 'paper.tex').read_text(encoding='utf-8').splitlines()
    return next(number for number, line in enumerate(lines, start=1) if text in line)


# --- the rules --------------------------------------------------------------------------------


def test_a_correct_submission_has_no_problems(project):
    _touch_bbl_after_paper(project)

    assert check(manifest()) == []


def test_a_paper_configured_without_a_manuscript_has_nothing_to_submit(project):
    (project / 'pyproject.toml').write_text('[tool.research-helpers.paper]\nmanuscript = false\n', encoding='utf-8')
    _load.cache_clear()

    assert check(manifest()) == ['the paper is configured without a manuscript: nothing to submit']


def test_a_missing_file_is_reported(project):
    files = manifest()
    files['tables/absent.tex'] = project / 'tex' / 'tables' / 'absent.tex'

    assert 'missing: tables/absent.tex' in check(files)


def test_a_filename_arxiv_forbids_is_reported(project):
    _touch_bbl_after_paper(project)
    files = manifest()
    files['tables/my table.tex'] = project / 'tex' / 'tables' / 'scores.tex'

    problems = check(files)

    assert any('permitted characters' in problem for problem in problems)


def test_a_hidden_file_is_reported(project):
    _touch_bbl_after_paper(project)
    files = manifest()
    files['.hidden.tex'] = project / 'tex' / 'tables' / 'scores.tex'

    assert any('hidden file' in problem for problem in check(files))


def test_an_absent_bbl_is_reported(project):
    (project / 'tex' / 'out_dir' / 'paper.bbl').unlink()

    assert any('no .bbl found' in problem for problem in check(manifest()))


def test_a_bbl_in_the_wrong_format_is_reported(project):
    _touch_bbl_after_paper(project)
    (project / 'tex' / 'out_dir' / 'paper.bbl').write_text(
        BBL.replace('3.3', '3.2'),
        encoding='utf-8',
    )

    problems = check(manifest())

    assert any('format 3.2' in problem and 'expects 3.3' in problem for problem in problems)


def test_the_expected_bbl_format_follows_the_project_setting(project):
    _touch_bbl_after_paper(project)

    assert check(manifest(), expected_bbl_format='3.2') != []
    assert check(manifest(), expected_bbl_format='3.3') == []


def test_a_bbl_older_than_the_manuscript_is_reported(project):
    _leave_the_bbl_stale(project)

    assert any('older than paper.tex' in problem for problem in check(manifest()))


def test_microtype_expansion_is_a_hard_error_under_xelatex(project):
    _touch_bbl_after_paper(project)
    (project / 'tex' / 'paper.tex').write_text(PAPER.replace('expansion=false', 'expansion=true'), encoding='utf-8')
    _touch_bbl_after_paper(project)

    assert any('expansion=true' in problem for problem in check(manifest()))


def test_microtype_expansion_is_fine_under_an_engine_that_supports_it(project):
    _touch_bbl_after_paper(project)
    (project / 'tex' / 'paper.tex').write_text(PAPER.replace('expansion=false', 'expansion=true'), encoding='utf-8')
    _touch_bbl_after_paper(project)

    assert check(manifest(), engine='pdflatex') == []


# --- reading the .bbl -------------------------------------------------------------------------


def test_the_bbl_format_is_read_from_the_file(project):
    assert bbl_format(project / 'tex' / 'out_dir' / 'paper.bbl') == '3.3'


def test_a_bbl_that_declares_nothing_reads_as_none(project):
    path = project / 'tex' / 'out_dir' / 'paper.bbl'
    path.write_text('no version comment here\n', encoding='utf-8')

    assert bbl_format(path) is None


def test_an_absent_bbl_reads_as_none(tmp_path):
    assert bbl_format(tmp_path / 'nothing.bbl') is None


# --- building and packing ---------------------------------------------------------------------


def test_build_lays_the_submission_out_flat(project):
    written = build(manifest(), project / 'dist')

    assert (project / 'dist' / 'paper.tex').exists()
    assert (project / 'dist' / 'tables' / 'scores.tex').exists()
    assert (project / 'dist' / 'figures' / 'curve.png').read_bytes() == b'\x89PNG image'
    assert 'paper.bbl' in written


def test_build_empties_the_directory_first(project):
    dist = project / 'dist'
    dist.mkdir()
    (dist / 'stale.tex').write_text('from an older submission', encoding='utf-8')

    build(manifest(), dist)

    assert not (dist / 'stale.tex').exists(), 'a stale file would be uploaded'


def test_pack_writes_a_tarball_of_the_submission(project):
    build(manifest(), project / 'dist')

    archive = pack(project / 'dist')

    with tarfile.open(archive) as tar:
        assert set(tar.getnames()) >= {'paper.tex', 'tables/scores.tex', 'figures/curve.png'}


# --- the report -------------------------------------------------------------------------------


def test_the_report_lists_the_manifest_and_says_it_is_ready(project):
    _touch_bbl_after_paper(project)
    files = manifest()

    text = report(files, check(files))

    assert 'paper.tex' in text
    assert '4 files' in text
    assert 'bbl format 3.3' in text
    assert 'ready to upload: select xelatex and TeX Live 2025' in text


def test_the_report_lists_the_problems(project):
    files = manifest()
    files['tables/absent.tex'] = project / 'tex' / 'absent.tex'

    text = report(files, check(files))

    assert 'MISSING' in text
    assert 'problem(s)' in text
    assert 'ready to upload' not in text


def test_the_report_names_what_was_left_out(project):
    (project / 'tex' / 'tables' / 'retired.tex').write_text('a table nothing inputs', encoding='utf-8')
    files = manifest()

    text = report(files, check(files), unused_files=unused(files))

    assert 'not uploaded, since paper.tex does not read them: tables/retired.tex' in text


def test_an_empty_manifest_says_so():
    assert 'manifest is empty' in report({}, [])


def test_the_tarball_is_byte_reproducible(project):
    """A resubmission should be distinguishable from a rebuild of unchanged sources."""
    build(manifest(), project / 'dist')

    first = pack(project / 'dist', project / 'first.tar.gz').read_bytes()
    for path in (project / 'dist').rglob('*'):
        os.utime(path, None)
    second = pack(project / 'dist', project / 'second.tar.gz').read_bytes()

    assert first == second


def test_the_manifest_uploads_a_package_loaded_from_beside_the_manuscript(project):
    loading = '\\usepackage{rhtextmath, amsmath}\n% \\usepackage{commented}\n\\begin{document}'
    (project / 'tex' / 'paper.tex').write_text(PAPER.replace('\\begin{document}', loading), encoding='utf-8')
    for name in ('rhtextmath', 'commented'):
        (project / 'tex' / f'{name}.sty').write_text('% a package\n', encoding='utf-8')

    files = manifest()

    assert files['rhtextmath.sty'] == project / 'tex' / 'rhtextmath.sty'
    assert 'amsmath.sty' not in files  # TeX Live's, not the manuscript's
    assert 'commented.sty' not in files  # loaded only in a comment
