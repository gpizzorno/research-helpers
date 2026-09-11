"""Wiring discovery, loading and resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_helpers.project import (
    ArxivSettings,
    ConfigWarning,
    FigureSettings,
    PaperSettings,
    Project,
    ProjectRootNotFoundError,
    _load,
    find_project_root,
)

SETTINGS = """
[tool.research-helpers.paper]
main = "manuscript/article.tex"
build-dir = "out"
text-width-in = 5.5

[tool.research-helpers.figures]
profile = "print"
dpi = 300

[tool.research-helpers.arxiv]
engine = "pdflatex"
"""


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Wiring is cached per root and overridable by environment. Neither may leak between tests."""
    monkeypatch.delenv('RESEARCH_HELPERS_ROOT', raising=False)
    _load.cache_clear()
    yield
    _load.cache_clear()


@pytest.fixture
def project_dir(tmp_path):
    """Return a project root carrying settings, with a nested directory to search up from."""
    (tmp_path / 'pyproject.toml').write_text(SETTINGS, encoding='utf-8')
    (tmp_path / 'notebooks' / 'drafts').mkdir(parents=True)
    return tmp_path


# --- root discovery ---------------------------------------------------------------------------


def test_finds_the_root_from_a_nested_subdirectory(project_dir):
    assert find_project_root(project_dir / 'notebooks' / 'drafts') == project_dir


def test_a_bare_git_directory_also_marks_the_root(tmp_path):
    (tmp_path / '.git').mkdir()
    (tmp_path / 'src').mkdir()

    assert find_project_root(tmp_path / 'src') == tmp_path


def test_the_environment_variable_overrides_the_search(project_dir, tmp_path, monkeypatch):
    elsewhere = tmp_path.parent / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.setenv('RESEARCH_HELPERS_ROOT', str(elsewhere))

    assert find_project_root(project_dir) == elsewhere.resolve()


def test_an_unmarked_tree_raises(tmp_path):
    # / always exists, so search from a temp dir only works if no ancestor carries a marker
    unmarked = tmp_path / 'nothing' / 'here'
    unmarked.mkdir(parents=True)

    with pytest.raises(ProjectRootNotFoundError, match=r'pyproject\.toml'):
        find_project_root(unmarked)


# --- loading ----------------------------------------------------------------------------------


def test_settings_are_read_and_paths_resolved_against_the_root(project_dir):
    project = Project.from_pyproject(project_dir / 'notebooks')

    assert project.root == project_dir
    assert project.paper.main == project_dir / 'manuscript' / 'article.tex'
    assert project.paper.build_dir == project_dir / 'out'
    assert project.figures.profile == 'print'
    assert project.paper.text_width_in == 5.5
    assert project.figures.dpi == 300
    assert project.arxiv.engine == 'pdflatex'


def test_paths_resolve_against_the_pyproject_not_the_working_directory(project_dir, monkeypatch, tmp_path):
    somewhere_else = tmp_path.parent / 'cwd'
    somewhere_else.mkdir()
    monkeypatch.chdir(somewhere_else)

    project = Project.from_pyproject(project_dir)

    assert project.paper.main == project_dir / 'manuscript' / 'article.tex'


def test_unset_keys_keep_their_defaults(project_dir):
    project = Project.from_pyproject(project_dir)

    assert project.paper.tables_dir == project_dir / PaperSettings.tables_dir
    assert project.figures.palette == FigureSettings.palette
    assert project.arxiv.texlive == ArxivSettings.texlive


def test_a_project_with_no_settings_section_gets_pure_defaults(tmp_path):
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "unrelated"\n', encoding='utf-8')

    project = Project.from_pyproject(tmp_path)

    assert project.pyproject is None
    assert project.paper.main == tmp_path / PaperSettings.main
    assert set(project.sources.values()) == {'default'}


def test_a_root_without_a_pyproject_at_all_gets_pure_defaults(tmp_path):
    (tmp_path / '.git').mkdir()

    project = Project.from_pyproject(tmp_path)

    assert project.pyproject is None
    assert project.figures.dpi == FigureSettings.dpi


def test_an_absolute_path_in_the_settings_is_left_alone(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\nmain = "/elsewhere/paper.tex"\n',
        encoding='utf-8',
    )

    project = Project.from_pyproject(tmp_path)

    assert project.paper.main == Path('/elsewhere/paper.tex')


# --- provenance and overrides -----------------------------------------------------------------


def test_each_setting_records_where_it_came_from(project_dir):
    project = Project.from_pyproject(project_dir)

    assert project.sources['paper.main'] == 'pyproject'
    assert project.sources['paper.tables_dir'] == 'default'
    assert project.sources['figures.dpi'] == 'pyproject'
    assert project.sources['figures.palette'] == 'default'


def test_explicit_arguments_beat_the_pyproject(project_dir):
    project = Project.from_pyproject(project_dir, figures=FigureSettings(profile='screen', dpi=72))

    assert project.figures.dpi == 72
    assert project.figures.profile == 'screen'
    assert project.sources['figures.*'] == 'argument'
    assert project.paper.main == project_dir / 'manuscript' / 'article.tex'


def test_an_unknown_settings_group_is_a_programming_error(project_dir):
    with pytest.raises(TypeError, match='unknown settings group'):
        Project.from_pyproject(project_dir, tables=PaperSettings())


# --- lengths in other units -------------------------------------------------------------------


def test_doctor_does_not_print_a_converted_length_to_full_precision(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\ntext-width-pt = 468.0\n',
        encoding='utf-8',
    )

    printed = Project.from_pyproject(tmp_path).doctor()

    assert '6.4757 ' in printed
    assert '6.475716064757161' not in printed


def _paper(tmp_path, body):
    (tmp_path / 'pyproject.toml').write_text(f'[tool.research-helpers.paper]\n{body}', encoding='utf-8')
    return tmp_path


def test_a_length_can_be_written_in_millimetres(tmp_path):
    project = Project.from_pyproject(_paper(tmp_path, 'text-width-mm = 164.0\n'))

    assert project.paper.text_width_in == pytest.approx(164.0 / 25.4)


def test_a_length_can_be_written_in_centimetres(tmp_path):
    project = Project.from_pyproject(_paper(tmp_path, 'text-width-cm = 16.4\n'))

    assert project.paper.text_width_in == pytest.approx(16.4 / 2.54)


def test_a_length_can_be_written_in_tex_points(tmp_path):
    # 468.0 is what '\showthe\textwidth' prints, so the common case needs no arithmetic by hand
    project = Project.from_pyproject(_paper(tmp_path, 'text-width-pt = 468.0\n'))

    assert project.paper.text_width_in == pytest.approx(468.0 / 72.27)


def test_a_tex_point_is_not_a_postscript_point(tmp_path):
    r"""TeX's pt is 1/72.27in; the big point '\includegraphics' uses is 1/72in. They differ by 0.37%."""
    project = Project.from_pyproject(_paper(tmp_path, 'text-width-pt = 468.0\n'))

    assert project.paper.text_width_in != pytest.approx(468.0 / 72.0)


def test_units_apply_to_every_length_whatever_the_section(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\ncolumn-width-mm = 77.0\n\n[tool.research-helpers.figures]\nprint-height-cm = 6.0\n',
        encoding='utf-8',
    )

    project = Project.from_pyproject(tmp_path)

    assert project.paper.column_width_in == pytest.approx(77.0 / 25.4)
    assert project.figures.print_height_in == pytest.approx(6.0 / 2.54)


def test_inches_remain_the_canonical_spelling(tmp_path):
    project = Project.from_pyproject(_paper(tmp_path, 'text-width-in = 6.45\n'))

    assert project.paper.text_width_in == 6.45


def test_a_unit_suffix_on_something_that_is_not_a_length_is_still_unknown(tmp_path):
    # 'main' is a path, so 'main-mm' must not be quietly accepted as a unit spelling of it
    with pytest.warns(ConfigWarning, match='unknown key "main-mm"'):
        project = Project.from_pyproject(_paper(tmp_path, 'main-mm = 3.0\n'))

    assert project.paper.main == tmp_path / PaperSettings.main


def test_an_unrecognised_unit_is_an_unknown_key(tmp_path):
    with pytest.warns(ConfigWarning, match='unknown key "text-width-furlong"'):
        project = Project.from_pyproject(_paper(tmp_path, 'text-width-furlong = 0.00008\n'))

    assert project.paper.text_width_in == PaperSettings.text_width_in


def test_the_same_length_in_two_units_warns_and_takes_the_first(tmp_path):
    # order in the file decides, so the result cannot depend on which spelling the reader prefers
    with pytest.warns(ConfigWarning, match='set twice.*Using "text-width-mm"'):
        project = Project.from_pyproject(_paper(tmp_path, 'text-width-mm = 164.0\ntext-width-in = 6.45\n'))

    assert project.paper.text_width_in == pytest.approx(164.0 / 25.4)


# --- bad input warns rather than failing the build ---------------------------------------------


def test_an_unknown_key_warns_and_is_ignored(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\nmian = "typo.tex"\n',
        encoding='utf-8',
    )

    with pytest.warns(ConfigWarning, match='unknown key "mian"'):
        project = Project.from_pyproject(tmp_path)

    assert project.paper.main == tmp_path / PaperSettings.main


def test_an_unknown_section_warns_and_is_ignored(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.zenodo]\ndeposit = "x"\n',
        encoding='utf-8',
    )

    with pytest.warns(ConfigWarning, match=r'unknown section \[tool.research-helpers.zenodo\]'):
        Project.from_pyproject(tmp_path)


def test_a_value_of_the_wrong_type_warns_and_falls_back(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.figures]\ndpi = "lots"\n',
        encoding='utf-8',
    )

    with pytest.warns(ConfigWarning, match='figures.dpi must be a int'):
        project = Project.from_pyproject(tmp_path)

    assert project.figures.dpi == FigureSettings.dpi
    assert project.sources['figures.dpi'] == 'default'


def test_a_boolean_does_not_slip_through_as_an_integer(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.figures]\ndpi = true\n',
        encoding='utf-8',
    )

    with pytest.warns(ConfigWarning, match='must be a int, not bool'):
        project = Project.from_pyproject(tmp_path)

    assert project.figures.dpi == FigureSettings.dpi


def test_an_integer_is_accepted_for_a_float_setting(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.paper]\ntext-width-in = 7\n',
        encoding='utf-8',
    )

    project = Project.from_pyproject(tmp_path)

    assert project.paper.text_width_in == 7.0
    assert isinstance(project.paper.text_width_in, float)


def test_an_unrecognised_profile_warns_and_falls_back(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.research-helpers.figures]\nprofile = "poster"\n',
        encoding='utf-8',
    )

    with pytest.warns(ConfigWarning, match='profile must be one of'):
        project = Project.from_pyproject(tmp_path)

    assert project.figures.profile == FigureSettings.profile


# --- doctor -----------------------------------------------------------------------------------


def test_doctor_reports_every_setting_its_source_and_what_is_missing(project_dir):
    (project_dir / 'out').mkdir()  # paper.build_dir exists; manuscript/ deliberately does not

    report = Project.from_pyproject(project_dir).doctor()
    entries = {line.split()[0]: line for line in report.splitlines() if line.startswith('  ') and line.strip()}

    assert entries.keys() >= {'paper.main', 'paper.tables_dir', 'figures.dpi', 'arxiv.engine'}
    assert 'manuscript/article.tex' in entries['paper.main']
    assert '[pyproject]' in entries['paper.main']
    assert '[default]' in entries['paper.tables_dir']
    assert 'MISSING' in entries['paper.main']
    assert 'MISSING' not in entries['paper.build_dir']
    assert str(project_dir) in report


def test_doctor_says_so_when_there_are_no_settings(tmp_path):
    (tmp_path / '.git').mkdir()

    report = Project.from_pyproject(tmp_path).doctor()

    assert 'none found' in report
    assert 'Defaults apply throughout.' in report
