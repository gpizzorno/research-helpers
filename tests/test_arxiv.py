"""Assemble an arXiv submission."""

from __future__ import annotations

import os
import tarfile

import pytest

from research_helpers.arxiv import bbl_format, build, check, manifest, pack, report
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


# --- the rules --------------------------------------------------------------------------------


def test_a_correct_submission_has_no_problems(project):
    _touch_bbl_after_paper(project)

    assert check(manifest()) == []


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
