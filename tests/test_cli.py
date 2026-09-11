"""Command line tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from research_helpers import arxiv as arxiv_module
from research_helpers.cli import main
from research_helpers.project import _load

PAPER = r"""
\documentclass{article}
\usepackage[expansion=false]{microtype}
\begin{document}
\input{tables/scores}
\includegraphics{figures/curve}
\end{document}
"""

# expansion=true is a hard error under xelatex
PAPER_WITH_A_PROBLEM = PAPER.replace('expansion=false', 'expansion=true')

BBL = '% $ biblatex bbl format version 3.3 $\n\\begin{thebibliography}\n\\end{thebibliography}\n'

USAGE_ERROR = 2


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Wiring is cached per root and overridable by environment. Neither may leak between tests."""
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    yield
    _load.cache_clear()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Return a laid-out project the 'arxiv' subcommand can work on, as the working directory."""
    root = tmp_path / 'project'
    for directory in ('tex/tables', 'tex/figures', 'tex/out_dir'):
        (root / directory).mkdir(parents=True)

    (root / 'pyproject.toml').write_text('[tool.research-helpers.arxiv]\nengine = "xelatex"\n', encoding='utf-8')
    (root / 'tex' / 'paper.tex').write_text(PAPER, encoding='utf-8')
    (root / 'tex' / 'tables' / 'scores.tex').write_text('a table\n', encoding='utf-8')
    (root / 'tex' / 'figures' / 'curve.png').write_bytes(b'\x89PNG image')

    bbl = root / 'tex' / 'out_dir' / 'paper.bbl'
    bbl.write_text(BBL, encoding='utf-8')
    bbl.touch()  # a real build leaves the .bbl newer than the manuscript

    monkeypatch.chdir(root)
    return root


@pytest.fixture
def unmarked(tmp_path, monkeypatch):
    """Return a directory with no project-root marker on it or above it."""
    nowhere = tmp_path / 'nothing' / 'here'
    nowhere.mkdir(parents=True)
    monkeypatch.chdir(nowhere)
    return nowhere


def _break_the_paper(root):
    """Give 'check' exactly one thing to find."""
    (root / 'tex' / 'paper.tex').write_text(PAPER_WITH_A_PROBLEM, encoding='utf-8')
    # rewriting the manuscript leaves the .bbl older than it, which check reports as stale
    (root / 'tex' / 'out_dir' / 'paper.bbl').touch()


# --- parsing and dispatch ---------------------------------------------------------------------


def test_a_missing_subcommand_is_a_usage_error():
    # the subparser is required, so bare 'research-helpers' must not fall through to a handler
    with pytest.raises(SystemExit) as exit_:
        main([])

    assert exit_.value.code == USAGE_ERROR


def test_an_unknown_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_:
        main(['publish'])

    assert exit_.value.code == USAGE_ERROR


def test_help_exits_cleanly():
    with pytest.raises(SystemExit) as exit_:
        main(['--help'])

    assert exit_.value.code == 0


def test_each_subcommand_has_its_own_help():
    with pytest.raises(SystemExit) as exit_:
        main(['arxiv', '--help'])

    assert exit_.value.code == 0


def test_the_status_is_an_integer_so_it_can_be_a_process_exit_code(project):
    # main() is used as `raise SystemExit(main())`, where a non-int would be printed and exit 1
    assert type(main(['arxiv', '--dry-run'])) is int
    assert project.exists()


def test_the_installed_console_script_runs():
    """Check that 'research-helpers' in [project.scripts] resolves."""
    # next to the interpreter, not on PATH: pytest is run from the venv without activating it
    script = shutil.which('research-helpers', path=str(Path(sys.executable).parent))
    assert script, 'the research-helpers entry point is not installed in this environment'

    result = subprocess.run([script, 'doctor', '--help'], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert 'directory to search upward from' in result.stdout


def test_the_parser_builds_with_docstrings_stripped():
    """'python -OO' sets every __doc__ to None, and the parser reads __doc__ for its description.

    Run in a subprocess because -OO is an interpreter flag: it cannot be simulated in-process,
    and monkeypatching the constant afterwards would only test the assignment, not the guard.
    """
    result = subprocess.run(
        [sys.executable, '-OO', '-c', 'from research_helpers.cli import main; main(["--help"])'],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'doctor' in result.stdout


# --- doctor -----------------------------------------------------------------------------------


def test_doctor_prints_every_setting_with_the_layer_it_came_from(project, capsys):
    status = main(['doctor'])

    printed = capsys.readouterr().out
    assert status == 0
    assert f'root       {project}' in printed
    assert 'arxiv.engine' in printed
    assert '[pyproject]' in printed  # the engine was configured
    assert '[default]' in printed  # and most other things were not


def test_doctor_searches_upward_from_a_given_directory(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # somewhere with no project of its own

    status = main(['doctor', str(project / 'tex' / 'tables')])

    assert status == 0
    assert f'root       {project}' in capsys.readouterr().out


@pytest.mark.usefixtures('unmarked')
def test_doctor_without_a_project_root_explains_and_fails(capsys):
    status = main(['doctor'])

    printed = capsys.readouterr()
    assert status == 1
    assert printed.out == '', 'a failure must not also print a settings table'
    assert 'No project root above' in printed.err
    assert 'RESEARCH_HELPERS_ROOT' in printed.err, 'the message should say how to override the search'


# --- arxiv ------------------------------------------------------------------------------------


def test_arxiv_dry_run_reports_the_upload_set(project, capsys):
    status = main(['arxiv', '--dry-run'])

    printed = capsys.readouterr().out
    assert status == 0
    assert 'paper.tex' in printed
    assert 'tables/scores.tex' in printed
    assert 'figures/curve.png' in printed
    assert 'select xelatex' in printed
    assert '(dry run, nothing written)' in printed
    assert not (project / 'build').exists()


def test_arxiv_builds_the_submission(project, capsys):
    status = main(['arxiv'])

    submission = project / 'build' / 'arxiv'
    assert status == 0
    assert 'wrote' in capsys.readouterr().out
    assert (submission / 'paper.tex').exists()
    assert (submission / 'paper.bbl').exists()
    # the layout must match what \input{tables/scores} resolves to on arXiv, not the source tree
    assert (submission / 'tables' / 'scores.tex').exists()
    assert (submission / 'figures' / 'curve.png').exists()


def test_arxiv_tar_packs_the_built_submission(project):
    status = main(['arxiv', '--tar'])

    assert status == 0
    assert (project / 'build' / 'arxiv.tar.gz').exists()


def test_arxiv_preview_compiles_with_the_engine_arxiv_will_use(project, monkeypatch, capsys):
    compiled = {}

    def fake_preview(source, destination):
        compiled['source'] = source
        compiled['destination'] = destination
        return destination / 'paper.pdf'

    # the real preview shells out to xelatex, which a test machine need not have
    monkeypatch.setattr(arxiv_module, 'preview', fake_preview)

    status = main(['arxiv', '--preview'])

    assert status == 0
    assert compiled['source'] == project / 'build' / 'arxiv'
    assert compiled['destination'] == project / 'build' / 'arxiv-preview'
    assert 'preview at' in capsys.readouterr().out


def test_arxiv_reports_what_would_be_rejected_and_fails(project, capsys):
    _break_the_paper(project)

    status = main(['arxiv'])

    printed = capsys.readouterr().out
    assert status == 1
    assert 'expansion=true' in printed
    assert '1 problem(s)' in printed


def test_arxiv_writes_nothing_when_the_check_failed(project):
    _break_the_paper(project)

    main(['arxiv', '--tar'])

    # the check runs before anything is written, so a rejected submission leaves no half-built
    # directory and no tarball to upload by mistake
    assert not (project / 'build').exists()


def test_a_failed_check_fails_under_dry_run_too(project, capsys):
    _break_the_paper(project)

    status = main(['arxiv', '--dry-run'])

    assert status == 1
    assert '(dry run' not in capsys.readouterr().out, 'the problems are the result, not an aside'
